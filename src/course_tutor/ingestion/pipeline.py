"""Ingestion pipeline coordinating staging, hashing, format extraction, and unit persistence."""

from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional, Union
import uuid

from ..errors import CourseNotFoundError, WorkspaceError, ValidationError, ConflictError
from ..models import KnowledgeUnit, SourceSection
from ..storage.db import atomic_transaction
from ..storage.file_store import FileStore
from ..storage.repositories import (
    CourseRepository,
    KnowledgeRepository,
    SourceRepository,
    TopicRepository,
)
from .extractors import ExtractedSection, get_extractor
from .processing import snapshot_configuration, processing_identity
from .unit_builder import build_unit_from_dict, parse_structured_unit_blocks


class IngestionPipeline:
    def __init__(self, con: sqlite3.Connection, file_store: FileStore):
        self.con = con
        self.file_store = file_store
        self.course_repo = CourseRepository(con)
        self.source_repo = SourceRepository(con)
        self.topic_repo = TopicRepository(con)
        self.knowledge_repo = KnowledgeRepository(con)

    def stage_ingestion(self, course_id, file_path, logical_name=None):
        if self.con.in_transaction:
            raise ValidationError("Ingestion preparation requires no active transaction.")
        if not self.course_repo.get_course(course_id):
            raise CourseNotFoundError(course_id)
        path = Path(file_path).resolve()
        staged, digest, size, mime = self.file_store.stage_file(path, original_filename=path.name)
        return dict(course_id=course_id, orig_filename=path.name, log_name=logical_name or path.name,
                    staged_path=staged, file_hash=digest, byte_size=size, mime_type=mime)

    def resolve_role(self, prep, role):
        if role is not None:
            return role
        source = self.source_repo.get_source(prep["course_id"], prep["log_name"])
        return source.role if source else "reference"

    def configuration(self, course_id, role, catalog_questions, structured_units, topic_slugs):
        mapping = {}
        for slug in topic_slugs or []:
            topic = self.topic_repo.get_topic_by_slug(course_id, slug)
            mapping[slug] = topic.id if topic else None
        return snapshot_configuration(role, catalog_questions, structured_units, topic_slugs, mapping)

    def validate_preparation(self, prep, configuration):
        if not self.course_repo.get_course(prep["course_id"]):
            raise CourseNotFoundError(prep["course_id"])
        source = self.source_repo.get_source(prep["course_id"], prep["log_name"])
        if source and source.role != configuration["role"]:
            raise ValidationError("Existing logical source has a different role.")
        current = self.configuration(prep["course_id"], configuration["role"],
            configuration["catalog_questions"], configuration["structured_units"], configuration["topic_slugs"])
        if current != configuration:
            raise ConflictError("Topic resolution changed during ingestion; retry preparation.")

    def reusable_version(self, prep, identity):
        if not identity.reuse_eligible:
            return None
        return self.source_repo.find_reusable_version(prep["course_id"], prep["log_name"],
                                                       prep["file_hash"], identity.fingerprint)

    def prepare_staged_ingestion(self, prep, configuration):
        if self.con.in_transaction:
            raise ValidationError("Extraction requires no active transaction.")
        try:
            self.validate_preparation(prep, configuration)
            extractor = get_extractor(prep["staged_path"])
            identity = processing_identity(prep["staged_path"], configuration, extractor)
            prep.update(configuration=configuration, processing_identity=identity)
            if self.reusable_version(prep, identity):
                prep.update(sections=None, extraction_status=None, status_notes="", limitations=[])
                return prep
            sections = extractor.extract(prep["staged_path"])
            quality_flags = {sec.quality_flag for sec in sections}
            limitations = [sec.notes for sec in sections if sec.notes]

            if "unsupported" in quality_flags:
                extraction_status = "unsupported"
                status_notes = "; ".join(limitations)
            elif quality_flags & {"uncertain_scanned", "has_images", "uncertain_math"}:
                extraction_status = "uncertain"
                status_notes = "; ".join(limitations) or "Contains scanned pages with uncertain or missing text layer."
            elif not sections or quality_flags == {"empty"}:
                extraction_status = "empty"
                status_notes = "No extractable text found."
            else:
                extraction_status = "extracted"
                status_notes = ""

            prep.update(sections=sections, extraction_status=extraction_status,
                        status_notes=status_notes, limitations=limitations)
            return prep
        except BaseException:
            prep["staged_path"].unlink(missing_ok=True)
            raise

    def prepare_ingestion(self, course_id, file_path, logical_name=None):
        """Compatibility preparation with default ingestion configuration."""
        prep = self.stage_ingestion(course_id, file_path, logical_name)
        return self.prepare_staged_ingestion(prep, self.configuration(course_id, "reference", True, None, None))

    def commit_prepared_ingestion(
        self,
        course_id: str,
        log_name: str,
        role: str,
        orig_filename: str,
        stored: Any,
        sections: List[ExtractedSection],
        extraction_status: str,
        status_notes: str,
        limitations: List[str],
        topic_slugs: Optional[List[str]] = None,
        structured_units: Optional[List[Dict[str, Any]]] = None,
        catalog_questions: bool = True,
        preparation=None,
    ) -> Dict[str, Any]:
        """Commit prepared ingestion results into the database inside a fast atomic transaction."""
        with atomic_transaction(self.con):
            if preparation is not None:
                configuration = preparation["configuration"]
                self.validate_preparation(preparation, configuration)
                identity = preparation["processing_identity"]
                role = configuration["role"]
                catalog_questions = configuration["catalog_questions"]
                structured_units = configuration["structured_units"]
                topic_slugs = configuration["topic_slugs"]
                existing_ver = self.reusable_version(preparation, identity)
            else:
                identity = None
                existing_ver = None
            source = self.source_repo.get_or_create_source(course_id, log_name, role=role)
            if source.role != role:
                raise ValidationError("Existing logical source has a different role.")
            if existing_ver:
                count = self.con.execute("SELECT COUNT(DISTINCT unit_id) FROM unit_provenance WHERE source_version_id=?", (existing_ver.id,)).fetchone()[0]
                return {
                    "status": "existing_content_reused", "source_id": source.id,
                    "source_version_id": existing_ver.id, "version_num": existing_ver.version_num,
                    "file_hash": stored.file_hash, "units_count": count,
                    "extraction_status": existing_ver.extraction_status,
                    "limitations": [existing_ver.extraction_notes] if existing_ver.extraction_notes else [],
                    "processing_fingerprint": identity.fingerprint,
                    "processing_descriptor": identity.descriptor,
                }
            if sections is None:
                raise ConflictError("Speculative reuse changed; retry preparation outside the transaction.")
            explicit_ids = set()
            for unit in structured_units or []:
                unit_id = unit.get("id")
                if unit_id and (unit_id in explicit_ids or self.knowledge_repo.get_unit(unit_id)):
                    raise ValidationError("Structured unit ID already exists; supply a fresh ID.")
                if unit_id:
                    explicit_ids.add(unit_id)

            # Create new version record (F06: new version on different bytes or new source)
            source_version = self.source_repo.add_source_version(
                source_id=source.id,
                course_id=course_id,
                file_hash=stored.file_hash,
                original_filename=orig_filename,
                mime_type=stored.mime_type,
                byte_size=stored.byte_size,
                storage_relpath=stored.storage_relpath,
                extraction_status=extraction_status,
                extraction_notes=status_notes,
            )

            # Persist raw extracted sections with locators for complete traceability
            for idx, sec in enumerate(sections):
                source_sec = SourceSection(
                    id=str(uuid.uuid4()),
                    source_version_id=source_version.id,
                    course_id=course_id,
                    section_index=idx,
                    label=sec.label,
                    text=sec.text,
                    quality_flag=sec.quality_flag,
                    notes=sec.notes,
                    metadata=sec.metadata,
                )
                self.source_repo.add_source_section(source_sec)

            # Map / resolve topics
            topic_ids: List[str] = []
            if topic_slugs:
                for slug in topic_slugs:
                    t = self.topic_repo.get_topic_by_slug(course_id, slug)
                    if t:
                        topic_ids.append(t.id)

            # Create semantic knowledge units
            created_units: List[KnowledgeUnit] = []

            if structured_units:
                for u_dict in structured_units:
                    ku, prov = build_unit_from_dict(u_dict, course_id, source_version.id)
                    self.knowledge_repo.create_unit(ku, [prov], topic_ids)
                    created_units.append(ku)
            else:
                for sec in sections:
                    parsed = parse_structured_unit_blocks(
                        text=sec.text,
                        course_id=course_id,
                        source_version_id=source_version.id,
                        page_index=sec.metadata.get("page_index"),
                        page_label=sec.label,
                        slide_index=sec.metadata.get("slide_index"),
                    )
                    for ku, prov in parsed:
                        self.knowledge_repo.create_unit(ku, [prov], topic_ids)
                        created_units.append(ku)

            if identity is not None:
                self.source_repo.record_source_processing(course_id, source_version.id, identity)

            question_catalog = None
            if catalog_questions and role in {"exam", "past_exam"}:
                from ..questions.catalog import QuestionCatalog
                question_catalog = QuestionCatalog(self.con).catalog(course_id, source_version.id)

        return {
            "status": "success",
            "source_id": source.id,
            "source_version_id": source_version.id,
            "version_num": source_version.version_num,
            "file_hash": stored.file_hash,
            "storage_relpath": stored.storage_relpath,
            "units_created_count": len(created_units),
            "units": [u.to_dict() for u in created_units],
            "units_created": [u.to_dict() for u in created_units],
            "sections_extracted": len(sections),
            "extraction_status": extraction_status,
            "limitations": limitations,
            "question_catalog": question_catalog,
            "processing_fingerprint": identity.fingerprint if identity else None,
            "processing_descriptor": identity.descriptor if identity else None,
        }

    def ingest_file(
        self,
        course_id: str,
        file_path: Union[str, Path],
        logical_name: Optional[str] = None,
        role: Optional[str] = None,
        structured_units: Optional[List[Dict[str, Any]]] = None,
        topic_slugs: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Ingest a file into course: stages bytes, extracts units outside DB, then commits atomically."""
        prep = self.stage_ingestion(course_id, file_path, logical_name)
        staged_path = prep["staged_path"]
        try:
            role = self.resolve_role(prep, role)
            config = self.configuration(course_id, role, True, structured_units, topic_slugs)
            self.prepare_staged_ingestion(prep, config)
            stored = self.file_store.publish_staged(
                staged_path=staged_path,
                file_hash=prep["file_hash"],
                original_filename=prep["orig_filename"],
            )
            return self.commit_prepared_ingestion(
                course_id=course_id,
                log_name=prep["log_name"],
                role=role,
                orig_filename=prep["orig_filename"],
                stored=stored,
                sections=prep["sections"],
                extraction_status=prep["extraction_status"],
                status_notes=prep["status_notes"],
                limitations=prep["limitations"],
                topic_slugs=topic_slugs,
                structured_units=structured_units,
                preparation=prep,
            )
        finally:
            if staged_path.exists():
                staged_path.unlink(missing_ok=True)

    def enrich_source_version(
        self,
        source_version_id: str,
        structured_units: List[Dict[str, Any]],
        publish: bool = True,
        topic_slugs: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Allows an agent or user to enrich raw extractions into structured knowledge units.
        
        Units created through enrichment can be set directly to 'published' (default)
        or left as 'pending_review' if review is required.
        """
        if type(publish) is not bool:
            from ..errors import ValidationError
            raise ValidationError("publish must be a boolean.")
        ver = self.source_repo.get_source_version(source_version_id)
        if not ver:
            raise ValueError(f"Source version not found: {source_version_id}")
        course_id = ver.course_id

        with atomic_transaction(self.con):
            topic_ids: List[str] = []
            if topic_slugs:
                for slug in topic_slugs:
                    t = self.topic_repo.get_topic_by_slug(course_id, slug)
                    if t:
                        topic_ids.append(t.id)

            created_units: List[KnowledgeUnit] = []
            for u_dict in structured_units:
                u_dict_copy = dict(u_dict)
                if not publish:
                    u_dict_copy["status"] = "pending_review"
                elif "status" not in u_dict_copy:
                    u_dict_copy["status"] = "published"
                ku, prov = build_unit_from_dict(u_dict_copy, course_id, source_version_id)
                self.knowledge_repo.create_unit(ku, [prov], topic_ids)
                created_units.append(ku)

            return {
                "status": "success",
                "source_version_id": source_version_id,
                "course_id": course_id,
                "units_created_count": len(created_units),
                "units": [u.to_dict() for u in created_units],
            }

    def get_extracted_sections(self, source_version_id: str) -> List[Dict[str, Any]]:
        """Retrieve raw persisted extracted sections for a source version."""
        sections = self.source_repo.list_source_sections(source_version_id)
        return [s.to_dict() for s in sections]
