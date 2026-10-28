"""Private, read-only seeded exam preparation; publication is coordinated separately.

Priority uses an exponential race: -log(U) / weight, with a stable-ID seeded
stream. weight = 1 + weakness + novelty. Unknown topics have weakness=novelty=0;
evaluated topics use weakness=1-mean(score), novelty=1/(1+representative count).
One representative per topic/family/skill/subpart uses the latest eligible submission
by persisted creation time, submission ID, then evidence ID (policy v2).
Scores: independent=1, assisted=.75, partial=.5, incorrect=0. These are selection
heuristics, not reported mastery. Bounded DFS proves a full conflict-free witness;
it makes no global optimality claim. Option boundaries are never inferred.
"""

import copy
import json
from ..questions.assets import snapshot_assets
import math
import random
import uuid
from collections import defaultdict

from ..errors import ValidationError
from ..models import compute_exercise_version_hash
from ..questions.history import QuestionHistory
from ..storage.repositories import EvidenceRepository, ExerciseRepository
from . import readiness


def _gaps(report, reason=None):
    """Public shortage details deliberately exclude candidate content/weights."""
    if reason is None:
        return copy.deepcopy(report['gaps'])
    return [{'slot_id': s['slot_id'], 'section': s['section'],
             'topic_ids': s['topic_ids'], 'question_type': s['question_type'],
             'needed': s['needed'], 'eligible': s['available'], 'shortfall': s['shortfall'],
             'exclusion_reasons': {k: v['count'] for k, v in s['exclusions'].items()},
             'joint_reason': reason} for s in report['slots']]


def _weights(con, course_id, learner_id, rows):
    history, evidence, exercises = QuestionHistory(con), EvidenceRepository(con), ExerciseRepository(con)
    topics, identities, versions = defaultdict(list), defaultdict(list), {}
    representatives = {}
    # Never inherit correctness across a newer unevaluated work submission.
    # Keep all candidates until eligibility checks: an ineligible tie winner must
    # not hide valid evidence, and topic is part of the representative identity.
    query = '''SELECT e.id,s.created_at,s.id AS submission_id,x.exercise_family
        FROM evidence e JOIN attempts a ON a.id=e.attempt_id
        JOIN attempt_events s ON s.id=e.event_id
        JOIN exercise_versions v ON v.id=e.exercise_version_id
        JOIN exercises x ON x.id=v.exercise_id
        WHERE e.course_id=? AND a.learner_id=? AND e.status='active'
        AND NOT EXISTS (SELECT 1 FROM attempt_events newer WHERE newer.attempt_id=e.attempt_id
            AND newer.event_type='work_submission' AND newer.event_index>s.event_index
            AND (newer.subpart_key IS NULL OR newer.subpart_key IN ('','default')
                 OR e.subpart_key IN ('','default') OR newer.subpart_key=e.subpart_key))'''
    scores = {'independent_mastery': 1., 'assisted_success': .75, 'partial_progress': .5, 'incorrect': 0.}
    for record in con.execute(query, (course_id, learner_id)).fetchall():
        ev = evidence.get_evidence(record['id'])
        if ev.exercise_version_id not in versions:
            versions[ev.exercise_version_id] = exercises.get_exercise_version(ev.exercise_version_id)
        version = versions[ev.exercise_version_id]
        if (version and version.validation_state == 'validated' and ev.demonstrated_level in scores
                and history.eligible(version, ev, learner_id)):
            unit = (ev.topic_id, record['exercise_family'], ev.skill_id, ev.subpart_key)
            chronology = (record['created_at'], record['submission_id'], ev.id)
            if unit not in representatives or chronology > representatives[unit][0]:
                representatives[unit] = (chronology, ev)
    for _, ev in representatives.values():
        topics[ev.topic_id].append(scores[ev.demonstrated_level])
        identities[ev.topic_id].append(ev.id)
    result = {}
    for vid, row in sorted(rows.items()):
        known = [t for t in sorted(row['topics']) if topics[t]]
        weakness = sum(1 - sum(topics[t]) / len(topics[t]) for t in known) / len(known) if known else 0.
        novelty = sum(1 / (1 + len(topics[t])) for t in known) / len(known) if known else 0.
        result[vid] = {'weight': 1 + weakness + novelty, 'weakness': weakness, 'novelty': novelty,
                       'topic_ids': sorted(row['topics']),
                       'evidence_ids': sorted({e for t in known for e in identities[t]}),
                       'reason': 'eligible_topic_evidence' if known else 'unknown_topics_neutral'}
    return result


def _allocate(slots, candidates, rows, conflicts, weights, seed, constraints):
    rng = random.Random(seed)
    priority = {v: -math.log(max(rng.random(), 1e-300)) / weights[v]['weight']
                for v in sorted({v for values in candidates.values() for v in values})}
    ordered = {s: sorted(vs, key=lambda v: (priority[v], v)) for s, vs in candidates.items()}
    rank = {s: {v: i for i, v in enumerate(vs)} for s, vs in ordered.items()}
    units = [s['id'] for s in sorted(slots, key=lambda s: (len(candidates[s['id']]), s['id']))
             for _ in range(s['count'])]
    budget = [readiness.SEARCH_NODE_BUDGET]

    def visit(index, picked, families, assignment, last):
        if index == len(units):
            from ..questions.constraints import ordered_selection
            return assignment if ordered_selection([v for _, v in assignment], constraints) is not None else None
        if budget[0] <= 0:
            return None
        budget[0] -= 1
        sid = units[index]
        for vid in ordered[sid]:
            family = rows[vid]['exercise_family']
            if rank[sid][vid] <= last.get(sid, -1) or family in families or conflicts[vid] & picked:
                continue
            result = visit(index + 1, picked | {vid}, families | {family},
                           assignment + [(sid, vid)], {**last, sid: rank[sid][vid]})
            if result is not None:
                return result
        return None
    return visit(0, set(), set(), [], {}), priority


def prepare_exam(con, course_id, learner_id, blueprint, seed, *, live_request_ids=None,
                 exclude_request_id=None, file_store=None):
    """Return private snapshots only after full readiness; never write DB/files.

    live_request_ids must come from the publication coordinator's lock checks.
    None is conservative (all pending owners reserve); empty means none are live.
    Preserves caller transactions; otherwise owns one consistent read snapshot.
    """
    if type(seed) is not int:
        raise ValidationError('seed must be an integer.')
    own_transaction = not con.in_transaction
    if own_transaction:
        con.execute('BEGIN')
    try:
        report, slots, candidates, rows, conflicts = readiness._report(
            con, course_id, blueprint, learner_id, internal=True,
            live_request_ids=live_request_ids, exclude_request_id=exclude_request_id)
        if report['analysis']['joint']['status'] != 'feasible':
            raise ValidationError('Blueprint has no proven complete allocation.', {'gaps': _gaps(report)})
        pool = {v for values in candidates.values() for v in values}
        weights = _weights(con, course_id, learner_id, {v: rows[v] for v in pool})
        from ..questions.constraints import load, ordered_selection
        constraints = load(con, course_id)
        assignment, priorities = _allocate(slots, candidates, rows, conflicts, weights, seed, constraints)
        if assignment is None:
            raise ValidationError('Seeded allocation search budget exhausted.',
                                  {'gaps': _gaps(report, 'selection_search_budget_exhausted')})
        by_slot = defaultdict(list)
        for sid, vid in assignment:
            by_slot[sid].append(vid)
        # Preserve first-seen section order and original slot order within each section.
        sections = list(dict.fromkeys(s.get('section') for s in slots))
        paper_slots = [s for section in sections for s in slots if s.get('section') == section]
        items, exercises = [], ExerciseRepository(con)
        for slot in paper_slots:
            for vid in by_slot[slot['id']]:
                version = exercises.get_exercise_version(vid)
                source = con.execute('''SELECT q.*,sv.original_filename,sv.version_num,sv.file_hash
                    FROM question_occurrences q JOIN source_versions sv ON sv.id=q.source_version_id
                    WHERE q.exercise_version_id=? AND q.course_id=? ORDER BY q.id LIMIT 1''', (vid, course_id)).fetchone()
                provenance = dict(source) if source else None
                if provenance:
                    provenance['source_spans'] = json.loads(provenance.pop('source_spans_json'))
                    provenance['metadata'] = json.loads(provenance.pop('metadata_json'))
                presentation = copy.deepcopy(version.rubric.get('choice_presentation'))
                # Preserve checked structures exactly. Free-text questions have no
                # machine option boundaries and therefore an empty permutation.
                options = presentation if isinstance(presentation, list) else (
                    presentation.get('options', []) if isinstance(presentation, dict) else [])
                permutation = list(range(len(options))) if isinstance(options, list) else []
                digest = compute_exercise_version_hash(version.question_text, version.reference_solution,
                                                       version.rubric, version.subparts)
                items.append({'item_id': str(uuid.uuid4()), 'exercise_version_id': vid,
                    'item_order': len(items) + 1, 'slot_id': slot['id'],
                    'max_points': slot.get('max_points', 1),
                    'exercise_revision': len(version.revision_history) + 1,
                    'exercise_content_hash': digest,
                    'snapshot': {'student_assets': snapshot_assets(con, course_id, version.rubric, file_store),
                        'question_text': version.question_text, 'subparts': copy.deepcopy(version.subparts),
                        'rubric': copy.deepcopy(version.rubric), 'reference_solution': version.reference_solution,
                        'source_reference': provenance, 'provenance': provenance,
                        'section': slot.get('section'), 'question_type': slot.get('question_type'),
                        'choice_presentation': presentation, 'option_permutation': permutation,
                        'answer_mapping': copy.deepcopy(version.rubric.get('answer_mapping', {})),
                        'review_identity': {'validation_state': version.validation_state,
                            'exercise_revision': len(version.revision_history) + 1,
                            'exercise_content_hash': digest}}})
        order = ordered_selection([item['exercise_version_id'] for item in items], constraints)
        items.sort(key=lambda item: order.index(item['exercise_version_id']))
        for index, item in enumerate(items, 1):
            item['item_order'] = index
            item['snapshot']['question_constraints'] = constraints[item['exercise_version_id']]
        from .references import resolve
        presented = resolve([{**i['snapshot'], 'item_order': i['item_order'], 'exercise_version_id': i['exercise_version_id']} for i in items], constraints)
        for item, public in zip(items, presented):
            item['snapshot']['presentation'] = {k: public[k] for k in ('presentation_text', 'subparts')}
        from ..questions.constraints import paper_settings
        effective_blueprint = paper_settings(con, order, report['relaxation_policy']['effective_blueprint'])
        return {'items': items, 'readiness': report,
                'effective_blueprint': effective_blueprint,
                'relaxation_policy': report['relaxation_policy'],
                'selection_inputs': {'seed': seed, 'policy': 'strict_weighted_priority_v2',
                                     'weights': weights, 'priorities': priorities}}
    finally:
        if own_transaction:
            con.execute('ROLLBACK')


# Publication uses one persistent OS lock inode per request. Never unlink locks:
# doing so lets a later opener lock a different inode while an earlier holder runs.
import hashlib
import os
from pathlib import Path
import shutil
from contextlib import ExitStack

from ..errors import ConflictError
from ..storage.db import atomic_transaction
from ..storage.repositories import AssemblyRepository, ReceiptRepository, ReservationRepository
from .paper import assembly_paper
from .export import render_staged_paper, verify_staged_paper, publish_directory


def _lock_path(core, request_id):
    return core.workspace_root / '.assembly-locks' / hashlib.sha256(request_id.encode()).hexdigest()


def _lock(core, request_id, *, create=False):
    import fcntl
    path = _lock_path(core, request_id)
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | (os.O_CREAT if create else 0), 0o600)
    except FileNotFoundError:
        return None
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise ConflictError('Assembly is active; retry with the same request ID.') from None
    return fd


def _identity(job):
    return {key: job[key] for key in ('request_id', 'assessment_id', 'input_hash')}


def _owned(job, path, *, complete=False):
    path = Path(path)
    try:
        marker_path = path / '.assembly-owner.json'
        if path.is_symlink() or marker_path.is_symlink():
            return False
        marker = json.loads(marker_path.read_text())
        if any(marker.get(k) != v for k, v in _identity(job).items()):
            return False
        if complete:
            manifest = path / 'presentation.json'
            return (not manifest.is_symlink() and hashlib.sha256(manifest.read_bytes()).hexdigest()
                    == marker.get('manifest_sha256'))
        return True
    except (OSError, ValueError, TypeError):
        return False


def _cleanup(job):
    staging = Path(job['staging_path'])
    if _owned(job, staging):
        shutil.rmtree(staging)


def _receipt(repo, job):
    return {'assessment_id': job['assessment_id'], 'pdf_path': str(Path(job['final_path'])/'test.pdf'),
            'summary': f"{len(repo.items(job['request_id']))} questions; pending visual review"}


def _complete(core, repo, job):
    if not _owned(job, job['final_path'], complete=True):
        return False
    verify_staged_paper(assembly_paper(core.con, job), job['final_path'])
    return True


def _classify(core, repo, course_id, stack, exclude=None):
    """Read-only liveness checks, holding dead locks until decisions commit."""
    live, dead = set(), []
    for job in repo.pending(course_id):
        if job['request_id'] == exclude:
            continue
        try:
            fd = _lock(core, job['request_id'])
        except ConflictError:
            live.add(job['request_id'])
            continue
        if fd is not None:
            stack.callback(os.close, fd)
        # A complete renamed job will become a real assessment on recovery, so
        # reserve it during readiness even though its process has exited.
        try:
            complete = _complete(core, repo, job)
        except ValidationError:
            complete = False
        if complete:
            live.add(job['request_id'])
        dead.append((job, complete))
    return live, dead


def _validate_saved(core, repo, job, live):
    generation = job['generation']
    report, slots, candidates, rows, conflicts = readiness._report_once(
        core.con, job['course_id'], generation.get('effective_blueprint', generation['blueprint']),
        job['learner_id'], internal=True, live_request_ids=live,
        exclude_request_id=job['request_id'],
        required_provenance_slots=readiness._provenance_slots(generation['blueprint']))
    picked, families = set(), set()
    counts = defaultdict(int)
    for item in repo.items(job['request_id']):
        vid, sid = item['exercise_version_id'], item['slot_id']
        version = ExerciseRepository(core.con).get_exercise_version(vid)
        if (vid not in candidates.get(sid, set()) or not version
                or item['exercise_revision'] != len(version.revision_history) + 1
                or item['exercise_content_hash'] != compute_exercise_version_hash(
                    version.question_text, version.reference_solution, version.rubric, version.subparts)
                or rows[vid]['exercise_family'] in families or conflicts[vid] & picked):
            raise ValidationError('Saved selection is no longer eligible; use a new request ID.', {'gaps': _gaps(report)})
        picked.add(vid)
        families.add(rows[vid]['exercise_family'])
        counts[sid] += 1
    from ..questions.constraints import load, ordered_selection
    saved_order = [i['exercise_version_id'] for i in repo.items(job['request_id'])]
    if ordered_selection(saved_order, load(core.con, job['course_id'])) != saved_order:
        raise ValidationError('Saved selection has missing prerequisites, stale constraints or answer disclosures.')
    if any(counts[s['id']] != s['count'] for s in slots):
        raise ValidationError('Saved selection does not satisfy the blueprint.', {'gaps': _gaps(report)})


def _recover(core, repo, dead):
    # Caller holds each acquired job lock and the database write transaction.
    for old, complete in dead:
        job = repo.get(old['request_id'])
        if (ReservationRepository(core.con).get(job['assessment_id'])
                or job['state'] != 'pending' or job['owner_token'] != old['owner_token']):
            continue
        if complete:
            repo.finalize(job['request_id'], job['owner_token'], _receipt(repo, job))
        else:
            repo.fail(job['request_id'], job['owner_token'], 'stale_owner')
            _cleanup(job)


def _clean_orphans(core, repo, parent):
    if not parent.is_dir():
        return
    for path in parent.glob('.assembly-*'):
        if path.is_symlink() or not path.is_dir():
            continue
        try:
            marker = json.loads((path/'.assembly-owner.json').read_text())
            rid = marker['request_id']
            if not isinstance(rid, str) or repo.get(rid) is not None:
                continue
            fd = _lock(core, rid)  # Existing inode only; never create during classification.
            if fd is None:
                continue
            try:
                if (path.name == '.assembly-'+marker['assessment_id']
                        and _owned(marker, path)):
                    shutil.rmtree(path)
            finally:
                os.close(fd)
        except (OSError, ValueError, KeyError, TypeError, ConflictError):
            continue


def assemble_exam(core, course_id, learner_id, blueprint, seed, request_id, title=None):
    """Prepare, reserve, render and publish; success means finalized publication only."""
    core._verify_not_detached()
    if core.con.in_transaction:
        raise ValidationError('Assembly requires a connection without an active transaction.')
    for label, value in (('request_id', request_id), ('learner_id', learner_id), ('course_id', course_id)):
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(label+' must be a nonempty string.')
    if type(seed) is not int or not isinstance(blueprint, dict):
        raise ValidationError('Blueprint must be an object and seed an integer.')
    if title is not None and (not isinstance(title, str) or not title.strip()):
        raise ValidationError('title must be a nonempty string.')
    try:
        # Keep request identity stable for retries of saved v1 assemblies.
        # Actual selection policy is versioned in selection_inputs snapshots.
        canonical = json.dumps({'course_id': course_id, 'learner_id': learner_id,
            'blueprint': blueprint, 'seed': seed, 'title': title,
            'policy': 'strict_weighted_priority_v1'}, sort_keys=True, allow_nan=False)
    except (ValueError, TypeError):
        raise ValidationError('Assembly input must contain finite JSON values.') from None
    input_hash = hashlib.sha256(canonical.encode()).hexdigest()
    repo = AssemblyRepository(core.con)
    existing = repo.get(request_id, input_hash)
    if (existing and existing['state'] != 'published'
            and ReservationRepository(core.con).get(existing['assessment_id'])):
        raise ValidationError('Reservation has a terminal disposition; use a new request ID.')
    if existing and existing['state'] == 'published':
        return ReceiptRepository(core.con).check_idempotency(request_id, input_hash).response_data
    # Both initial readiness and dead-owner classification are strictly read-only.
    with ExitStack() as scan:
        live, _ = _classify(core, repo, course_id, scan, exclude=request_id)
        if existing:
            probe = _lock(core, request_id)
            if probe is not None:
                scan.callback(os.close, probe)
            if _complete(core, repo, existing):
                prepared = None
            else:
                _validate_saved(core, repo, existing, live)
                prepared = None
        else:
            prepared = prepare_exam(core.con, course_id, learner_id, blueprint, seed,
                                    live_request_ids=live, file_store=core.file_store)
    from ..course_layout import test_directory
    assessment_id = existing['assessment_id'] if existing else str(uuid.uuid4())
    final = Path(existing['final_path']) if existing else test_directory(
        core.con, core.workspace_root, course_id, assessment_id)
    staging = Path(existing['staging_path']) if existing else final.parent / ('.assembly-'+assessment_id)
    with ExitStack() as ownership:
        ownership.callback(os.close, _lock(core, request_id, create=True))
        with atomic_transaction(core.con), ExitStack() as scan:
            core._verify_not_detached()
            live, dead = _classify(core, repo, course_id, scan, exclude=request_id)
            job = repo.get(request_id, input_hash)
            if job and job['state'] == 'published':
                return ReceiptRepository(core.con).check_idempotency(request_id, input_hash).response_data
            if job and ReservationRepository(core.con).get(job['assessment_id']):
                raise ValidationError('Reservation has a terminal disposition; use a new request ID.')
            complete = job is not None and _complete(core, repo, job)
            if job and not complete:
                _validate_saved(core, repo, job, live)
            elif not job:
                prepared = prepare_exam(core.con, course_id, learner_id, blueprint, seed, live_request_ids=live, file_store=core.file_store)
            _recover(core, repo, dead)
            if job:
                job = repo.claim(request_id, input_hash, job['owner_token'], str(uuid.uuid4()))
            else:
                job = repo.create(request_id=request_id, input_hash=input_hash, assessment_id=assessment_id,
                    course_id=course_id, learner_id=learner_id, owner_token=str(uuid.uuid4()),
                    staging_path=str(staging), final_path=str(final), generation={
                        'blueprint': blueprint, 'seed': seed, 'title': title,
                        'selection_inputs': prepared['selection_inputs'],
                        'effective_blueprint': prepared['effective_blueprint'],
                        'relaxation_policy': prepared['relaxation_policy']}, items=prepared['items'])
        renamed = complete
        staging_created = False
        try:
            if not complete:
                _clean_orphans(core, repo, final.parent)
                _cleanup(job)
                final.parent.mkdir(parents=True, exist_ok=True)
                staging.mkdir()  # An unrecognized earlier directory is never overwritten.
                staging_created = True
                marker = _identity(job)
                (staging/'.assembly-owner.json').write_text(json.dumps(marker))
                render_staged_paper(assembly_paper(core.con, job), staging)
                marker['manifest_sha256'] = hashlib.sha256((staging/'presentation.json').read_bytes()).hexdigest()
                (staging/'.assembly-owner.json').write_text(json.dumps(marker))
                verify_staged_paper(assembly_paper(core.con, job), staging)
                publish_directory(staging, final)
                renamed = True
            with atomic_transaction(core.con):
                core._verify_not_detached()
                return repo.finalize(request_id, job['owner_token'], _receipt(repo, job))
        except Exception:
            # A rename wrapper may fail after the atomic filesystem side effect.
            # Leave its verified complete set pending so retry can finalize it.
            if not renamed:
                try:
                    renamed = _complete(core, repo, job)
                except (ValidationError, OSError):
                    renamed = False
            if not renamed:
                with atomic_transaction(core.con):
                    repo.fail(request_id, job['owner_token'])
                if staging_created and staging.is_dir() and not staging.is_symlink():
                    shutil.rmtree(staging)
                else:
                    _cleanup(job)
            # Rename-before-commit remains pending with its complete immutable set.
            raise


def export_saved_assessment(core, job, destination=None):
    """Re-export saved content, preserving all existing verified artifact bytes."""
    paper = assembly_paper(core.con, job)
    output = Path(destination).resolve() if destination is not None else Path(job['final_path'])
    if output.exists():
        return verify_staged_paper(paper, output)
    if core.con.in_transaction:
        raise ValidationError('Export requires a connection without an active transaction.')
    with ExitStack() as ownership:
        ownership.callback(os.close, _lock(core, job['request_id'], create=True))
        if output.exists():
            return verify_staged_paper(paper, output)
        output.parent.mkdir(parents=True, exist_ok=True)
        stage = output.parent / ('.assembly-'+job['assessment_id'])
        # Missing original publication may leave an owned partial re-export.
        temporary_job = dict(job, staging_path=str(stage))
        _cleanup(temporary_job)
        stage.mkdir()
        try:
            marker = _identity(job)
            (stage/'.assembly-owner.json').write_text(json.dumps(marker))
            render_staged_paper(paper, stage)
            marker['manifest_sha256'] = hashlib.sha256((stage/'presentation.json').read_bytes()).hexdigest()
            (stage/'.assembly-owner.json').write_text(json.dumps(marker))
            publish_directory(stage, output)
        except Exception:
            _cleanup(temporary_job)
            raise
    return verify_staged_paper(paper, output)
