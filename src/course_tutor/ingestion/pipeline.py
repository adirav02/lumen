"""Ingestion pipeline coordinating staging, hashing, format extraction, and unit persistence."""

from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional, Union
import uuid

from ..errors import CourseNotFoundError, WorkspaceError
from ..models import KnowledgeUnit, SourceSection, UnitProvenance
from ..storage.db import atomic_transaction
from ..storage.file_store import FileStore
from ..storage.repositories import (
    CourseRepository,
    KnowledgeRepository,
    SourceRepository,
    TopicRepository,
)
from .extractors import get_extractor
from .unit_builder import build_unit_from_dict, parse_structured_unit_blocks


class IngestionPipeline:
    def __init__(self, con: sqlite3.Connection, file_store: FileStore):
        self.con = con
        self.file_store = file_store
        self.course_repo = CourseRepository(con)
        self.source_repo = SourceRepository(con)
        self.topic_repo = TopicRepository(con)
        self.knowledge_repo = KnowledgeRepository(con)

    def ingest_file(
        self,
        course_id: str,
        file_path: Union[str, Path],
        logical_name: Optional[str] = None,
        role: str = "reference",
        structured_units: Optional[List[Dict[str, Any]]] = None,
        topic_slugs: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Ingest a file into course: stages bytes, creates source version, extracts units.
        
        Extraction and file staging occur outside database transactions to avoid
        holding SQLite transaction locks during long-running I/O or parsing operations.
        """
        course = self.course_repo.get_course(course_id)
        if not course:
            raise CourseNotFoundError(course_id)

        src_path = Path(file_path).resolve()
        if not src_path.is_file():
            raise WorkspaceError(str(src_path), f"File not found: {src_path}")

        orig_filename = src_path.name
        log_name = logical_name or orig_filename

        # 1. Stage and store original file byte-for-byte outside DB transaction
        stored = self.file_store.store_file(src_path, original_filename=orig_filename)

        # 2. Extract content using format extractor outside DB transaction
        extractor = get_extractor(src_path)
        sections = extractor.extract(src_path)

        quality_flags = {sec.quality_flag for sec in sections}
        limitations = [sec.notes for sec in sections if sec.notes]

        # F01: if scanned or uncertain, mark explicit status
        if "uncertain_scanned" in quality_flags:
            extraction_status = "uncertain"
            status_notes = "; ".join(limitations) or "Contains scanned pages with uncertain or missing text layer."
        elif "empty" in quality_flags and len(sections) == 1:
            extraction_status = "empty"
            status_notes = "No extractable text found."
        else:
            extraction_status = "extracted"
            status_notes = ""

        # 3. Fast atomic transaction for database metadata and unit persistence
        with atomic_transaction(self.con):
            # Register logical source
            source = self.source_repo.get_or_create_source(course_id, log_name, role=role)

            # Check for identical content already in course (F05: content identity)
            existing_ver = self.source_repo.find_version_by_hash(course_id, stored.file_hash)
            if existing_ver and existing_ver.source_id == source.id:
                # Same source and exact same content uploaded again: return existing without reprocessing
                return {
                    "status": "existing_content_reused",
                    "source_id": source.id,
                    "source_version_id": existing_ver.id,
                    "version_num": existing_ver.version_num,
                    "file_hash": stored.file_hash,
                    "units_count": len(self.knowledge_repo.list_units(course_id)),
                    "extraction_status": existing_ver.extraction_status,
                    "limitations": [existing_ver.extraction_notes] if existing_ver.extraction_notes else [],
                }

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

        return {
            "status": "success",
            "source_id": source.id,
            "source_version_id": source_version.id,
            "version_num": source_version.version_num,
            "file_hash": stored.file_hash,
            "storage_relpath": stored.storage_relpath,
            "units_created_count": len(created_units),
            "units": [u.to_dict() for u in created_units],
            "sections_extracted": len(sections),
            "extraction_status": extraction_status,
            "limitations": limitations,
        }

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
                if publish and "status" not in u_dict_copy:
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
