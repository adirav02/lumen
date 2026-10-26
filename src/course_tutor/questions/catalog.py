"""Conservative extraction, immutable source occurrences and indexed similarity candidates.

Text matching proposes relationships, never mathematical equivalence. No external
model calls are made, and the candidate search is bounded rather than all-pairs.
"""

import hashlib
import json
import re
import unicodedata
import uuid
from collections import Counter

from ..errors import CourseNotFoundError, CrossCourseViolationError, StaleRevisionError, ValidationError
from ..models import Exercise, ExerciseVersion, utc_now_iso
from ..storage.repositories import CourseRepository, ExerciseRepository, SourceRepository


HEADER = re.compile(r"(?mi)^[ \t]*(?:question|problem|שאלה)[ \t]+([0-9]+|[א-ת])(?:[ \t]*[.):\-])?[ \t]*")
NUMBERED = re.compile(r"(?m)^[ \t]*([0-9]{1,3})[.)][ \t]+")
TOKEN = re.compile(r"\w+|[^\w\s]", re.UNICODE)


def require_text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} must be a non-empty string.")
    return value


def page_size(limit):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValidationError("limit must be an integer between 1 and 100.")
    return limit


def validate_subparts(value):
    if not isinstance(value, list):
        raise ValidationError("subparts must be a list.")
    keys = []
    for part in value:
        if isinstance(part, str):
            key = part
        elif isinstance(part, dict):
            key = part.get("subpart_key") or part.get("key") or part.get("id")
            if "required" in part and type(part["required"]) is not bool:
                raise ValidationError("subpart required must be a boolean.")
        else:
            raise ValidationError("Each subpart requires a string key or object.")
        require_text(key, "subpart key")
        keys.append(key.strip())
    if len(keys) != len(set(keys)):
        raise ValidationError("Subpart keys must be distinct.")


def normalized(text):
    # Indentation/line breaks can be meaningful in code and mathematical layouts.
    # Treat reflowed text as a reviewable similarity, not a proven exact copy.
    return unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n").strip("\n")


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def index_question(con, version_id, course_id, text):
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='question_fingerprints'").fetchone():
        return  # Legacy migration fixtures are indexed when migration 9 runs.
    exact = digest(normalized(text))
    structure = digest(re.sub(r"\d+(?:\.\d+)?", "#", normalized(text)))
    con.execute("INSERT OR REPLACE INTO question_fingerprints VALUES (?, ?, ?, ?)", (version_id, course_id, exact, structure))
    rowid = con.execute("SELECT rowid FROM exercise_versions WHERE id=?", (version_id,)).fetchone()[0]
    con.execute("DELETE FROM question_search WHERE rowid = ?", (rowid,))
    con.execute("INSERT INTO question_search(rowid,exercise_version_id,course_id,question_text) VALUES (?, ?, ?, ?)", (rowid, version_id, course_id, text))
    # Exact/number-variant detection uses hash indexes. Long duplicate groups are
    # represented by a bounded set of edges; practice also consults hash groups.
    candidates = {r["exercise_version_id"]: r for r in con.execute(
        """SELECT f.*, v.question_text FROM question_fingerprints f JOIN exercise_versions v ON v.id=f.exercise_version_id
           WHERE f.course_id=? AND f.exercise_version_id!=? AND (f.exact_hash=? OR f.structure_hash=?)
           ORDER BY f.exercise_version_id LIMIT 100""", (course_id, version_id, exact, structure))}
    words = list(dict.fromkeys(re.findall(r"\w{3,}", text)))[:16]
    if words:
        query = " OR ".join('"' + word + '"' for word in words)
        for row in con.execute(
            """SELECT f.*, s.question_text FROM question_search s JOIN question_fingerprints f
               ON f.exercise_version_id=s.exercise_version_id
               WHERE question_search MATCH ? AND f.course_id=? AND f.exercise_version_id!=?
               ORDER BY rank LIMIT 40""", (query, course_id, version_id)):
            candidates.setdefault(row["exercise_version_id"], row)
    tokens = Counter(TOKEN.findall(normalized(text)))
    for other, row in candidates.items():
        other_tokens = Counter(TOKEN.findall(normalized(row["question_text"])))
        union = sum((tokens | other_tokens).values())
        similarity = sum((tokens & other_tokens).values()) / union if union else 0.0
        if row["exact_hash"] == exact:
            kind, method, status, similarity = "exact", "normalized_text", "confirmed", 1.0
        elif row["structure_hash"] == structure:
            kind, method, status = "similar", "numeric_template", "pending_review"
        elif len(tokens) >= 8 and similarity >= 0.8:
            kind, method, status = "similar", "token_overlap", "pending_review"
        else:
            continue
        left, right = sorted((version_id, other))
        hashes = {version_id: exact, other: row["exact_hash"]}
        con.execute(
            """INSERT OR IGNORE INTO question_relations
               (id,course_id,left_version_id,right_version_id,left_hash,right_hash,kind,method,similarity,status,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (str(uuid.uuid4()), course_id, left, right, hashes[left], hashes[right], kind, method, similarity, status, utc_now_iso()))


def current_relations_sql():
    """A rejected or obsolete text match cannot affect current practice selection."""
    return """SELECT r.* FROM question_relations r
              JOIN question_fingerprints l ON l.exercise_version_id=r.left_version_id AND l.exact_hash=r.left_hash
              JOIN question_fingerprints z ON z.exercise_version_id=r.right_version_id AND z.exact_hash=r.right_hash"""


class QuestionCatalog:
    def __init__(self, con):
        self.con = con
        self.sources = SourceRepository(con)
        self.exercises = ExerciseRepository(con)

    def source(self, course_id, version_id):
        row = self.con.execute("SELECT v.*, s.logical_name FROM source_versions v JOIN sources s ON s.id=v.source_id WHERE v.id=?", (version_id,)).fetchone()
        if not row:
            raise ValidationError("Source version not found.")
        if row["course_id"] != course_id:
            raise CrossCourseViolationError("SourceVersion", version_id, course_id, row["course_id"])
        return row

    def catalog(self, course_id, source_version_id, questions=None, exam_label=None):
        automatic = questions is None
        src = self.source(course_id, source_version_id)
        sections = self.sources.list_source_sections(source_version_id)
        by_index = {s.section_index: s for s in sections}
        existing = self.con.execute("SELECT * FROM exam_catalogs WHERE source_version_id=?", (source_version_id,)).fetchone()
        aliases_available = self.con.execute("SELECT 1 FROM sqlite_master WHERE name='exam_catalog_aliases'").fetchone()
        if aliases_available and not existing:
            duplicate = self.con.execute("""SELECT c.source_version_id FROM exam_catalogs c JOIN source_versions s ON s.id=c.source_version_id
                JOIN source_processing old ON old.source_version_id=s.id AND old.reuse_eligible=1
                JOIN source_processing new ON new.source_version_id=? AND new.reuse_eligible=1
                    AND new.processing_fingerprint=old.processing_fingerprint
                WHERE c.course_id=? AND s.file_hash=? ORDER BY c.created_at,c.source_version_id LIMIT 1""", (source_version_id, course_id, src['file_hash'])).fetchone()
            if duplicate:
                self.con.execute('INSERT OR IGNORE INTO exam_catalog_aliases VALUES (?,?)', (source_version_id, duplicate[0]))
                return self.exam_status(course_id, source_version_id)
        if existing and questions is None:
            from .constraints import apply_known
            apply_known(self.con, course_id)
            return self.exam_status(course_id, source_version_id)
        if exam_label is not None:
            require_text(exam_label, "exam_label")
        if not existing:
            self.con.execute("INSERT INTO exam_catalogs (source_version_id,course_id,exam_label,created_at) VALUES (?,?,?,?)",
                             (source_version_id, course_id, exam_label or src["logical_name"], utc_now_iso()))
        if questions is None:
            # Join pages to retain continuation text and precise source offsets.
            text, positions = "", []
            for sec in sections:
                start = len(text)
                text += sec.text
                positions.append((start, len(text), sec))
                text += "\n\n"
            matches = list(HEADER.finditer(text))
            numeric = not matches
            matches = matches or list(NUMBERED.finditer(text))
            questions = []
            keys = Counter()
            for i, match in enumerate(matches):
                start, end = match.end(), matches[i + 1].start() if i + 1 < len(matches) else len(text)
                key = match.group(1)
                keys[key] += 1
                flags = ["automatic_boundary_requires_review"]
                if numeric:
                    flags.append("ambiguous_numbered_boundary")
                if keys[key] > 1:
                    flags.append("repeated_question_label")
                spans = []
                for left, right, sec in positions:
                    if left < end and right > start:
                        spans.append({"section_index": sec.section_index, "start_offset": max(start, left) - left,
                                      "end_offset": min(end, right) - left})
                body = text[start:end].strip()
                if body:
                    questions.append({"question_key": key if keys[key] == 1 else f"{key}#{keys[key]}",
                                      "question_text": body, "source_spans": spans, "quality_flags": flags})
        if not isinstance(questions, list) or (not automatic and len(questions) > 500):
            raise ValidationError("questions must be a list of at most 500 items per batch.")
        added = 0
        for question in questions:
            if not isinstance(question, dict):
                raise ValidationError("Each question must be an object.")
            key = require_text(question.get("question_key"), "question_key")
            text = require_text(question.get("question_text"), "question_text")
            validate_subparts(question.get("subparts", []))
            for name in ("topic_mappings", "skill_mappings"):
                refs = question.get(name, [])
                if not isinstance(refs, list) or any(not isinstance(ref, str) or not ref.strip() for ref in refs):
                    raise ValidationError(f"{name} must be a list of non-empty strings.")
            if not isinstance(question.get("rubric", {}), dict) or not isinstance(question.get("reference_solution", ""), str):
                raise ValidationError("rubric must be an object and reference_solution must be text.")
            spans = question.get("source_spans")
            if not isinstance(spans, list) or not spans:
                raise ValidationError("Every question requires source_spans.")
            flags = question.get("quality_flags", ["host_transcription_requires_review"])
            if not isinstance(flags, list) or any(not isinstance(f, str) for f in flags):
                raise ValidationError("quality_flags must be a list of strings.")
            flags = list(flags)
            checked_spans = []
            for span in spans:
                if not isinstance(span, dict) or type(span.get("section_index")) is not int or span["section_index"] not in by_index:
                    raise ValidationError("source_spans must reference an existing source section_index.")
                sec = by_index[span["section_index"]]
                start, end = span.get("start_offset", 0), span.get("end_offset", len(sec.text))
                if type(start) is not int or type(end) is not int or not 0 <= start <= end <= len(sec.text):
                    raise ValidationError("Invalid source text offsets.")
                checked_spans.append({"section_id": sec.id, "section_index": sec.section_index, "label": sec.label,
                                      "start_offset": start, "end_offset": end, "locator": sec.metadata})
                if sec.quality_flag not in ("clean", "good", "extracted", "ok"):
                    flags.append(sec.quality_flag)
            old = self.con.execute("SELECT * FROM question_occurrences WHERE source_version_id=? AND question_key=?", (source_version_id, key)).fetchone()
            if old:
                if old["extracted_text"] != text or json.loads(old["source_spans_json"]) != checked_spans:
                    raise ValidationError(f"Question key '{key}' already exists with different content. Use exercise revision/correction operations.")
                continue
            ex_id, ver_id, now = str(uuid.uuid4()), str(uuid.uuid4()), utc_now_iso()
            self.exercises.create_exercise(Exercise(id=ex_id, course_id=course_id,
                exercise_family="exam-question:" + digest(normalized(text)), external_ref=f"{source_version_id}#{key}"))
            self.exercises.create_exercise_version(ExerciseVersion(id=ver_id, exercise_id=ex_id, course_id=course_id,
                version_num=1, question_text=text, validation_state="pending_review",
                subparts=question.get("subparts", []), topic_mappings=question.get("topic_mappings", []),
                skill_mappings=question.get("skill_mappings", []), reference_solution=question.get("reference_solution", ""),
                rubric=question.get("rubric", {})))
            self.con.execute("""INSERT INTO question_occurrences
                (id,course_id,source_version_id,exercise_version_id,question_key,extracted_text,source_spans_json,quality_flags_json,created_at)
                VALUES (?,?,?,?,?,?,?,?,?)""", (str(uuid.uuid4()), course_id, source_version_id, ver_id, key, text,
                json.dumps(checked_spans, ensure_ascii=False), json.dumps(sorted(set(flags))), now))
            if 'visual_review_status' in {r[1] for r in self.con.execute('PRAGMA table_info(question_occurrences)')} and src['mime_type'].startswith('text/'):
                self.con.execute("UPDATE question_occurrences SET visual_review_status='not_required' WHERE exercise_version_id=?", (ver_id,))
            from .provenance import filename_provenance
            provenance = filename_provenance(src['original_filename'])
            if provenance:
                self.con.execute('UPDATE question_occurrences SET metadata_json=? WHERE exercise_version_id=?',
                                 (json.dumps(provenance), ver_id))
            added += 1
        from .constraints import apply_known
        apply_known(self.con, course_id)
        if added:
            self.con.execute("UPDATE exam_catalogs SET status='pending_review',revision=revision+1 WHERE source_version_id=?", (source_version_id,))
        return self.exam_status(course_id, source_version_id)

    def exam_status(self, course_id, source_version_id):
        src = self.source(course_id, source_version_id)
        if self.con.execute("SELECT 1 FROM sqlite_master WHERE name='exam_catalog_aliases'").fetchone():
            alias = self.con.execute('SELECT canonical_source_version_id FROM exam_catalog_aliases WHERE source_version_id=?', (source_version_id,)).fetchone()
            if alias:
                return {**self.exam_status(course_id, alias[0]), 'upload_alias_source_version_id': source_version_id,
                        'canonical_source_version_id': alias[0], 'duplicate_upload': True}
        catalog = self.con.execute("SELECT * FROM exam_catalogs WHERE source_version_id=?", (source_version_id,)).fetchone()
        if not catalog:
            raise ValidationError("This source version has not been cataloged.")
        result = dict(catalog)
        result["review_history"] = json.loads(result.pop("review_history_json"))
        if 'metadata_json' in result:
            result['metadata'] = json.loads(result.pop('metadata_json'))
        result["question_counts"] = {r["review_status"]: r["n"] for r in self.con.execute(
            "SELECT review_status,COUNT(*) n FROM question_occurrences WHERE source_version_id=? GROUP BY review_status", (source_version_id,))}
        result["source"] = {k: src[k] for k in ("source_id", "version_num", "file_hash", "extraction_status", "extraction_notes")}
        result["coverage_verified"] = catalog["status"] == "reviewed"
        return result

    def review_question(self, course_id, occurrence_id, expected_revision, status, notes):
        require_text(notes, "notes")
        if status not in ("accepted", "rejected", "pending_review"):
            raise ValidationError("Invalid question review status.")
        row = self.con.execute("SELECT * FROM question_occurrences WHERE id=?", (occurrence_id,)).fetchone()
        if not row or row["course_id"] != course_id:
            raise ValidationError("Question occurrence not found in this course.")
        self.check_revision(row, expected_revision, occurrence_id)
        if status != "accepted":
            version = self.exercises.get_exercise_version(row["exercise_version_id"])
            self.exercises.validate_exercise_version(version.id, status="pending_review",
                expected_revision=len(version.revision_history) + 1, notes="Source question extraction requires review.")
        history = json.loads(row["review_history_json"]) + [{"status": status, "notes": notes, "at": utc_now_iso()}]
        self.con.execute("UPDATE question_occurrences SET review_status=?,revision=revision+1,review_history_json=? WHERE id=?", (status, json.dumps(history), occurrence_id))
        self.con.execute("UPDATE exam_catalogs SET status='pending_review',revision=revision+1 WHERE source_version_id=?", (row["source_version_id"],))
        refresh_review_dependents(self.con, row['exercise_version_id'])
        return {"occurrence_id": occurrence_id, "review_status": status, "revision": row["revision"] + 1}

    @staticmethod
    def check_revision(row, expected, identity):
        if type(expected) is not int or expected < 1:
            raise ValidationError("expected_revision must be a positive integer.")
        if expected != row["revision"]:
            raise StaleRevisionError("QuestionCatalog", identity, expected, row["revision"])

    def review_exam(self, course_id, source_version_id, expected_revision, expected_question_count, notes, checks):
        require_text(notes, "notes")
        status = self.exam_status(course_id, source_version_id)
        self.check_revision(status, expected_revision, source_version_id)
        if type(expected_question_count) is not int or expected_question_count < 0:
            raise ValidationError("expected_question_count must be a non-negative integer.")
        if not isinstance(checks, dict) or set(checks) != {"all_pages_reviewed", "question_count_verified"} or any(value is not True for value in checks.values()):
            raise ValidationError("Explicit all_pages_reviewed and question_count_verified checks are required.")
        counts = status["question_counts"]
        if counts.get("pending_review", 0) or counts.get("accepted", 0) != expected_question_count:
            raise ValidationError("Resolve all candidates and verify the accepted question count before marking coverage reviewed.")
        history = status["review_history"] + [{"notes": notes, "checks": checks, "expected_question_count": expected_question_count, "at": utc_now_iso()}]
        self.con.execute("UPDATE exam_catalogs SET status='reviewed',revision=revision+1,review_history_json=? WHERE source_version_id=?", (json.dumps(history), source_version_id))
        return self.exam_status(course_id, source_version_id)

    def list_questions(self, course_id, source_version_id=None, limit=50, after_id=""):
        page_size(limit)
        if not isinstance(after_id, str):
            raise ValidationError("after_id must be a string.")
        if not CourseRepository(self.con).get_course(course_id):
            raise CourseNotFoundError(course_id)
        if source_version_id:
            self.source(course_id, source_version_id)
            alias = self.con.execute('SELECT canonical_source_version_id FROM exam_catalog_aliases WHERE source_version_id=?', (source_version_id,)).fetchone()
            if alias:
                source_version_id = alias[0]
        rows = self.con.execute("""SELECT q.*,v.question_text,v.validation_state,c.exam_label,s.source_id,s.version_num,s.file_hash
            FROM question_occurrences q JOIN exercise_versions v ON v.id=q.exercise_version_id
            JOIN exam_catalogs c ON c.source_version_id=q.source_version_id
            JOIN source_versions s ON s.id=q.source_version_id
            WHERE q.course_id=? AND (? IS NULL OR q.source_version_id=?) AND q.id>?
            ORDER BY q.id LIMIT ?""", (course_id, source_version_id, source_version_id, after_id, limit + 1)).fetchall()
        items = []
        for row in rows[:limit]:
            item = dict(row)
            for name in ("source_spans", "quality_flags", "review_history"):
                item[name] = json.loads(item.pop(name + "_json"))
            for name in ('metadata', 'solution_links', 'visual_review_history'):
                if name + '_json' in item:
                    item[name] = json.loads(item.pop(name + '_json'))
            item['verification'] = {'extraction': item['review_status'], 'visual': item.get('visual_review_status','pending_review'),
                                    'mathematical': item['validation_state']}
            items.append(item)
        return {"questions": items, "next_after_id": items[-1]["id"] if len(rows) > limit else None}

    def list_relations(self, course_id, version_id=None, limit=50, after_id=""):
        page_size(limit)
        if not isinstance(after_id, str):
            raise ValidationError("after_id must be a string.")
        if not CourseRepository(self.con).get_course(course_id):
            raise CourseNotFoundError(course_id)
        rows = self.con.execute(current_relations_sql() + """ WHERE r.course_id=? AND r.id>?
            AND (? IS NULL OR r.left_version_id=? OR r.right_version_id=?) ORDER BY r.id LIMIT ?""",
            (course_id, after_id, version_id, version_id, version_id, limit + 1)).fetchall()
        items = [dict(row) for row in rows[:limit]]
        for item in items:
            item["review_history"] = json.loads(item.pop("review_history_json"))
        return {"relations": items, "next_after_id": items[-1]["id"] if len(rows) > limit else None,
                "limitations": "Indexed text/numeric-template candidates; semantic equivalence requires review. Not all paraphrases are detectable."}

    def search_questions(self, course_id, query, limit=20):
        page_size(limit)
        require_text(query, 'query')
        if not CourseRepository(self.con).get_course(course_id):
            raise CourseNotFoundError(course_id)
        terms = re.findall(r'\w+', query)[:20]
        if not terms:
            return {'questions': [], 'query': query}
        match = ' AND '.join('"' + term + '"' for term in terms)
        rows = self.con.execute("""SELECT s.exercise_version_id,snippet(question_search,2,'[',']','…',40) excerpt,
            q.id occurrence_id,q.source_version_id,q.question_key,q.review_status,q.visual_review_status,q.metadata_json,v.validation_state
            FROM question_search s JOIN exercise_versions v ON v.id=s.exercise_version_id
            LEFT JOIN question_occurrences q ON q.exercise_version_id=v.id
            WHERE question_search MATCH ? AND v.course_id=? ORDER BY rank,v.id LIMIT ?""", (match, course_id, limit)).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item['metadata'] = json.loads(item.pop('metadata_json') or '{}')
            results.append(item)
        return {'questions': results, 'query': query, 'limit': limit, 'notes': 'Raw search hits do not establish review or correctness.'}

    def lexical_overlap(self, course_id, exercise_version_id, threshold=0.45, limit=20):
        page_size(limit)
        if type(threshold) not in (int, float) or not 0 < threshold <= 1:
            raise ValidationError('threshold must be a finite number in (0,1].')
        version = self.exercises.get_exercise_version(exercise_version_id)
        if not version or version.course_id != course_id:
            raise ValidationError('Question not found in this course.')
        def tokens(text):
            return set(re.findall(r'\w+', unicodedata.normalize('NFKC', text).casefold()))
        left = tokens(version.question_text)
        candidates = []
        # Cheap tutor-only advisory over this course, including uncataloged exercises.
        for row in self.con.execute('SELECT id,question_text FROM exercise_versions WHERE course_id=? AND id!=? ORDER BY id',
                                    (course_id, exercise_version_id)):
            right = tokens(row['question_text'])
            score = len(left & right)/len(left | right) if left | right else 0
            if score >= threshold:
                candidates.append({'exercise_version_id': row['id'], 'lexical_jaccard': score,
                                   'status': 'advisory_tutor_review'})
        candidates.sort(key=lambda r: (-r['lexical_jaccard'], r['exercise_version_id']))
        return {'candidates': candidates[:limit], 'threshold': threshold,
                'scope': 'Normalized token Jaccard over current course questions; advisory only.',
                'notes': 'No candidates found does not prove novelty or semantic independence.'}

    def review_relation(self, course_id, relation_id, expected_revision, status, notes):
        require_text(notes, "notes")
        if status not in ("confirmed", "rejected", "pending_review"):
            raise ValidationError("Invalid relation status.")
        row = self.con.execute(current_relations_sql() + " WHERE r.id=? AND r.course_id=?", (relation_id, course_id)).fetchone()
        if not row:
            raise ValidationError("Current question relation not found in this course.")
        self.check_revision(row, expected_revision, relation_id)
        history = json.loads(row["review_history_json"]) + [{"status": status, "notes": notes, "at": utc_now_iso()}]
        self.con.execute("UPDATE question_relations SET status=?,revision=revision+1,review_history_json=? WHERE id=?", (status, json.dumps(history), relation_id))
        return {"relation_id": relation_id, "status": status, "revision": row["revision"] + 1}


def invalidate_source_review(con, version_id):
    """A changed transcription must be compared with its immutable source again."""
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='question_occurrences'").fetchone():
        return
    row = con.execute("SELECT * FROM question_occurrences WHERE exercise_version_id=?", (version_id,)).fetchone()
    if row:
        history = json.loads(row["review_history_json"]) + [{"status": "pending_review", "notes": "Question text changed; compare with original source again", "at": utc_now_iso()}]
        con.execute("UPDATE question_occurrences SET review_status='pending_review',revision=revision+1,review_history_json=? WHERE id=?", (json.dumps(history), row["id"]))
        if 'visual_review_status' in row.keys():
            con.execute("UPDATE question_occurrences SET visual_review_status=CASE WHEN visual_review_status='not_required' THEN 'not_required' ELSE 'pending_review' END WHERE id=?", (row['id'],))
        con.execute("UPDATE exam_catalogs SET status='pending_review',revision=revision+1 WHERE source_version_id=?", (row["source_version_id"],))


def refresh_review_dependents(con, version_id, *, rebuild_topics=True):
    """Withdraw confirmed diagnostic scores and rebuild projections after review changes.

    Historical evidence and scores remain available. Restoring a review does not
    silently restore a previously withdrawn numeric score.
    """
    from ..storage.repositories import AssessmentRepository, EvidenceRepository
    row = con.execute('SELECT * FROM question_occurrences WHERE exercise_version_id=?', (version_id,)).fetchone()
    if not row:
        return
    ready = row['review_status'] == 'accepted' and (
        'visual_review_status' not in row.keys() or row['visual_review_status'] in ('verified', 'not_required'))
    if not ready:
        repository = AssessmentRepository(con)
        for item in repository.get_items_by_exercise_version(version_id):
            if item.points_awarded is not None:
                entry = {'action': 'invalidated_by_source_review', 'previous_points': item.points_awarded,
                         'previous_score_status': item.score_status, 'reason': 'Source extraction or visual review is pending.',
                         'recorded_at': utc_now_iso()}
                repository.update_item_progress(item.id, points_awarded=None, score_status='pending_review',
                                                score_history=list(item.score_history) + [entry])
                con.execute("UPDATE assessments SET status='open',updated_at=? WHERE id=?", (utc_now_iso(), item.assessment_id))
    if rebuild_topics:
        evidence = EvidenceRepository(con)
        for topic in con.execute('SELECT DISTINCT course_id,topic_id FROM evidence WHERE exercise_version_id=?', (version_id,)).fetchall():
            evidence.recompute_topic_state(topic['course_id'], topic['topic_id'])
