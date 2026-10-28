"""Compact, read-only blueprint readiness with witnessed conflict-aware bounds.

Inputs are limited to 100 slots and 100 requested questions. Similarity is a
pairwise constraint, never a transitive family merge. Counts of exclusion reasons
can overlap and are not additive. No content/solution/rubric columns are read. Instructor review actions never approve.
"""

import copy
import json
import math
from collections import defaultdict

from ..errors import CourseNotFoundError, ValidationError
from ..questions.catalog import current_relations_sql, require_text
from ..storage.repositories import CourseRepository, TopicRepository, ReservationRepository

RELAXABLE_FIELDS = ("source_version_ids", "year_min", "year_max", "difficulty")
SEARCH_NODE_BUDGET = 20000


def _positive(value, name):
    try:
        valid = type(value) in (int, float) and math.isfinite(value) and value > 0
    except OverflowError:
        valid = False
    if not valid:
        raise ValidationError(name + " must be a positive finite number.")


def validate_paper_settings(blueprint):
    if 'duration_minutes' in blueprint:
        _positive(blueprint['duration_minutes'], 'duration_minutes')
    if 'instructions' in blueprint:
        if not isinstance(blueprint['instructions'], list) or any(not isinstance(v, str) or not v.strip() for v in blueprint['instructions']):
            raise ValidationError('instructions must be a list of nonempty strings.')


def _validate(con, course, blueprint, learner):
    require_text(course, "course_id")
    if not CourseRepository(con).get_course(course):
        raise CourseNotFoundError(course)
    require_text(learner, "learner_id")
    if not isinstance(blueprint, dict) or set(blueprint) - {"slots", "duration_minutes", "relaxations", "shuffle_options", "instructions"} or "slots" not in blueprint:
        raise ValidationError("blueprint must contain slots and only supported strict policy fields.")
    policy = blueprint.get("relaxations", [])
    if (not isinstance(policy, list) or any(not isinstance(k, str) or k not in RELAXABLE_FIELDS for k in policy)
            or len(set(policy)) != len(policy)):
        raise ValidationError("relaxations must be a unique ordered list of source_version_ids, year_min, year_max or difficulty.")
    if "shuffle_options" in blueprint and blueprint["shuffle_options"] is not False:
        raise ValidationError("Option shuffling is unsupported.")
    validate_paper_settings(blueprint)
    slots = blueprint["slots"]
    if not isinstance(slots, list) or not 1 <= len(slots) <= 100:
        raise ValidationError("slots must contain between 1 and 100 slots.")
    seen, total = set(), 0
    for slot in slots:
        if not isinstance(slot, dict) or set(slot) - {"id", "count", "section", "question_type", "topic_ids", "max_points", "source_version_ids", "year_min", "year_max", "difficulty"}:
            raise ValidationError("Invalid slot object or unsupported constraint.")
        require_text(slot.get("id"), "slot id")
        if slot["id"] in seen:
            raise ValidationError("Slot IDs must be distinct.")
        seen.add(slot["id"])
        if type(slot.get("count")) is not int or slot["count"] <= 0:
            raise ValidationError("slot count must be a positive integer.")
        total += slot["count"]
        if "max_points" in slot:
            _positive(slot["max_points"], "max_points")
        if "difficulty" in slot:
            require_text(slot["difficulty"], "difficulty")
        for key in ("year_min", "year_max"):
            if key in slot and (type(slot[key]) is not int or not 1 <= slot[key] <= 9999):
                raise ValidationError("Year bounds must be integer years between 1 and 9999.")
        if slot.get("year_min", 1) > slot.get("year_max", 9999):
            raise ValidationError("year_min exceeds year_max.")
        if "source_version_ids" in slot:
            ids = slot["source_version_ids"]
            if not isinstance(ids, list) or not ids:
                raise ValidationError("source_version_ids must be a nonempty list.")
            for source_id in ids:
                require_text(source_id, "source_version_id")
                if not con.execute("SELECT 1 FROM source_versions WHERE id=? AND course_id=?", (source_id, course)).fetchone():
                    raise ValidationError("Source version not found in this course.")
        for key in ("section", "question_type"):
            if key in slot:
                require_text(slot[key], key)
        if "topic_ids" in slot:
            tids = slot["topic_ids"]
            if not isinstance(tids, list) or not tids:
                raise ValidationError("topic_ids must be a nonempty list.")
            for tid in tids:
                require_text(tid, "topic_id")
                TopicRepository(con).require_course_topic(course, tid)
    if total > 100:
        raise ValidationError("Blueprint may request at most 100 questions.")
    return slots


def _json(raw, kind):
    try:
        value = json.loads(raw)
        return value if isinstance(value, kind) else kind()
    except (ValueError, TypeError):
        return kind()


def _ids(rows):
    return {"count": len(rows), "version_ids": sorted(rows),
            "occurrence_ids": sorted({q["id"] for r in rows.values() for q in r["occurrences"]}),
            "family_ids": sorted({r["exercise_family"] for r in rows.values() if r["exercise_family"]})}


def _matching(slots, candidates, rows, copies):
    """Integral family/slot b-matching, also retaining a variant witness."""
    units = [s["id"] for s in slots for _ in range(s["count"] * copies)]
    by_slot = {s["id"]: {} for s in slots}
    for sid, versions in candidates.items():
        for vid in versions:
            by_slot[sid].setdefault(rows[vid]["exercise_family"], vid)
    owners, chosen = {}, {}

    def augment(unit):
        # Iterative alternating-path search avoids recursion limits on large banks.
        queue, seen_units, seen_families, parent = [unit], {unit}, set(), {}
        for current in queue:
            for family, vid in sorted(by_slot[units[current]].items()):
                if family in seen_families:
                    continue
                seen_families.add(family)
                parent[family] = (current, vid)
                if family not in owners:
                    while True:
                        previous, version = parent[family]
                        old_family = rows[chosen[previous]]["exercise_family"] if previous in chosen else None
                        owners[family] = previous
                        chosen[previous] = version
                        if old_family is None:
                            return
                        family = old_family
                owner = owners[family]
                if owner not in seen_units:
                    seen_units.add(owner)
                    queue.append(owner)

    for unit in range(len(units)):
        augment(unit)
    return units, [(units[u], chosen[u]) for u in sorted(chosen)]


def _solve(slots, candidates, rows, conflicts, copies, budget):
    units, relaxed = _matching(slots, candidates, rows, copies)
    upper = len(relaxed)
    best, families, selected = [], set(), set()
    for sid, vid in relaxed:
        family = rows[vid]["exercise_family"]
        if family not in families and not (conflicts[vid] & selected):
            best.append((sid, vid))
            families.add(family)
            selected.add(vid)
    if len(best) == upper:
        return best, upper, True
    # Units with no candidates never need a recursive search level.
    units = sorted((u for u in units if candidates[u]), key=lambda u: (len(candidates[u]), u))
    exhausted = False

    def search(index, assignment, used, picked, last):
        nonlocal best, exhausted
        if len(best) == upper or len(assignment) + len(units) - index <= len(best):
            return
        if budget[0] <= 0:
            exhausted = True
            return
        budget[0] -= 1
        if len(assignment) > len(best):
            best = assignment[:]
        if index == len(units):
            return
        sid = units[index]
        for vid in candidates[sid]:
            family = rows[vid]["exercise_family"]
            if family in used or conflicts[vid] & picked or vid <= last.get(sid, ""):
                continue
            search(index + 1, assignment + [(sid, vid)], used | {family}, picked | {vid}, {**last, sid: vid})
            if exhausted or len(best) == upper:
                return
        search(index + 1, assignment, used, picked, last)

    # Avoid Python recursion failure for very large banks: this is a budget stop,
    # not evidence of infeasibility. The relaxed and greedy bounds remain valid.
    if len(units) < 800:
        search(0, [], set(), set(), {})
    else:
        exhausted = True
    exact = len(best) == upper or not exhausted
    return best, len(best) if exact else upper, exact


def _analysis(slots, candidates, rows, conflicts):
    budget = [SEARCH_NODE_BUDGET]
    witness, upper, exact = _solve(slots, candidates, rows, conflicts, 1, budget)
    needed = sum(s["count"] for s in slots)
    lower = len(witness)
    state = "feasible" if lower == needed else "infeasible" if upper < needed else "unknown"
    families = {rows[v]["exercise_family"] for vs in candidates.values() for v in vs}
    cap_upper = len(families) // needed
    # Relaxed matching produces a finite Hall-aware upper bound on complete tests.
    lo, hi = 0, cap_upper
    while lo < hi:
        mid = (lo + hi + 1) // 2
        _, match = _matching(slots, candidates, rows, mid)
        if len(match) == needed * mid:
            lo = mid
        else:
            hi = mid - 1
    cap_upper = lo
    cap_lower = 1 if lower == needed else 0
    if upper < needed:
        cap_upper = 0
    while cap_lower < cap_upper:
        mid = (cap_lower + cap_upper + 1) // 2
        assignment, bound, _ = _solve(slots, candidates, rows, conflicts, mid, budget)
        if len(assignment) == needed * mid:
            cap_lower = mid
        elif bound < needed * mid:
            cap_upper = mid - 1
        else:
            break
    # A residual alternating-path cut identifies shared-pool/Hall bottlenecks;
    # unrelated independently fillable slots are omitted from this cut.
    _, relaxed = _matching(slots, candidates, rows, 1)
    assigned = defaultdict(list)
    owner = {}
    for sid, vid in relaxed:
        assigned[sid].append(vid)
        owner[rows[vid]["exercise_family"]] = sid
    affected = {s["id"] for s in slots if len(assigned[s["id"]]) < s["count"]}
    family_edges = {sid: {rows[v]["exercise_family"] for v in vids} for sid, vids in candidates.items()}
    frontier = sorted(affected)
    for sid in frontier:
        for family in sorted(family_edges[sid]):
            other = owner.get(family)
            if other is not None and other not in affected:
                affected.add(other)
                frontier.append(other)
    overlap = []
    if affected:
        pool = set().union(*(family_edges[sid] for sid in affected))
        demand = sum(s["count"] for s in slots if s["id"] in affected)
        overlap.append({"reason": "shared_family_pool_shortfall", "slot_ids": sorted(affected),
                        "topic_ids": sorted({t for s in slots if s["id"] in affected for t in s.get("topic_ids", [])}),
                        "needed": demand, "available_families": len(pool), "shortfall": demand - len(pool)})
    gaps = []
    if state != "feasible":
        gaps.append({"reason": "joint_conflict_or_shared_pool" if exact else "search_budget_exhausted",
                     "slot_ids": [s["id"] for s in slots],
                     "topic_ids": sorted({t for s in slots for t in s.get("topic_ids", [])}),
                     "shortfall_lower_bound": needed - upper, "shortfall_upper_bound": needed - lower})
    return {"joint": {"status": state, "needed": needed, "matched_lower_bound": lower,
                      "matched_upper_bound": upper, "exact": exact,
                      "overlap_bottlenecks": overlap,
                      "assignment": [{"slot_id": s, "version_id": v, "family_id": rows[v]["exercise_family"]}
                                     for s, v in sorted(witness)], "gaps": gaps},
            "capacity": {"lower_bound": cap_lower, "upper_bound": cap_upper, "exact": cap_lower == cap_upper,
                         "method": "family_matching_and_budgeted_pairwise_conflict_search",
                         "limitations": ["Recorded similarity is conservative and incomplete.",
                                         "Budget exhaustion leaves bounds, not a maximum estimate.",
                                         "Conflict search stops before 800 assignment units to bound stack depth."],
                         "search_nodes_used": SEARCH_NODE_BUDGET - budget[0]}}


def blueprint_readiness(con, course_id, blueprint, learner_id="default_learner"):
    """Inspect one consistent read snapshot; preserve an existing transaction."""
    own_transaction = not con.in_transaction
    if own_transaction:
        con.execute("BEGIN")
    try:
        return _report(con, course_id, blueprint, learner_id)
    finally:
        if own_transaction:
            con.execute("ROLLBACK")


def _provenance_slots(blueprint):
    return {s["id"] for s in blueprint["slots"] if any(k in s for k in RELAXABLE_FIELDS)}


def _report(con, course_id, blueprint, learner_id, *, internal=False, live_request_ids=None, exclude_request_id=None):
    # Validate every original constraint before an authorized prefix can remove it.
    _validate(con, course_id, blueprint, learner_id)
    effective = copy.deepcopy(blueprint)
    effective["relaxations"] = []
    attempted, applied = [], []
    for field in [None, *blueprint.get("relaxations", [])]:
        if field is not None:
            for slot in effective["slots"]:
                slot.pop(field, None)
            applied.append(field)
        result = _report_once(con, course_id, effective, learner_id, internal=True,
            live_request_ids=live_request_ids, exclude_request_id=exclude_request_id,
            required_provenance_slots=_provenance_slots(blueprint))
        report = result[0]
        attempted.append({"applied": list(applied), "status": report["analysis"]["joint"]["status"],
                          "gaps": copy.deepcopy(report["gaps"])})
        if report["analysis"]["joint"]["status"] == "feasible":
            break
    report["relaxation_policy"] = {"attempted": attempted, "applied": applied,
                                    "effective_blueprint": effective}
    if internal:
        return result
    report.pop("relaxation_policy")
    return report


def _report_once(con, course_id, blueprint, learner_id, *, internal=False, live_request_ids=None,
                 exclude_request_id=None, required_provenance_slots=()):
    slots = _validate(con, course_id, blueprint, learner_id)
    topics = TopicRepository(con).list_topics(course_id)
    lookup = {key: t.id for t in topics for key in (t.id, t.slug)}
    rows = {r["id"]: dict(r) for r in con.execute("""SELECT v.id,v.validation_state,v.topic_mappings_json,
        x.exercise_family,f.exact_hash,f.structure_hash,v.revision_history_json FROM exercise_versions v
        JOIN exercises x ON x.id=v.exercise_id LEFT JOIN question_fingerprints f ON f.exercise_version_id=v.id
        WHERE v.course_id=? ORDER BY v.id""", (course_id,))}
    for r in rows.values():
        r["occurrences"] = []
        r["revision"] = len(_json(r.pop("revision_history_json"), list)) + 1
        mapping = _json(r.pop("topic_mappings_json"), list)
        r["topics"] = {lookup[m] for m in mapping if isinstance(m, str) and m in lookup}
        r["topics_unknown"] = not mapping or any(not isinstance(m, str) or m not in lookup for m in mapping)
    for q in con.execute("""SELECT id,exercise_version_id,source_version_id,review_status,visual_review_status,metadata_json,revision
                             FROM question_occurrences WHERE course_id=? ORDER BY id""", (course_id,)):
        if q["exercise_version_id"] in rows:
            rows[q["exercise_version_id"]]["occurrences"].append(dict(q))
    related, rejected = set(), set()
    for r in con.execute("SELECT left_version_id,right_version_id,status FROM (" +
                         current_relations_sql() + ") WHERE course_id=?", (course_id,)):
        pair = frozenset((r["left_version_id"], r["right_version_id"]))
        (rejected if r["status"] == "rejected" else related).add(pair)

    groups = {key: defaultdict(set) for key in ("exercise_family", "exact_hash", "structure_hash")}
    adjacency = defaultdict(set)
    for pair in related:
        if len(pair) == 2:
            a, b = pair
            adjacency[a].add(b)
            adjacency[b].add(a)
    for vid, row in rows.items():
        for key, index in groups.items():
            if row[key]:
                index[row[key]].add(vid)

    def neighbors(vid):
        row = rows[vid]
        result = {vid} | adjacency[vid]
        for key in ("exercise_family", "exact_hash"):
            if row[key]:
                result.update(groups[key][row[key]])
        if row["structure_hash"]:
            result.update(other for other in groups["structure_hash"][row["structure_hash"]]
                          if frozenset((vid, other)) not in rejected)
        return result & rows.keys()

    attempts = {r[0] for r in con.execute("SELECT exercise_version_id FROM attempts WHERE course_id=? AND learner_id=?", (course_id, learner_id))} & rows.keys()
    repository = ReservationRepository(con)
    saved = list(con.execute("""SELECT a.id,i.exercise_version_id FROM assessment_items i
        JOIN assessments a ON a.id=i.assessment_id WHERE a.course_id=?
        AND (a.learner_id=? OR a.learner_id IS NULL) AND """ + repository.active_predicate("a.id"),
        (course_id, learner_id)))
    # Only saved unused drafts are safe in a read-only counterfactual. Pending
    # jobs remain reserved: readiness does not acquire publication locks.
    safe_ids = sorted({r["id"] for r in saved
        if repository.unused_reason(r["id"]) is None and not con.execute(
            "SELECT 1 FROM assembly_jobs WHERE assessment_id=? AND state!='published'",
            (r["id"],)).fetchone()})
    reserved = {r["exercise_version_id"] for r in saved} & rows.keys()
    unsafe_reserved = {r["exercise_version_id"] for r in saved if r["id"] not in safe_ids}
    # Liveness is supplied by the coordinator after nonblocking OS lock checks.
    # Without that knowledge readiness conservatively reserves pending jobs.
    from ..storage.repositories import AssemblyRepository
    for reservation in AssemblyRepository(con).reservations(course_id):
        if (reservation["learner_id"] == learner_id and reservation["request_id"] != exclude_request_id
                and (live_request_ids is None or reservation["request_id"] in live_request_ids)):
            reserved.add(reservation["exercise_version_id"])
            unsafe_reserved.add(reservation["exercise_version_id"])
    reserved &= rows.keys()
    exposure = set().union(*(neighbors(v) for v in attempts))
    reservations = set().union(*(neighbors(v) for v in reserved))
    unsafe_reservations = set().union(*(neighbors(v) for v in unsafe_reserved & rows.keys()))
    candidates, without, safe_without, reports, reservation_only = {}, {}, {}, [], {}
    for slot in slots:
        usable, unreserved = {}, {}
        reasons, unknown = defaultdict(dict), defaultdict(dict)
        pending = {}
        for vid, row in rows.items():
            missing, potential, fits = set(), False, False
            topic_missing = "topic_ids" in slot and not row["topics"].intersection(slot["topic_ids"])
            if topic_missing and not row["topics_unknown"]:
                reasons["topic_mismatch"][vid] = row
                continue
            for q in row["occurrences"] or [None]:
                meta = _json(q["metadata_json"], dict) if q else {}
                fields, mismatch = set(), False
                if topic_missing:
                    fields.add("topic_ids")
                for key in ("section", "question_type"):
                    if key not in slot:
                        continue
                    value = meta.get(key)
                    if not isinstance(value, str) or not value.strip():
                        fields.add(key)
                    elif value != slot[key]:
                        mismatch = True
                constrained = slot["id"] in required_provenance_slots or any(k in slot for k in RELAXABLE_FIELDS)
                trusted = q and q["review_status"] == "accepted" and q["visual_review_status"] in ("verified", "not_required")
                if constrained and not trusted:
                    fields.add("reviewed_provenance")
                if "source_version_ids" in slot:
                    if not q:
                        fields.add("source_version_ids")
                    elif q["source_version_id"] not in slot["source_version_ids"]:
                        mismatch = True
                if "difficulty" in slot:
                    value = meta.get("difficulty")
                    if not isinstance(value, str) or not value.strip():
                        fields.add("difficulty")
                    elif value != slot["difficulty"]:
                        mismatch = True
                if "year_min" in slot or "year_max" in slot:
                    from ..questions.provenance import verified_year
                    year = verified_year(meta)
                    if type(year) is not int or not 1 <= year <= 9999:
                        fields.add("year")
                    elif not slot.get("year_min", 1) <= year <= slot.get("year_max", 9999):
                        mismatch = True
                if not mismatch:
                    potential = True
                    missing.update(fields)
                    fits |= not fields
            if not potential:
                reasons["metadata_mismatch"][vid] = row
                continue
            if not fits:
                for field in missing:
                    unknown[field][vid] = row
                reasons["missing_required_metadata"][vid] = row
            gates = set()
            state = row["validation_state"]
            if state != "validated":
                gates.add("math_pending_review" if state == "pending_review" else "math_" + state)
            if not row["exercise_family"] or not row["exercise_family"].strip():
                gates.add("missing_family")
            for q in row["occurrences"]:
                if q["review_status"] != "accepted":
                    gates.add("extraction_" + q["review_status"])
                if q["visual_review_status"] not in ("verified", "not_required"):
                    gates.add("visual_" + q["visual_review_status"])
            for reason in gates:
                reasons[reason][vid] = row
                if "pending" in reason or "unknown" in reason:
                    pending[vid] = row
            if vid in exposure:
                reasons["learner_exposure"][vid] = row
            if vid in reservations:
                reasons["assessment_reservation"][vid] = row
            if fits and not gates and vid not in exposure:
                unreserved[vid] = row
                if vid not in reservations:
                    usable[vid] = row
                else:
                    reservation_only[vid] = row
        candidates[slot["id"]] = sorted(usable)
        without[slot["id"]] = sorted(unreserved)
        safe_without[slot["id"]] = sorted(unreserved.keys() - unsafe_reservations)
        available = len(_ids(usable)["family_ids"])
        shortfall = max(0, slot["count"] - available)
        reports.append({"slot_id": slot["id"], "topic_ids": sorted(slot.get("topic_ids", [])),
                        "section": slot.get("section"), "question_type": slot.get("question_type"),
                        "needed": slot["count"], "available": available, "shortfall": shortfall,
                        "eligible": _ids(usable), "pending_review": _ids(pending),
                        "unknown_required_metadata": {k: _ids(v) for k, v in sorted(unknown.items())},
                        "exclusions": {k: _ids(v) for k, v in sorted(reasons.items())},
                        "safe_release_relief": _ids({v: rows[v] for v in set(safe_without[slot["id"]]) - usable.keys()}),
                        "reservation_only": _ids({v: rows[v] for v in unreserved.keys() - usable.keys()}),
                        "gaps": ([{"reason": "marginal_shortfall", "slot_ids": [slot["id"]],
                                   "topic_ids": sorted(slot.get("topic_ids", [])), "shortfall": shortfall}] if shortfall else [])})
    pool = {v for vs in without.values() for v in vs}
    conflicts = {v: (neighbors(v) & pool) - {v} for v in sorted(pool)}
    from ..questions.constraints import load
    from .combinations import enumerate_exams
    constraints = load(con, course_id)
    def prune(pool):
        changed = True
        while changed:
            available = {v for values in pool.values() for v in values}
            blocked = {v for v in available if constraints[v].get('stale') or any(
                link['exercise_version_id'] not in available for link in constraints[v]['depends_on'])}
            changed = bool(blocked)
            for sid in pool:
                pool[sid] = [v for v in pool[sid] if v not in blocked]
    before_constraints = {sid: set(values) for sid, values in candidates.items()}
    for pool in (candidates, without, safe_without):
        prune(pool)
    for slot in reports:
        sid = slot['slot_id']
        slot['safe_release_relief'] = _ids({v: rows[v] for v in set(safe_without[sid]) - set(candidates[sid])})
        slot['reservation_only'] = _ids({v: rows[v] for v in set(without[sid]) - set(candidates[sid])})
        removed = before_constraints[sid] - set(candidates[sid])
        if removed:
            slot['exclusions']['question_constraints'] = _ids({v: rows[v] for v in removed})
            slot['eligible'] = _ids({v: rows[v] for v in candidates[sid]})
            slot['available'] = len(slot['eligible']['family_ids'])
            slot['shortfall'] = max(0, slot['needed'] - slot['available'])
            slot['gaps'] = ([{'reason': 'question_constraints', 'slot_ids': [sid],
                             'shortfall': slot['shortfall']}] if slot['shortfall'] else [])
    from .review_actions import actions
    for slot in reports:
        slot['review_actions'] = actions(slot, rows, constraints)
        slot['marginal_extra_families_for_second_disjoint_paper'] = max(0, 2 * slot['needed'] - slot['available'])
    # Answer disclosures are directional metadata, but either selection order leaks.
    for vid, rules in constraints.items():
        for link in rules['gives_away']:
            other = link['exercise_version_id']
            if vid in conflicts and other in conflicts:
                conflicts[vid].add(other)
                conflicts[other].add(vid)
    normal = _analysis(slots, candidates, rows, conflicts)
    relief = _analysis(slots, without, rows, conflicts)
    safe_relief = _analysis(slots, safe_without, rows, conflicts)
    for analysis, pool in ((normal, candidates), (relief, without), (safe_relief, safe_without)):
        combinations, witness = enumerate_exams(slots, pool, rows, conflicts, constraints, SEARCH_NODE_BUDGET)
        analysis['distinct_exams'] = combinations
        if any(c.get('depends_on') or c.get('stale') for c in constraints.values()):
            joint = analysis['joint']
            needed = joint['needed']
            joint.update(status='feasible' if witness else 'infeasible' if combinations['exact'] else 'unknown',
                         matched_lower_bound=needed if witness else 0,
                         matched_upper_bound=needed if witness or not combinations['exact'] else max(0, needed-1),
                         exact=bool(witness) or combinations['exact'],
                         assignment=[{'slot_id': sid, 'version_id': v, 'family_id': rows[v]['exercise_family']}
                                     for sid, v in (witness or [])])
            capacity = analysis['capacity']
            capacity['lower_bound'] = 1 if witness else 0
            if combinations['exact'] and not witness:
                capacity['upper_bound'] = 0
            capacity['exact'] = capacity['lower_bound'] == capacity['upper_bound']
            capacity['limitations'].append('Dependency-aware disjoint capacity is bounded; prerequisites must belong to each individual exam.')
    a, b = normal["capacity"], relief["capacity"]
    def improvement(capacity):
        return {"lower_bound": max(0, capacity["lower_bound"] - a["upper_bound"]),
                "upper_bound": max(0, capacity["upper_bound"] - a["lower_bound"]),
                "exact": a["exact"] and capacity["exact"],
                "relief": "proven" if capacity["lower_bound"] > a["upper_bound"] else "uncertain" if not (a["exact"] and capacity["exact"]) else "none"}

    topic_bottlenecks = []
    for topic in sorted({t for slot in slots for t in slot.get("topic_ids", [])}):
        relevant = [s for s in reports if topic in s["topic_ids"]]
        versions = {v for s in relevant for v in candidates[s["slot_id"]] if topic in rows[v]["topics"]}
        topic_bottlenecks.append({"topic_id": topic, "slot_ids": [s["slot_id"] for s in relevant],
            "eligible": _ids({v: rows[v] for v in versions}),
            "marginal_gap_slot_ids": [s["slot_id"] for s in relevant if s["shortfall"]],
            "reservation_only": _ids({v: rows[v] for s in relevant for v in s["reservation_only"]["version_ids"]
                                      if topic in rows[v]["topics"]}),
            "demand_semantics": "A slot accepts ANY listed topic; topic demands are not additive."})
    result = {"course_id": course_id, "learner_id": learner_id, "recorded": False, "slots": reports,
            "analysis": normal, "without_reservations": relief, "topic_bottlenecks": topic_bottlenecks, "reservation_only": _ids(reservation_only),
            "without_reservations_scope": "All active reservations removed; learner exposure retained; not a safe-release recommendation.",
            "without_safe_releases": safe_relief,
            "without_safe_releases_scope": "Only unused saved drafts removed; pending jobs, used/completed assessments and learner exposure retained.",
            "safely_releasable_assessment_ids": safe_ids,
            "safe_release_relief": _ids({v: rows[v] for sid in safe_without for v in set(safe_without[sid]) - set(candidates[sid])}),
            "safe_release_capacity_improvement": improvement(safe_relief["capacity"]),
            "reservation_capacity_improvement": improvement(b),
            "notes": ["Exclusion reason sets overlap; counts are not additive.",
                      "Available counts are marginal distinct families; joint conflicts are analyzed separately.",
                      "Attempts are exposure; unreleased saved assessments of every status reserve for their learner or all learners when unowned.",
                      "Assignments witness disjoint complete tests by splitting each slot allocation into its repeated demands.",
                      "Unknown metadata and pending review never imply availability."]}

    result['warnings'] = [{'reason': 'low_slot_variety', 'slot_id': s['slot_id'],
                           'eligible_questions': len(s['eligible']['version_ids']),
                           'message': 'Fewer than 3 eligible questions; seed has little or no effect.'}
                          for s in reports if len(s['eligible']['version_ids']) < 3]
    pool = {v for values in candidates.values() for v in values}
    result['question_constraints'] = [{'exercise_version_id': v, **c} for v, c in constraints.items()
                                      if v in pool and (c['depends_on'] or c['gives_away'] or c.get('stale'))]
    for v, c in constraints.items():
        for link in c['gives_away']:
            if v in pool and link['exercise_version_id'] in pool:
                result['warnings'].append({'reason': 'answer_disclosure', 'exercise_version_id': v,
                                           'target': link, 'message': 'These questions cannot appear in the same exam.'})
    distinct = normal['distinct_exams']
    result['selection_variation'] = {
        'status': ('multiple_selections_available' if distinct['lower_bound'] > 1 else
                   'forced_selection' if distinct['exact'] and distinct['count'] == 1 else
                   'infeasible' if distinct['exact'] and distinct['count'] == 0 else 'unknown'),
        'count_is_exact': distinct['exact'],
        'note': 'Selection identity excludes order and option permutations. Different seeds are not guaranteed to choose different selections. Marginal second-paper deficits do not establish joint capacity.'}
    joint = normal["joint"]
    result["gaps"] = [] if joint["status"] == "feasible" else [
        {"slot_id": s["slot_id"], "section": s["section"], "topic_ids": s["topic_ids"],
         "question_type": s["question_type"], "needed": s["needed"], "eligible": s["available"],
         "shortfall": s["shortfall"],
         "exclusion_reasons": {k: v["count"] for k, v in s["exclusions"].items()},
         "joint_reason": "search_budget_exhausted" if joint["status"] == "unknown" else "joint_conflict_or_shared_pool",
         "joint_shortfall_lower_bound": joint["needed"] - joint["matched_upper_bound"],
         "joint_shortfall_upper_bound": joint["needed"] - joint["matched_lower_bound"]}
        for s in reports]
    if internal:
        return result, slots, candidates, rows, conflicts
    return result
