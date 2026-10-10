"""Repositories for database entities with strict validation, revisions, and isolation."""

import hashlib
import json
import re
import sqlite3
from typing import Any, Dict, List, Optional, Union
import uuid

from ..errors import (
    CourseNotFoundError,
    CrossCourseViolationError,
    IdempotencyConflictError,
    SourceNotFoundError,
    StaleRevisionError,
    ValidationError,
)
from ..models import (
    Assessment,
    AssessmentItem,
    Attempt,
    AttemptEvent,
    Course,
    EVALUATED_DEMONSTRATED_LEVELS,
    EvidenceRecord,
    Exercise,
    ExerciseVersion,
    KnowledgeUnit,
    LearnerSettings,
    OBSERVATION_DEMONSTRATED_LEVELS,
    OperationReceipt,
    Source,
    SourceSection,
    SourceVersion,
    Topic,
    TopicAlias,
    TopicLink,
    TopicState,
    UnitProvenance,
    utc_now_iso,
    is_identity_resolved,
    validate_finite_number,
    validate_finite_metadata,
)
from ..learning.policy import check_evidence_eligibility_chain
from .db import atomic_transaction


class ReceiptRepository:
    def __init__(self, con: sqlite3.Connection):
        self.con = con

    def check_idempotency(self, request_id: str, canonical_hash: str) -> Optional[OperationReceipt]:
        """Check if request_id has already been executed.

        Returns prior receipt if hashes match, or raises IdempotencyConflictError if hashes differ.
        """
        row = self.con.execute(
            "SELECT request_id, course_id, canonical_request_hash, operation_name, affected_ids_json, response_json, created_at "
            "FROM operation_receipts WHERE request_id = ?",
            (request_id,),
        ).fetchone()

        if not row:
            return None

        existing_hash = row["canonical_request_hash"]
        if existing_hash != canonical_hash:
            raise IdempotencyConflictError(request_id, existing_hash, canonical_hash)

        return OperationReceipt(
            request_id=row["request_id"],
            course_id=row["course_id"],
            canonical_request_hash=row["canonical_request_hash"],
            operation_name=row["operation_name"],
            affected_ids=json.loads(row["affected_ids_json"]),
            response_data=json.loads(row["response_json"]),
            created_at=row["created_at"],
        )

    def record_receipt(self, receipt: OperationReceipt) -> None:
        self.con.execute(
            """
            INSERT INTO operation_receipts (
                request_id, course_id, canonical_request_hash, operation_name,
                affected_ids_json, response_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                receipt.request_id,
                receipt.course_id,
                receipt.canonical_request_hash,
                receipt.operation_name,
                json.dumps(receipt.affected_ids),
                json.dumps(receipt.response_data),
                receipt.created_at,
            ),
        )


class CourseRepository:
    def __init__(self, con: sqlite3.Connection):
        self.con = con

    def create_course(self, course: Course) -> Course:
        self.con.execute(
            """
            INSERT INTO courses (id, name, scope, default_language, notation_settings, revision, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                course.id,
                course.name,
                course.scope,
                course.default_language,
                json.dumps(course.notation_settings),
                course.revision,
                course.created_at,
                course.updated_at,
            ),
        )
        return course

    def get_course(self, course_id: str) -> Optional[Course]:
        row = self.con.execute(
            "SELECT id, name, scope, default_language, notation_settings, revision, created_at, updated_at FROM courses WHERE id = ?",
            (course_id,),
        ).fetchone()
        if not row:
            return None
        return Course(
            id=row["id"],
            name=row["name"],
            scope=row["scope"],
            default_language=row["default_language"],
            notation_settings=json.loads(row["notation_settings"]),
            revision=row["revision"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list_courses(self) -> List[Course]:
        rows = self.con.execute(
            "SELECT id, name, scope, default_language, notation_settings, revision, created_at, updated_at FROM courses ORDER BY name ASC"
        ).fetchall()
        return [
            Course(
                id=r["id"],
                name=r["name"],
                scope=r["scope"],
                default_language=r["default_language"],
                notation_settings=json.loads(r["notation_settings"]),
                revision=r["revision"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
            for r in rows
        ]

    def update_course(self, course: Course, expected_revision: int) -> Course:
        current = self.get_course(course.id)
        if not current:
            raise CourseNotFoundError(course.id)
        if current.revision != expected_revision:
            raise StaleRevisionError("Course", course.id, expected_revision, current.revision)

        new_revision = current.revision + 1
        now = utc_now_iso()
        self.con.execute(
            """
            UPDATE courses SET name = ?, scope = ?, default_language = ?, notation_settings = ?,
                              revision = ?, updated_at = ?
            WHERE id = ? AND revision = ?
            """,
            (
                course.name,
                course.scope,
                course.default_language,
                json.dumps(course.notation_settings),
                new_revision,
                now,
                course.id,
                expected_revision,
            ),
        )
        course.revision = new_revision
        course.updated_at = now
        return course

    def get_or_create_learner_settings(self, course_id: str, learner_id: str) -> LearnerSettings:
        row = self.con.execute(
            "SELECT id, course_id, learner_id, teaching_preference, chosen_language, explicit_goals, updated_at "
            "FROM learner_settings WHERE course_id = ? AND learner_id = ?",
            (course_id, learner_id),
        ).fetchone()
        if row:
            return LearnerSettings(
                id=row["id"],
                course_id=row["course_id"],
                learner_id=row["learner_id"],
                teaching_preference=row["teaching_preference"],
                chosen_language=row["chosen_language"],
                explicit_goals=row["explicit_goals"],
                updated_at=row["updated_at"],
            )
        settings = LearnerSettings(
            id=str(uuid.uuid4()),
            course_id=course_id,
            learner_id=learner_id,
        )
        self.con.execute(
            """
            INSERT INTO learner_settings (id, course_id, learner_id, teaching_preference, chosen_language, explicit_goals, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                settings.id,
                settings.course_id,
                settings.learner_id,
                settings.teaching_preference,
                settings.chosen_language,
                settings.explicit_goals,
                settings.updated_at,
            ),
        )
        return settings

    def update_learner_settings(self, settings: LearnerSettings) -> LearnerSettings:
        now = utc_now_iso()
        self.con.execute(
            """
            UPDATE learner_settings SET teaching_preference = ?, chosen_language = ?, explicit_goals = ?, updated_at = ?
            WHERE course_id = ? AND learner_id = ?
            """,
            (
                settings.teaching_preference,
                settings.chosen_language,
                settings.explicit_goals,
                now,
                settings.course_id,
                settings.learner_id,
            ),
        )
        settings.updated_at = now
        return settings


class SourceRepository:
    def __init__(self, con: sqlite3.Connection):
        self.con = con

    def get_or_create_source(self, course_id: str, logical_name: str, role: str = "reference") -> Source:
        row = self.con.execute(
            "SELECT id, course_id, logical_name, role, created_at FROM sources WHERE course_id = ? AND logical_name = ?",
            (course_id, logical_name),
        ).fetchone()
        if row:
            return Source(
                id=row["id"],
                course_id=row["course_id"],
                logical_name=row["logical_name"],
                role=row["role"],
                created_at=row["created_at"],
            )
        source = Source(
            id=str(uuid.uuid4()),
            course_id=course_id,
            logical_name=logical_name,
            role=role,
        )
        self.con.execute(
            "INSERT INTO sources (id, course_id, logical_name, role, created_at) VALUES (?, ?, ?, ?, ?)",
            (source.id, source.course_id, source.logical_name, source.role, source.created_at),
        )
        return source

    def add_source_version(
        self,
        source_id: str,
        course_id: str,
        file_hash: str,
        original_filename: str,
        mime_type: str,
        byte_size: int,
        storage_relpath: str,
        extraction_status: str = "pending",
        extraction_notes: str = "",
    ) -> SourceVersion:
        # Check source ownership
        src_row = self.con.execute("SELECT course_id FROM sources WHERE id = ?", (source_id,)).fetchone()
        if not src_row:
            raise SourceNotFoundError(source_id)
        if src_row["course_id"] != course_id:
            raise CrossCourseViolationError("Source", source_id, course_id, src_row["course_id"])

        # Determine next version number
        ver_row = self.con.execute(
            "SELECT COALESCE(MAX(version_num), 0) + 1 AS next_ver FROM source_versions WHERE source_id = ?",
            (source_id,),
        ).fetchone()
        next_ver = ver_row["next_ver"]

        version = SourceVersion(
            id=str(uuid.uuid4()),
            source_id=source_id,
            course_id=course_id,
            version_num=next_ver,
            file_hash=file_hash,
            original_filename=original_filename,
            mime_type=mime_type,
            byte_size=byte_size,
            storage_relpath=storage_relpath,
            extraction_status=extraction_status,
            extraction_notes=extraction_notes,
        )
        self.con.execute(
            """
            INSERT INTO source_versions (
                id, source_id, course_id, version_num, file_hash, original_filename,
                mime_type, byte_size, storage_relpath, extraction_status, extraction_notes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                version.id,
                version.source_id,
                version.course_id,
                version.version_num,
                version.file_hash,
                version.original_filename,
                version.mime_type,
                version.byte_size,
                version.storage_relpath,
                version.extraction_status,
                version.extraction_notes,
                version.created_at,
            ),
        )
        return version

    def find_version_by_hash(self, course_id: str, file_hash: str) -> Optional[SourceVersion]:
        row = self.con.execute(
            """
            SELECT id, source_id, course_id, version_num, file_hash, original_filename,
                   mime_type, byte_size, storage_relpath, extraction_status, extraction_notes, created_at
            FROM source_versions
            WHERE course_id = ? AND file_hash = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (course_id, file_hash),
        ).fetchone()
        if not row:
            return None
        return SourceVersion(**dict(row))

    def get_source_version(self, version_id: str) -> Optional[SourceVersion]:
        row = self.con.execute(
            """
            SELECT id, source_id, course_id, version_num, file_hash, original_filename,
                   mime_type, byte_size, storage_relpath, extraction_status, extraction_notes, created_at
            FROM source_versions WHERE id = ?
            """,
            (version_id,),
        ).fetchone()
        if not row:
            return None
        return SourceVersion(**dict(row))

    def list_sources(self, course_id: str) -> List[Source]:
        rows = self.con.execute(
            "SELECT id, course_id, logical_name, role, created_at FROM sources WHERE course_id = ? ORDER BY logical_name ASC",
            (course_id,),
        ).fetchall()
        return [Source(**dict(r)) for r in rows]

    def list_source_versions(self, source_id: str) -> List[SourceVersion]:
        rows = self.con.execute(
            """
            SELECT id, source_id, course_id, version_num, file_hash, original_filename,
                   mime_type, byte_size, storage_relpath, extraction_status, extraction_notes, created_at
            FROM source_versions WHERE source_id = ? ORDER BY version_num ASC
            """,
            (source_id,),
        ).fetchall()
        return [SourceVersion(**dict(r)) for r in rows]

    def update_extraction_status(self, version_id: str, status: str, notes: str = "") -> None:
        self.con.execute(
            "UPDATE source_versions SET extraction_status = ?, extraction_notes = ? WHERE id = ?",
            (status, notes, version_id),
        )

    def add_source_section(self, section: SourceSection) -> SourceSection:
        self.con.execute(
            """
            INSERT INTO source_sections (
                id, source_version_id, course_id, section_index, label, text,
                quality_flag, notes, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                section.id,
                section.source_version_id,
                section.course_id,
                section.section_index,
                section.label,
                section.text,
                section.quality_flag,
                section.notes,
                json.dumps(section.metadata),
                section.created_at,
            ),
        )
        return section

    def list_source_sections(self, source_version_id: str) -> List[SourceSection]:
        rows = self.con.execute(
            """
            SELECT id, source_version_id, course_id, section_index, label, text,
                   quality_flag, notes, metadata_json, created_at
            FROM source_sections WHERE source_version_id = ? ORDER BY section_index ASC
            """,
            (source_version_id,),
        ).fetchall()
        return [
            SourceSection(
                id=r["id"],
                source_version_id=r["source_version_id"],
                course_id=r["course_id"],
                section_index=r["section_index"],
                label=r["label"],
                text=r["text"],
                quality_flag=r["quality_flag"],
                notes=r["notes"],
                metadata=json.loads(r["metadata_json"]),
                created_at=r["created_at"],
            )
            for r in rows
        ]


class TopicRepository:
    def __init__(self, con: sqlite3.Connection):
        self.con = con

    def create_topic(self, topic: Topic) -> Topic:
        self.con.execute(
            "INSERT INTO topics (id, course_id, name, slug, parent_topic_id, description, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (topic.id, topic.course_id, topic.name, topic.slug, topic.parent_topic_id, topic.description, topic.created_at),
        )
        return topic

    def get_topic(self, topic_id: str) -> Optional[Topic]:
        row = self.con.execute(
            "SELECT id, course_id, name, slug, parent_topic_id, description, created_at FROM topics WHERE id = ?",
            (topic_id,),
        ).fetchone()
        if not row:
            return None
        return Topic(**dict(row))

    def get_topic_by_slug(self, course_id: str, slug: str) -> Optional[Topic]:
        row = self.con.execute(
            "SELECT id, course_id, name, slug, parent_topic_id, description, created_at FROM topics WHERE course_id = ? AND slug = ?",
            (course_id, slug),
        ).fetchone()
        if not row:
            return None
        return Topic(**dict(row))

    def list_topics(self, course_id: str) -> List[Topic]:
        rows = self.con.execute(
            "SELECT id, course_id, name, slug, parent_topic_id, description, created_at FROM topics WHERE course_id = ? ORDER BY name ASC",
            (course_id,),
        ).fetchall()
        return [Topic(**dict(r)) for r in rows]

    def add_topic_link(self, course_id: str, from_id: str, to_id: str, rel_type: str = "prerequisite") -> TopicLink:
        link_id = str(uuid.uuid4())
        self.con.execute(
            "INSERT OR IGNORE INTO topic_links (id, course_id, from_topic_id, to_topic_id, relationship_type) VALUES (?, ?, ?, ?, ?)",
            (link_id, course_id, from_id, to_id, rel_type),
        )
        return TopicLink(id=link_id, course_id=course_id, from_topic_id=from_id, to_topic_id=to_id, relationship_type=rel_type)

    def list_topic_links(self, course_id: str) -> List[TopicLink]:
        rows = self.con.execute(
            "SELECT id, course_id, from_topic_id, to_topic_id, relationship_type FROM topic_links WHERE course_id = ?",
            (course_id,),
        ).fetchall()
        return [TopicLink(**dict(r)) for r in rows]

    def add_alias(self, course_id: str, topic_id: str, alias: str, language: str = "en") -> TopicAlias:
        alias_id = str(uuid.uuid4())
        self.con.execute(
            "INSERT OR IGNORE INTO topic_aliases (id, course_id, topic_id, alias, language) VALUES (?, ?, ?, ?, ?)",
            (alias_id, course_id, topic_id, alias, language),
        )
        return TopicAlias(id=alias_id, course_id=course_id, topic_id=topic_id, alias=alias, language=language)

    def list_aliases(self, course_id: str, topic_id: Optional[str] = None) -> List[TopicAlias]:
        if topic_id:
            rows = self.con.execute(
                "SELECT id, course_id, topic_id, alias, language FROM topic_aliases WHERE course_id = ? AND topic_id = ?",
                (course_id, topic_id),
            ).fetchall()
        else:
            rows = self.con.execute(
                "SELECT id, course_id, topic_id, alias, language FROM topic_aliases WHERE course_id = ?",
                (course_id,),
            ).fetchall()
        return [TopicAlias(**dict(r)) for r in rows]

    def find_by_alias(self, course_id: str, query: str) -> List[Topic]:
        rows = self.con.execute(
            """
            SELECT DISTINCT t.id, t.course_id, t.name, t.slug, t.parent_topic_id, t.description, t.created_at
            FROM topics t
            JOIN topic_aliases a ON t.id = a.topic_id
            WHERE t.course_id = ? AND (a.alias LIKE ? OR a.alias = ?)
            """,
            (course_id, f"%{query}%", query),
        ).fetchall()
        return [Topic(**dict(r)) for r in rows]


class KnowledgeRepository:
    def __init__(self, con: sqlite3.Connection):
        self.con = con

    def create_unit(
        self,
        unit: KnowledgeUnit,
        provenance_list: List[UnitProvenance],
        topic_ids: List[str],
    ) -> KnowledgeUnit:
        self.con.execute(
            """
            INSERT INTO knowledge_units (
                id, course_id, kind, title, content, summary, assumptions,
                symbol_definitions, exceptions, dependencies, status, revision, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                unit.id,
                unit.course_id,
                unit.kind,
                unit.title,
                unit.content,
                unit.summary,
                json.dumps(unit.assumptions),
                json.dumps(unit.symbol_definitions),
                json.dumps(unit.exceptions),
                json.dumps(unit.dependencies),
                unit.status,
                unit.revision,
                unit.created_at,
                unit.updated_at,
            ),
        )

        for prov in provenance_list:
            self.con.execute(
                """
                INSERT INTO unit_provenance (
                    id, unit_id, source_version_id, page_index, page_label,
                    slide_index, region_box, origin_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    prov.id,
                    unit.id,
                    prov.source_version_id,
                    prov.page_index,
                    prov.page_label,
                    prov.slide_index,
                    json.dumps(prov.region_box) if prov.region_box else None,
                    prov.origin_type,
                ),
            )

        for tid in topic_ids:
            self.con.execute(
                "INSERT OR IGNORE INTO unit_topics (id, unit_id, topic_id) VALUES (?, ?, ?)",
                (str(uuid.uuid4()), unit.id, tid),
            )

        self._index_fts(unit)
        return unit

    def _index_fts(self, unit: KnowledgeUnit) -> None:
        assumptions_str = " ".join(unit.assumptions)
        symbols_str = " ".join(f"{k} {v}" for k, v in unit.symbol_definitions.items())
        # Delete existing entry if present
        self.con.execute("DELETE FROM fts_units WHERE unit_id = ?", (unit.id,))
        self.con.execute(
            """
            INSERT INTO fts_units (unit_id, course_id, title, content, summary, assumptions, symbols)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (unit.id, unit.course_id, unit.title, unit.content, unit.summary, assumptions_str, symbols_str),
        )

    def get_unit(self, unit_id: str) -> Optional[KnowledgeUnit]:
        row = self.con.execute(
            """
            SELECT id, course_id, kind, title, content, summary, assumptions,
                   symbol_definitions, exceptions, dependencies, status, revision, created_at, updated_at
            FROM knowledge_units WHERE id = ?
            """,
            (unit_id,),
        ).fetchone()
        if not row:
            return None
        return KnowledgeUnit(
            id=row["id"],
            course_id=row["course_id"],
            kind=row["kind"],
            title=row["title"],
            content=row["content"],
            summary=row["summary"],
            assumptions=json.loads(row["assumptions"]),
            symbol_definitions=json.loads(row["symbol_definitions"]),
            exceptions=json.loads(row["exceptions"]),
            dependencies=json.loads(row["dependencies"]),
            status=row["status"],
            revision=row["revision"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def get_provenance(self, unit_id: str) -> List[UnitProvenance]:
        rows = self.con.execute(
            """
            SELECT id, unit_id, source_version_id, page_index, page_label, slide_index, region_box, origin_type
            FROM unit_provenance WHERE unit_id = ?
            """,
            (unit_id,),
        ).fetchall()
        return [
            UnitProvenance(
                id=r["id"],
                unit_id=r["unit_id"],
                source_version_id=r["source_version_id"],
                page_index=r["page_index"],
                page_label=r["page_label"],
                slide_index=r["slide_index"],
                region_box=json.loads(r["region_box"]) if r["region_box"] else None,
                origin_type=r["origin_type"],
            )
            for r in rows
        ]

    def get_unit_topics(self, unit_id: str) -> List[str]:
        rows = self.con.execute("SELECT topic_id FROM unit_topics WHERE unit_id = ?", (unit_id,)).fetchall()
        return [r["topic_id"] for r in rows]

    def list_units(self, course_id: str, kind: Optional[str] = None) -> List[KnowledgeUnit]:
        if kind:
            rows = self.con.execute(
                """
                SELECT id, course_id, kind, title, content, summary, assumptions,
                       symbol_definitions, exceptions, dependencies, status, revision, created_at, updated_at
                FROM knowledge_units WHERE course_id = ? AND kind = ? ORDER BY title ASC
                """,
                (course_id, kind),
            ).fetchall()
        else:
            rows = self.con.execute(
                """
                SELECT id, course_id, kind, title, content, summary, assumptions,
                       symbol_definitions, exceptions, dependencies, status, revision, created_at, updated_at
                FROM knowledge_units WHERE course_id = ? ORDER BY title ASC
                """,
                (course_id,),
            ).fetchall()
        return [
            KnowledgeUnit(
                id=r["id"],
                course_id=r["course_id"],
                kind=r["kind"],
                title=r["title"],
                content=r["content"],
                summary=r["summary"],
                assumptions=json.loads(r["assumptions"]),
                symbol_definitions=json.loads(r["symbol_definitions"]),
                exceptions=json.loads(r["exceptions"]),
                dependencies=json.loads(r["dependencies"]),
                status=r["status"],
                revision=r["revision"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
            for r in rows
        ]

    def update_unit_status(self, unit_id: str, status: str) -> None:
        now = utc_now_iso()
        self.con.execute(
            "UPDATE knowledge_units SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, unit_id),
        )

    def find_units_by_title(self, title: str, course_id: Optional[str] = None) -> List[KnowledgeUnit]:
        if course_id:
            rows = self.con.execute(
                """
                SELECT id, course_id, kind, title, content, summary, assumptions,
                       symbol_definitions, exceptions, dependencies, status, revision, created_at, updated_at
                FROM knowledge_units WHERE title = ? AND course_id = ?
                """,
                (title, course_id),
            ).fetchall()
        else:
            rows = self.con.execute(
                """
                SELECT id, course_id, kind, title, content, summary, assumptions,
                       symbol_definitions, exceptions, dependencies, status, revision, created_at, updated_at
                FROM knowledge_units WHERE title = ?
                """,
                (title,),
            ).fetchall()
        return [
            KnowledgeUnit(
                id=r["id"],
                course_id=r["course_id"],
                kind=r["kind"],
                title=r["title"],
                content=r["content"],
                summary=r["summary"],
                assumptions=json.loads(r["assumptions"]),
                symbol_definitions=json.loads(r["symbol_definitions"]),
                exceptions=json.loads(r["exceptions"]),
                dependencies=json.loads(r["dependencies"]),
                status=r["status"],
                revision=r["revision"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
            for r in rows
        ]


def compute_exercise_version_hash(
    question_text: str,
    reference_solution: str = "",
    rubric: Optional[Dict[str, Any]] = None,
    subparts: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Compute a deterministic content hash for an exercise version's educational content."""
    payload = {
        "question_text": question_text,
        "reference_solution": reference_solution,
        "rubric": rubric or {},
        "subparts": subparts or [],
    }
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ExerciseRepository:
    def __init__(self, con: sqlite3.Connection):
        self.con = con

    def create_exercise(self, exercise: Exercise) -> Exercise:
        self.con.execute(
            "INSERT INTO exercises (id, course_id, exercise_family, external_ref, created_at) VALUES (?, ?, ?, ?, ?)",
            (exercise.id, exercise.course_id, exercise.exercise_family, exercise.external_ref, exercise.created_at),
        )
        return exercise

    def create_exercise_version(self, version: ExerciseVersion) -> ExerciseVersion:
        # Cross-course check
        ex_row = self.con.execute("SELECT course_id FROM exercises WHERE id = ?", (version.exercise_id,)).fetchone()
        if not ex_row:
            raise ValidationError(f"Exercise '{version.exercise_id}' not found.")
        if ex_row["course_id"] != version.course_id:
            raise CrossCourseViolationError("Exercise", version.exercise_id, version.course_id, ex_row["course_id"])

        self.con.execute(
            """
            INSERT INTO exercise_versions (
                id, exercise_id, course_id, version_num, question_text, subparts_json,
                topic_mappings_json, skill_mappings_json, reference_solution, rubric_json,
                validation_state, validation_notes, revision_history_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                version.id,
                version.exercise_id,
                version.course_id,
                version.version_num,
                version.question_text,
                json.dumps(version.subparts),
                json.dumps(version.topic_mappings),
                json.dumps(version.skill_mappings),
                version.reference_solution,
                json.dumps(version.rubric),
                version.validation_state,
                version.validation_notes,
                json.dumps(version.revision_history),
                version.created_at,
            ),
        )
        return version

    def get_exercise_version(self, version_id: str) -> Optional[ExerciseVersion]:
        row = self.con.execute(
            """
            SELECT *
            FROM exercise_versions WHERE id = ?
            """,
            (version_id,),
        ).fetchone()
        if not row:
            return None
        rev_hist_raw = row["revision_history_json"] if "revision_history_json" in row.keys() else None
        return ExerciseVersion(
            id=row["id"],
            exercise_id=row["exercise_id"],
            course_id=row["course_id"],
            version_num=row["version_num"],
            question_text=row["question_text"],
            subparts=json.loads(row["subparts_json"]),
            topic_mappings=json.loads(row["topic_mappings_json"]),
            skill_mappings=json.loads(row["skill_mappings_json"]),
            reference_solution=row["reference_solution"],
            rubric=json.loads(row["rubric_json"]),
            validation_state=row["validation_state"],
            validation_notes=row["validation_notes"],
            revision_history=json.loads(rev_hist_raw) if rev_hist_raw else [],
            created_at=row["created_at"],
        )

    def get_exercise(self, exercise_id: str) -> Optional[Exercise]:
        row = self.con.execute(
            "SELECT id, course_id, exercise_family, external_ref, created_at FROM exercises WHERE id = ?",
            (exercise_id,),
        ).fetchone()
        if not row:
            return None
        return Exercise(**dict(row))

    def list_exercises(self, course_id: str) -> List[Exercise]:
        rows = self.con.execute(
            "SELECT id, course_id, exercise_family, external_ref, created_at FROM exercises WHERE course_id = ? ORDER BY created_at ASC",
            (course_id,),
        ).fetchall()
        return [Exercise(**dict(r)) for r in rows]

    def validate_exercise_version(
        self,
        version_id: str,
        reviewer: str = "host_agent",
        checks: Optional[Union[Dict[str, Any], List[str]]] = None,
        notes: str = "",
        status: str = "validated",
        reference_solution: Optional[str] = None,
        rubric: Optional[Dict[str, Any]] = None,
        expected_revision: Optional[int] = None,
        expected_question_text: Optional[str] = None,
        expected_reference_solution: Optional[str] = None,
        expected_rubric: Optional[Dict[str, Any]] = None,
        expected_content_hash: Optional[str] = None,
    ) -> ExerciseVersion:
        initial_ver = self.get_exercise_version(version_id)
        if not initial_ver:
            raise ValidationError(f"Exercise version '{version_id}' not found.")

        # Defect 3: Require caller-side identity validation
        if expected_revision is None and expected_content_hash is None:
            raise ValidationError(
                "validate_exercise_version requires caller-side identity: expected_revision (positive integer) or expected_content_hash must be provided."
            )
        if expected_revision is not None:
            if type(expected_revision) is not int or expected_revision < 1:
                raise ValidationError(
                    f"expected_revision must be a positive integer, got {expected_revision!r} ({type(expected_revision).__name__})."
                )
        if expected_content_hash is not None:
            if not isinstance(expected_content_hash, str) or not expected_content_hash.strip():
                raise ValidationError(
                    f"expected_content_hash must be a non-empty string, got {expected_content_hash!r}."
                )

        initial_revision = len(initial_ver.revision_history) + 1
        initial_hash = compute_exercise_version_hash(
            initial_ver.question_text,
            initial_ver.reference_solution,
            initial_ver.rubric,
            initial_ver.subparts,
        )

        if expected_revision is not None and expected_revision != initial_revision:
            raise StaleRevisionError(
                entity_type="ExerciseVersion",
                entity_id=version_id,
                expected_revision=expected_revision,
                current_revision=initial_revision,
            )
        if expected_question_text is not None and expected_question_text != initial_ver.question_text:
            raise ValidationError(
                f"Exercise version '{version_id}' question text mismatch. Attestation was prepared for a different question text.",
                details={"expected": expected_question_text, "actual": initial_ver.question_text},
            )
        if expected_reference_solution is not None and expected_reference_solution != initial_ver.reference_solution:
            raise ValidationError(
                f"Exercise version '{version_id}' reference solution mismatch.",
                details={"expected": expected_reference_solution, "actual": initial_ver.reference_solution},
            )
        if expected_rubric is not None and expected_rubric != initial_ver.rubric:
            raise ValidationError(
                f"Exercise version '{version_id}' rubric mismatch.",
                details={"expected": expected_rubric, "actual": initial_ver.rubric},
            )
        if expected_content_hash is not None and expected_content_hash != initial_hash:
            raise ValidationError(
                f"Exercise version '{version_id}' content hash mismatch.",
                details={"expected_hash": expected_content_hash, "actual_hash": initial_hash},
            )

        effective_solution = reference_solution if reference_solution is not None else initial_ver.reference_solution
        effective_rubric = rubric if rubric is not None else initial_ver.rubric

        # Defect 5: Unambiguous verification-check schema and validation
        ALLOWED_CHECK_KEYS = frozenset({"status", "state", "reason", "notes", "metadata", "score"})
        PASSING_CHECK_STATUSES = frozenset({"passed", "verified", "ok", "success"})
        FAILING_OR_PENDING_STATUSES = frozenset({"failed", "falsified", "rejected", "pending", "unknown"})

        checks_dict: Dict[str, Any] = {}
        failing_checks: List[str] = []

        if checks is None:
            checks_dict = {}
        elif isinstance(checks, list):
            seen_check_names: set[str] = set()
            for c in checks:
                if not isinstance(c, str) or not c.strip() or not re.match(r"^[a-zA-Z0-9_\-\.]+$", c.strip()):
                    raise ValidationError(f"Invalid verification check name: {c!r}")
                c_clean = c.strip()
                c_norm = c_clean.lower()
                if c_norm in seen_check_names:
                    raise ValidationError(f"Duplicate verification check name: {c!r}")
                seen_check_names.add(c_norm)
                checks_dict[c_clean] = True
        elif isinstance(checks, dict):
            seen_check_names = set()
            for k, v in checks.items():
                if not isinstance(k, str) or not k.strip() or not re.match(r"^[a-zA-Z0-9_\-\.]+$", k.strip()):
                    raise ValidationError(f"Invalid verification check name: {k!r}")
                k_clean = k.strip()
                k_norm = k_clean.lower()
                if k_norm in seen_check_names:
                    raise ValidationError(f"Duplicate verification check name: {k!r}")
                seen_check_names.add(k_norm)

                if type(v) is bool:
                    checks_dict[k_clean] = v
                    if not v:
                        failing_checks.append(k_clean)
                elif isinstance(v, dict):
                    unknown_keys = set(v.keys()) - ALLOWED_CHECK_KEYS
                    if unknown_keys:
                        raise ValidationError(
                            f"Invalid keys in structured check for '{k}': {sorted(unknown_keys)}. Allowed keys: {sorted(ALLOWED_CHECK_KEYS)}."
                        )
                    status_val = v.get("status")
                    state_val = v.get("state")
                    if status_val is None and state_val is None:
                        raise ValidationError(f"Structured check for '{k}' must provide 'status' or 'state'.")
                    if status_val is not None and not isinstance(status_val, str):
                        raise ValidationError(f"Structured check 'status' for '{k}' must be a string, got {status_val!r}.")
                    if state_val is not None and not isinstance(state_val, str):
                        raise ValidationError(f"Structured check 'state' for '{k}' must be a string, got {state_val!r}.")

                    # Defect 6 / Defect 7: Validate finite numeric score and schema fields
                    score_val = v.get("score")
                    if score_val is not None:
                        validate_finite_number(score_val, f"Structured check 'score' for '{k}'", min_val=0.0)

                    reason_val = v.get("reason")
                    if reason_val is not None and not isinstance(reason_val, str):
                        raise ValidationError(
                            f"Structured check 'reason' for '{k}' must be a string, got {type(reason_val).__name__} ({reason_val!r})."
                        )

                    notes_val = v.get("notes")
                    if notes_val is not None and not isinstance(notes_val, str):
                        raise ValidationError(
                            f"Structured check 'notes' for '{k}' must be a string, got {type(notes_val).__name__} ({notes_val!r})."
                        )

                    meta_val = v.get("metadata")
                    if meta_val is not None:
                        if not isinstance(meta_val, dict):
                            raise ValidationError(
                                f"Structured check 'metadata' for '{k}' must be a dictionary, got {type(meta_val).__name__} ({meta_val!r})."
                            )
                        validate_finite_metadata(meta_val, f"Structured check 'metadata' for '{k}'")


                    s_lower = status_val.strip().lower() if status_val is not None else None
                    st_lower = state_val.strip().lower() if state_val is not None else None

                    if s_lower is not None and st_lower is not None:
                        is_s_pass = s_lower in PASSING_CHECK_STATUSES
                        is_st_pass = st_lower in PASSING_CHECK_STATUSES
                        is_s_fail = s_lower in FAILING_OR_PENDING_STATUSES
                        is_st_fail = st_lower in FAILING_OR_PENDING_STATUSES
                        if (is_s_pass and is_st_fail) or (is_s_fail and is_st_pass) or (s_lower != st_lower and (is_s_pass != is_st_pass)):
                            raise ValidationError(
                                f"Conflicting status ('{status_val}') and state ('{state_val}') in structured check for '{k}'."
                            )

                    effective_status = s_lower if s_lower is not None else st_lower
                    if effective_status in PASSING_CHECK_STATUSES:
                        checks_dict[k_clean] = v
                    elif effective_status in FAILING_OR_PENDING_STATUSES:
                        checks_dict[k_clean] = v
                        failing_checks.append(k_clean)
                    else:
                        raise ValidationError(f"Unknown structured check status for '{k}': {effective_status!r}")
                else:
                    raise ValidationError(
                        f"Invalid check value type for check '{k}': {type(v).__name__} ({v!r}). "
                        "Checks must be boolean True or passing structured check dictionary."
                    )
        else:
            raise ValidationError(f"Invalid checks format: {type(checks).__name__}")

        if status == "validated":
            if not effective_solution or not effective_solution.strip():
                raise ValidationError(
                    f"Cannot validate exercise version '{version_id}': missing reference or verified solution."
                )
            if not effective_rubric or not isinstance(effective_rubric, dict) or len(effective_rubric) == 0:
                raise ValidationError(
                    f"Cannot validate exercise version '{version_id}': missing versioned rubric."
                )
            if not checks_dict or len(checks_dict) == 0:
                raise ValidationError(
                    f"Cannot validate exercise version '{version_id}': missing recorded verification checks."
                )
            if failing_checks:
                raise ValidationError(
                    f"Cannot validate exercise version '{version_id}': verification checks must pass, but found failed check(s): {failing_checks}."
                )

        with atomic_transaction(self.con):
            ex_ver = self.get_exercise_version(version_id)
            if not ex_ver:
                raise ValidationError(f"Exercise version '{version_id}' not found.")

            current_revision = len(ex_ver.revision_history) + 1
            current_hash = compute_exercise_version_hash(
                ex_ver.question_text,
                ex_ver.reference_solution,
                ex_ver.rubric,
                ex_ver.subparts,
            )

            # Defect B: Reject stale attestation if question/solution/rubric was concurrently modified
            if (
                current_revision != initial_revision
                or ex_ver.question_text != initial_ver.question_text
                or ex_ver.reference_solution != initial_ver.reference_solution
                or ex_ver.rubric != initial_ver.rubric
            ):
                raise StaleRevisionError(
                    entity_type="ExerciseVersion",
                    entity_id=version_id,
                    expected_revision=initial_revision,
                    current_revision=current_revision,
                )

            if expected_revision is not None and expected_revision != current_revision:
                raise StaleRevisionError(
                    entity_type="ExerciseVersion",
                    entity_id=version_id,
                    expected_revision=expected_revision,
                    current_revision=current_revision,
                )
            if expected_question_text is not None and expected_question_text != ex_ver.question_text:
                raise ValidationError(
                    f"Exercise version '{version_id}' question text mismatch inside transaction.",
                    details={"expected": expected_question_text, "actual": ex_ver.question_text},
                )
            if expected_reference_solution is not None and expected_reference_solution != ex_ver.reference_solution:
                raise ValidationError(
                    f"Exercise version '{version_id}' reference solution mismatch inside transaction.",
                    details={"expected": expected_reference_solution, "actual": ex_ver.reference_solution},
                )
            if expected_rubric is not None and expected_rubric != ex_ver.rubric:
                raise ValidationError(
                    f"Exercise version '{version_id}' rubric mismatch inside transaction.",
                    details={"expected": expected_rubric, "actual": ex_ver.rubric},
                )
            if expected_content_hash is not None and expected_content_hash != current_hash:
                raise ValidationError(
                    f"Exercise version '{version_id}' content hash mismatch inside transaction.",
                    details={"expected_hash": expected_content_hash, "actual_hash": current_hash},
                )

            solution_changed = (
                reference_solution is not None
                and reference_solution != ex_ver.reference_solution
                and bool(ex_ver.reference_solution)
            )
            rubric_changed = (
                rubric is not None
                and rubric != ex_ver.rubric
                and bool(ex_ver.rubric)
            )

            revision_history = list(ex_ver.revision_history)
            if solution_changed or rubric_changed:
                snapshot = {
                    "question_text": ex_ver.question_text,
                    "reference_solution": ex_ver.reference_solution,
                    "rubric": ex_ver.rubric,
                    "validation_state": ex_ver.validation_state,
                    "validation_notes": ex_ver.validation_notes,
                    "timestamp": utc_now_iso(),
                }
                revision_history.append(snapshot)

                evidence_rows = self.con.execute(
                    "SELECT DISTINCT topic_id FROM evidence WHERE exercise_version_id = ? AND status = 'active'",
                    (version_id,),
                ).fetchall()
                affected_topics = {r["topic_id"] for r in evidence_rows}
                affected_topics.update(ex_ver.topic_mappings)

                self.con.execute(
                    "UPDATE evidence SET status = 'pending_review', correction_reason = 'Invalidated due to reference solution or rubric change', updated_at = ? WHERE exercise_version_id = ? AND status = 'active'",
                    (utc_now_iso(), version_id),
                )

                # Invalidate linked assessment items with audit history entries
                assessment_repo = AssessmentRepository(self.con)
                affected_items = assessment_repo.get_items_by_exercise_version(version_id)
                for it in affected_items:
                    if it.points_awarded is not None:
                        history_entry = {
                            "points_awarded": None,
                            "previous_points": it.points_awarded,
                            "attempt_id": it.attempt_id,
                            "action": "invalidated_by_exercise_update",
                            "reason": "Invalidated due to reference solution or rubric change",
                            "recorded_at": utc_now_iso(),
                        }
                        score_history = list(it.score_history) + [history_entry]
                        assessment_repo.update_item_progress(
                            it.id,
                            attempt_id=it.attempt_id,
                            points_awarded=None,
                            score_status="pending_review",
                            score_history=score_history,
                            evidence_ids=[],
                        )

                self.con.execute(
                    "UPDATE assessments SET status = 'open' WHERE id IN (SELECT assessment_id FROM assessment_items WHERE exercise_version_id = ?)",
                    (version_id,),
                )

                evidence_repo = EvidenceRepository(self.con)
                for tid in affected_topics:
                    evidence_repo.recompute_topic_state(ex_ver.course_id, tid)

            final_revision = len(revision_history) + 1
            final_hash = compute_exercise_version_hash(
                ex_ver.question_text,
                effective_solution,
                effective_rubric,
                ex_ver.subparts,
            )

            provenance = {
                "reviewer": reviewer,
                "checks": checks_dict,
                "notes": notes,
                "validated_at": utc_now_iso(),
                "checked_revision": final_revision,
                "content_hash": final_hash,
            }
            if final_revision != current_revision:
                provenance["previous_revision"] = current_revision
                provenance["previous_content_hash"] = current_hash
            provenance_json = json.dumps(provenance)

            self.con.execute(
                """
                UPDATE exercise_versions SET
                    reference_solution = ?,
                    rubric_json = ?,
                    validation_state = ?,
                    validation_notes = ?,
                    revision_history_json = ?
                WHERE id = ?
                """,
                (
                    effective_solution,
                    json.dumps(effective_rubric),
                    status,
                    provenance_json,
                    json.dumps(revision_history),
                    version_id,
                ),
            )
        return self.get_exercise_version(version_id)

    def update_exercise_version(
        self,
        version_id: str,
        question_text: Optional[str] = None,
        reference_solution: Optional[str] = None,
        rubric: Optional[Dict[str, Any]] = None,
        expected_revision: Optional[int] = None,
    ) -> ExerciseVersion:
        with atomic_transaction(self.con):
            ex_ver = self.get_exercise_version(version_id)
            if not ex_ver:
                raise ValidationError(f"Exercise version '{version_id}' not found.")

            current_revision = len(ex_ver.revision_history) + 1
            if expected_revision is not None and expected_revision != current_revision:
                raise StaleRevisionError(
                    entity_type="ExerciseVersion",
                    entity_id=version_id,
                    expected_revision=expected_revision,
                    current_revision=current_revision,
                )

            updates = []
            params = []
            content_changed = False

            if question_text is not None and question_text != ex_ver.question_text:
                updates.append("question_text = ?")
                params.append(question_text)
                content_changed = True
            if reference_solution is not None and reference_solution != ex_ver.reference_solution:
                updates.append("reference_solution = ?")
                params.append(reference_solution)
                content_changed = True
            if rubric is not None and rubric != ex_ver.rubric:
                updates.append("rubric_json = ?")
                params.append(json.dumps(rubric))
                content_changed = True

            if content_changed:
                evidence_rows = self.con.execute(
                    "SELECT DISTINCT topic_id FROM evidence WHERE exercise_version_id = ? AND status = 'active'",
                    (version_id,),
                ).fetchall()
                affected_topics = {r["topic_id"] for r in evidence_rows}
                affected_topics.update(ex_ver.topic_mappings)

                snapshot = {
                    "question_text": ex_ver.question_text,
                    "reference_solution": ex_ver.reference_solution,
                    "rubric": ex_ver.rubric,
                    "validation_state": ex_ver.validation_state,
                    "validation_notes": ex_ver.validation_notes,
                    "timestamp": utc_now_iso(),
                }
                revision_history = list(ex_ver.revision_history) + [snapshot]

                updates.append("validation_state = 'pending_review'")
                updates.append("validation_notes = 'Invalidated due to question or rubric changes; requires re-verification'")
                updates.append("revision_history_json = ?")
                params.append(json.dumps(revision_history))
                params.append(version_id)
                sql = f"UPDATE exercise_versions SET {', '.join(updates)} WHERE id = ?"
                self.con.execute(sql, params)

                self.con.execute(
                    "UPDATE evidence SET status = 'pending_review', correction_reason = 'Invalidated due to exercise question/rubric change', updated_at = ? WHERE exercise_version_id = ? AND status = 'active'",
                    (utc_now_iso(), version_id),
                )

                # Invalidate linked assessment items with audit history entries
                assessment_repo = AssessmentRepository(self.con)
                affected_items = assessment_repo.get_items_by_exercise_version(version_id)
                for it in affected_items:
                    if it.points_awarded is not None:
                        history_entry = {
                            "points_awarded": None,
                            "previous_points": it.points_awarded,
                            "attempt_id": it.attempt_id,
                            "action": "invalidated_by_exercise_update",
                            "reason": "Invalidated due to exercise question/rubric change",
                            "recorded_at": utc_now_iso(),
                        }
                        score_history = list(it.score_history) + [history_entry]
                        assessment_repo.update_item_progress(
                            it.id,
                            attempt_id=it.attempt_id,
                            points_awarded=None,
                            score_status="pending_review",
                            score_history=score_history,
                            evidence_ids=[],
                        )

                self.con.execute(
                    "UPDATE assessments SET status = 'open' WHERE id IN (SELECT assessment_id FROM assessment_items WHERE exercise_version_id = ?)",
                    (version_id,),
                )

                evidence_repo = EvidenceRepository(self.con)
                for tid in affected_topics:
                    evidence_repo.recompute_topic_state(ex_ver.course_id, tid)

        return self.get_exercise_version(version_id)


class AttemptRepository:
    def __init__(self, con: sqlite3.Connection):
        self.con = con

    def create_attempt(self, attempt: Attempt) -> Attempt:
        self.con.execute(
            """
            INSERT INTO attempts (id, course_id, exercise_version_id, learner_id, mode, status, current_revision, started_at, updated_at, completed_at, exercise_revision, exercise_content_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt.id,
                attempt.course_id,
                attempt.exercise_version_id,
                attempt.learner_id,
                attempt.mode,
                attempt.status,
                attempt.current_revision,
                attempt.started_at,
                attempt.updated_at,
                attempt.completed_at,
                attempt.exercise_revision,
                attempt.exercise_content_hash,
            ),
        )
        return attempt

    def get_attempt(self, attempt_id: str) -> Optional[Attempt]:
        row = self.con.execute(
            "SELECT id, course_id, exercise_version_id, learner_id, mode, status, current_revision, started_at, updated_at, completed_at, exercise_revision, exercise_content_hash "
            "FROM attempts WHERE id = ?",
            (attempt_id,),
        ).fetchone()
        if not row:
            return None
        return Attempt(**dict(row))

    def get_open_attempt(self, course_id: str, learner_id: str) -> Optional[Attempt]:
        row = self.con.execute(
            "SELECT id, course_id, exercise_version_id, learner_id, mode, status, current_revision, started_at, updated_at, completed_at, exercise_revision, exercise_content_hash "
            "FROM attempts WHERE course_id = ? AND learner_id = ? AND status IN ('open', 'paused') ORDER BY updated_at DESC LIMIT 1",
            (course_id, learner_id),
        ).fetchone()
        if not row:
            return None
        return Attempt(**dict(row))

    def update_attempt(self, attempt: Attempt, expected_revision: int) -> Attempt:
        current = self.get_attempt(attempt.id)
        if not current:
            raise ValidationError(f"Attempt '{attempt.id}' not found.")
        if current.current_revision != expected_revision:
            raise StaleRevisionError("Attempt", attempt.id, expected_revision, current.current_revision)

        new_rev = current.current_revision + 1
        now = utc_now_iso()
        self.con.execute(
            """
            UPDATE attempts SET status = ?, current_revision = ?, updated_at = ?, completed_at = ?
            WHERE id = ? AND current_revision = ?
            """,
            (attempt.status, new_rev, now, attempt.completed_at, attempt.id, expected_revision),
        )
        attempt.current_revision = new_rev
        attempt.updated_at = now
        return attempt

    def add_event(self, event: AttemptEvent) -> AttemptEvent:
        self.con.execute(
            """
            INSERT INTO attempt_events (id, attempt_id, course_id, event_index, event_type, subpart_key, content, event_metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.id,
                event.attempt_id,
                event.course_id,
                event.event_index,
                event.event_type,
                event.subpart_key,
                event.content,
                json.dumps(event.metadata),
                event.created_at,
            ),
        )
        return event

    def list_events(self, attempt_id: str) -> List[AttemptEvent]:
        rows = self.con.execute(
            """
            SELECT id, attempt_id, course_id, event_index, event_type, subpart_key, content, event_metadata_json, created_at
            FROM attempt_events WHERE attempt_id = ? ORDER BY event_index ASC
            """,
            (attempt_id,),
        ).fetchall()
        return [
            AttemptEvent(
                id=r["id"],
                attempt_id=r["attempt_id"],
                course_id=r["course_id"],
                event_index=r["event_index"],
                event_type=r["event_type"],
                subpart_key=r["subpart_key"],
                content=r["content"],
                metadata=json.loads(r["event_metadata_json"]),
                created_at=r["created_at"],
            )
            for r in rows
        ]


class EvidenceRepository:
    def __init__(self, con: sqlite3.Connection):
        self.con = con

    def create_evidence(self, rec: EvidenceRecord) -> EvidenceRecord:
        self.con.execute(
            """
            INSERT INTO evidence (
                id, course_id, attempt_id, event_id, exercise_version_id, topic_id, skill_id,
                subpart_key, demonstrated_level, error_category, rationale, status,
                parent_evidence_id, correction_reason, created_at, updated_at,
                exercise_revision, exercise_content_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rec.id,
                rec.course_id,
                rec.attempt_id,
                rec.event_id,
                rec.exercise_version_id,
                rec.topic_id,
                rec.skill_id,
                rec.subpart_key,
                rec.demonstrated_level,
                rec.error_category,
                rec.rationale,
                rec.status,
                rec.parent_evidence_id,
                rec.correction_reason,
                rec.created_at,
                rec.updated_at,
                rec.exercise_revision,
                rec.exercise_content_hash,
            ),
        )
        return rec

    def get_evidence(self, evidence_id: str) -> Optional[EvidenceRecord]:
        row = self.con.execute(
            """
            SELECT id, course_id, attempt_id, event_id, exercise_version_id, topic_id, skill_id,
                   subpart_key, demonstrated_level, error_category, rationale, status,
                   parent_evidence_id, correction_reason, created_at, updated_at,
                   exercise_revision, exercise_content_hash
            FROM evidence WHERE id = ?
            """,
            (evidence_id,),
        ).fetchone()
        if not row:
            return None
        return EvidenceRecord(**dict(row))

    def list_evidence(
        self,
        course_id: str,
        attempt_id: Optional[str] = None,
        topic_id: Optional[str] = None,
        status: str = "active",
    ) -> List[EvidenceRecord]:
        query = "SELECT * FROM evidence WHERE course_id = ?"
        params: List[Any] = [course_id]

        if status != "all":
            query += " AND status = ?"
            params.append(status)
        if attempt_id:
            query += " AND attempt_id = ?"
            params.append(attempt_id)
        if topic_id:
            query += " AND topic_id = ?"
            params.append(topic_id)

        query += " ORDER BY created_at ASC"
        rows = self.con.execute(query, params).fetchall()
        return [EvidenceRecord(**dict(r)) for r in rows]

    def retract_evidence(self, evidence_id: str, reason: str) -> EvidenceRecord:
        rec = self.get_evidence(evidence_id)
        if not rec:
            raise ValidationError(f"Evidence '{evidence_id}' not found.")
        now = utc_now_iso()
        self.con.execute(
            "UPDATE evidence SET status = 'retracted', correction_reason = ?, updated_at = ? WHERE id = ?",
            (reason, now, evidence_id),
        )
        rec.status = "retracted"
        rec.correction_reason = reason
        rec.updated_at = now
        return rec

    def supersede_evidence(self, old_evidence_id: str, replacement: EvidenceRecord, reason: str) -> EvidenceRecord:
        old = self.get_evidence(old_evidence_id)
        if not old:
            raise ValidationError(f"Prior evidence '{old_evidence_id}' not found.")
        now = utc_now_iso()
        self.con.execute(
            "UPDATE evidence SET status = 'superseded', correction_reason = ?, updated_at = ? WHERE id = ?",
            (reason, now, old_evidence_id),
        )
        replacement.parent_evidence_id = old_evidence_id
        replacement.correction_reason = reason
        return self.create_evidence(replacement)

    def get_topic_state(self, course_id: str, topic_id: str) -> Optional[TopicState]:
        topic_row = self.con.execute(
            "SELECT id FROM topics WHERE course_id = ? AND (id = ? OR slug = ?)",
            (course_id, topic_id, topic_id),
        ).fetchone()
        lookup_id = topic_row["id"] if topic_row else topic_id

        row = self.con.execute(
            """
            SELECT id, course_id, topic_id, policy_version, independent_success_count,
                   assisted_success_count, partial_progress_count, error_count, unassessed_flag,
                   last_evidence_event_id, summary_json, updated_at
            FROM topic_state WHERE course_id = ? AND topic_id = ?
            """,
            (course_id, lookup_id),
        ).fetchone()
        if not row:
            return None
        return TopicState(
            id=row["id"],
            course_id=row["course_id"],
            topic_id=row["topic_id"],
            policy_version=row["policy_version"],
            independent_success_count=row["independent_success_count"],
            assisted_success_count=row["assisted_success_count"],
            partial_progress_count=row["partial_progress_count"],
            error_count=row["error_count"],
            unassessed_flag=bool(row["unassessed_flag"]),
            last_evidence_event_id=row["last_evidence_event_id"],
            summary_data=json.loads(row["summary_json"]),
            updated_at=row["updated_at"],
        )

    def recompute_topic_state(self, course_id: str, topic_id: str) -> Optional[TopicState]:
        """Deterministically rebuild topic state projection from active evidence."""
        topic_row = self.con.execute(
            "SELECT id FROM topics WHERE course_id = ? AND (id = ? OR slug = ?)",
            (course_id, topic_id, topic_id),
        ).fetchone()
        if not topic_row:
            return None
        actual_topic_id = topic_row["id"]

        active_evs = self.list_evidence(course_id, topic_id=actual_topic_id, status="active")
        if not active_evs and topic_id != actual_topic_id:
            active_evs = self.list_evidence(course_id, topic_id=topic_id, status="active")

        # Defect 2: Filter active evidence by educational identity eligibility!
        # Only active evidence whose educational identity is resolved and matches the current
        # exercise version's revision and content hash is eligible for current topic performance.
        eligible_active_evs = []
        ex_ver_cache: Dict[str, Optional[Tuple[int, str]]] = {}
        for e in active_evs:
            if not is_identity_resolved(e.exercise_revision, e.exercise_content_hash):
                continue
            if e.exercise_version_id not in ex_ver_cache:
                ex_row = self.con.execute(
                    "SELECT question_text, reference_solution, rubric_json, subparts_json, revision_history_json FROM exercise_versions WHERE id = ?",
                    (e.exercise_version_id,),
                ).fetchone()
                if not ex_row:
                    ex_ver_cache[e.exercise_version_id] = None
                else:
                    try:
                        rev_h = json.loads(ex_row["revision_history_json"] or "[]")
                    except Exception:
                        rev_h = []
                    c_rev = len(rev_h) + 1
                    try:
                        subp = json.loads(ex_row["subparts_json"] or "[]")
                    except Exception:
                        subp = []
                    try:
                        rubr = json.loads(ex_row["rubric_json"] or "{}")
                    except Exception:
                        rubr = {}
                    c_h = compute_exercise_version_hash(
                        ex_row["question_text"],
                        ex_row["reference_solution"],
                        rubr,
                        subp,
                    )
                    ex_ver_cache[e.exercise_version_id] = (c_rev, c_h)

            ex_info = ex_ver_cache[e.exercise_version_id]
            if ex_info and e.exercise_revision == ex_info[0] and e.exercise_content_hash == ex_info[1]:
                ok, _ = check_evidence_eligibility_chain(self.con, e, ex_info[0], ex_info[1])
                if ok:
                    eligible_active_evs.append(e)

        ind_success = sum(1 for e in eligible_active_evs if e.demonstrated_level == "independent_mastery")
        ass_success = sum(1 for e in eligible_active_evs if e.demonstrated_level == "assisted_success")
        partial_prog = sum(1 for e in eligible_active_evs if e.demonstrated_level == "partial_progress")
        errors = sum(1 for e in eligible_active_evs if e.demonstrated_level == "incorrect")
        evaluated_evs = [e for e in eligible_active_evs if e.demonstrated_level in EVALUATED_DEMONSTRATED_LEVELS]
        is_unassessed = len(evaluated_evs) == 0
        last_event_id = eligible_active_evs[-1].event_id if eligible_active_evs else None
        now = utc_now_iso()

        error_breakdown: Dict[str, int] = {}
        for e in eligible_active_evs:
            if e.error_category:
                error_breakdown[e.error_category] = error_breakdown.get(e.error_category, 0) + 1

        summary = {
            "total_active_evidence": len(eligible_active_evs),
            "error_breakdown": error_breakdown,
            "skills_assessed": list({e.skill_id for e in eligible_active_evs}),
        }


        row = self.con.execute(
            "SELECT id FROM topic_state WHERE course_id = ? AND topic_id = ?",
            (course_id, actual_topic_id),
        ).fetchone()

        if row:
            state_id = row["id"]
            self.con.execute(
                """
                UPDATE topic_state SET
                    independent_success_count = ?, assisted_success_count = ?,
                    partial_progress_count = ?, error_count = ?, unassessed_flag = ?,
                    last_evidence_event_id = ?, summary_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    ind_success,
                    ass_success,
                    partial_prog,
                    errors,
                    1 if is_unassessed else 0,
                    last_event_id,
                    json.dumps(summary),
                    now,
                    state_id,
                ),
            )
        else:
            state_id = str(uuid.uuid4())
            self.con.execute(
                """
                INSERT INTO topic_state (
                    id, course_id, topic_id, policy_version, independent_success_count,
                    assisted_success_count, partial_progress_count, error_count,
                    unassessed_flag, last_evidence_event_id, summary_json, updated_at
                ) VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    state_id,
                    course_id,
                    actual_topic_id,
                    ind_success,
                    ass_success,
                    partial_prog,
                    errors,
                    1 if is_unassessed else 0,
                    last_event_id,
                    json.dumps(summary),
                    now,
                ),
            )

        return TopicState(
            id=state_id,
            course_id=course_id,
            topic_id=actual_topic_id,
            policy_version=1,
            independent_success_count=ind_success,
            assisted_success_count=ass_success,
            partial_progress_count=partial_prog,
            error_count=errors,
            unassessed_flag=is_unassessed,
            last_evidence_event_id=last_event_id,
            summary_data=summary,
            updated_at=now,
        )


class AssessmentRepository:
    def __init__(self, con: sqlite3.Connection):
        self.con = con

    def _row_to_item(self, row: sqlite3.Row) -> AssessmentItem:
        d = dict(row)
        score_history_raw = d.pop("score_history_json", None)
        d["score_history"] = json.loads(score_history_raw) if score_history_raw else []
        evidence_ids_raw = d.pop("evidence_ids_json", None)
        d["evidence_ids"] = json.loads(evidence_ids_raw) if evidence_ids_raw else []
        if "score_status" not in d:
            d["score_status"] = "scored" if d.get("points_awarded") is not None else "unassessed"
        if "learner_id" not in d:
            d["learner_id"] = None
        return AssessmentItem(**d)

    def create_assessment(self, assessment: Assessment, items: List[AssessmentItem]) -> Assessment:
        self.con.execute(
            "INSERT INTO assessments (id, course_id, title, blueprint_json, learner_id, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                assessment.id,
                assessment.course_id,
                assessment.title,
                json.dumps(assessment.blueprint),
                assessment.learner_id,
                assessment.status,
                assessment.created_at,
                assessment.updated_at,
            ),
        )
        for it in items:
            self.con.execute(
                """
                INSERT INTO assessment_items (
                    id, assessment_id, exercise_version_id, item_order, attempt_id, learner_id,
                    weight, max_points, points_awarded, exposure_count,
                    score_status, score_history_json, evidence_ids_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    it.id,
                    it.assessment_id,
                    it.exercise_version_id,
                    it.item_order,
                    it.attempt_id,
                    it.learner_id or assessment.learner_id,
                    it.weight,
                    it.max_points,
                    it.points_awarded,
                    it.exposure_count,
                    it.score_status,
                    json.dumps(it.score_history),
                    json.dumps(it.evidence_ids),
                    it.created_at,
                ),
            )
        return assessment

    def get_assessment(self, assessment_id: str) -> Optional[Assessment]:
        row = self.con.execute(
            "SELECT * FROM assessments WHERE id = ?",
            (assessment_id,),
        ).fetchone()
        if not row:
            return None
        return Assessment(
            id=row["id"],
            course_id=row["course_id"],
            title=row["title"],
            blueprint=json.loads(row["blueprint_json"]),
            learner_id=row["learner_id"] if "learner_id" in row.keys() else None,
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list_assessments(self, course_id: str) -> List[Assessment]:
        rows = self.con.execute(
            "SELECT * FROM assessments WHERE course_id = ? ORDER BY created_at DESC",
            (course_id,),
        ).fetchall()
        return [
            Assessment(
                id=r["id"],
                course_id=r["course_id"],
                title=r["title"],
                blueprint=json.loads(r["blueprint_json"]),
                learner_id=r["learner_id"] if "learner_id" in r.keys() else None,
                status=r["status"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
            for r in rows
        ]

    def update_assessment_learner(self, assessment_id: str, learner_id: str) -> None:
        self.con.execute(
            "UPDATE assessments SET learner_id = ?, updated_at = ? WHERE id = ?",
            (learner_id, utc_now_iso(), assessment_id),
        )

    def get_items(self, assessment_id: str) -> List[AssessmentItem]:
        rows = self.con.execute(
            """
            SELECT *
            FROM assessment_items WHERE assessment_id = ? ORDER BY item_order ASC
            """,
            (assessment_id,),
        ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def update_item_progress(
        self,
        item_id: str,
        attempt_id: Optional[str] = None,
        points_awarded: Optional[float] = None,
        score_status: Optional[str] = None,
        score_history: Optional[List[Dict[str, Any]]] = None,
        evidence_ids: Optional[List[str]] = None,
        learner_id: Optional[str] = None,
    ) -> None:
        updates = ["points_awarded = ?"]
        params: List[Any] = [points_awarded]

        if attempt_id is not None:
            updates.append("attempt_id = ?")
            params.append(attempt_id)
        if learner_id is not None:
            updates.append("learner_id = ?")
            params.append(learner_id)
        if score_status is not None:
            updates.append("score_status = ?")
            params.append(score_status)
        if score_history is not None:
            updates.append("score_history_json = ?")
            params.append(json.dumps(score_history))
        if evidence_ids is not None:
            updates.append("evidence_ids_json = ?")
            params.append(json.dumps(evidence_ids))

        params.append(item_id)
        sql = f"UPDATE assessment_items SET {', '.join(updates)} WHERE id = ?"
        self.con.execute(sql, params)

    def get_item_by_order(self, assessment_id: str, item_order: int) -> Optional[AssessmentItem]:
        row = self.con.execute(
            """
            SELECT *
            FROM assessment_items WHERE assessment_id = ? AND item_order = ?
            """,
            (assessment_id, item_order),
        ).fetchone()
        if not row:
            return None
        return self._row_to_item(row)

    def get_item_by_attempt(self, attempt_id: str) -> Optional[AssessmentItem]:
        row = self.con.execute(
            """
            SELECT *
            FROM assessment_items WHERE attempt_id = ?
            """,
            (attempt_id,),
        ).fetchone()
        if not row:
            return None
        return self._row_to_item(row)

    def get_items_by_attempt(self, attempt_id: str) -> List[AssessmentItem]:
        rows = self.con.execute(
            """
            SELECT *
            FROM assessment_items WHERE attempt_id = ?
            """,
            (attempt_id,),
        ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def get_items_by_exercise_version(self, exercise_version_id: str) -> List[AssessmentItem]:
        rows = self.con.execute(
            """
            SELECT *
            FROM assessment_items WHERE exercise_version_id = ?
            """,
            (exercise_version_id,),
        ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def update_item_score(
        self, assessment_id: str, item_order: int, attempt_id: str, points_awarded: float
    ) -> AssessmentItem:
        item = self.get_item_by_order(assessment_id, item_order)
        if not item:
            raise ValidationError(f"Assessment item {item_order} not found in assessment '{assessment_id}'.")
        self.update_item_progress(item.id, attempt_id=attempt_id, points_awarded=points_awarded, score_status="scored")
        return self.get_item_by_order(assessment_id, item_order)

    def update_assessment_status(self, assessment_id: str, status: str) -> None:
        self.con.execute(
            "UPDATE assessments SET status = ?, updated_at = ? WHERE id = ?",
            (status, utc_now_iso(), assessment_id),
        )
