"""Full knowledge unit reading and source region inspection with integrity checks."""

import sqlite3
from typing import Any, Dict, List, Optional

from ..errors import CrossCourseViolationError, SourceNotFoundError, ValidationError
from ..storage.file_store import FileStore
from ..storage.repositories import KnowledgeRepository, SourceRepository
from .expansion import expand_unit_dependencies


def read_units(
    con: sqlite3.Connection,
    course_id: str,
    unit_ids: List[str],
    expand_dependencies: bool = False,
) -> Dict[str, Any]:
    """Retrieve complete knowledge units with exact assumptions, symbols, exceptions, and provenance.

    When expand_dependencies is True, automatically resolves and includes all prerequisite units.
    """
    repo = KnowledgeRepository(con)
    src_repo = SourceRepository(con)

    if expand_dependencies:
        closure = expand_unit_dependencies(con, course_id, unit_ids)
        all_units = closure
        unresolved_deps = closure.unresolved_dependencies
        missing_roots = closure.missing_roots
        closure_complete = closure.closure_complete
    else:
        unresolved_deps = []
        missing_roots = []
        all_units = {}
        for uid in unit_ids:
            u = repo.get_unit(uid)
            if not u:
                matching = [u for u in repo.list_units(course_id) if u.title.strip().lower() == uid.strip().lower()]
                if len(matching) > 1:
                    raise ValidationError(f"Ambiguous unit title '{uid}'; use an exact unit ID.")
                if matching:
                    u = matching[0]
                else:
                    foreign = [u for u in repo.find_units_by_title(uid) if u.course_id != course_id]
                    if foreign:
                        raise CrossCourseViolationError("KnowledgeUnit", foreign[0].id, course_id, foreign[0].course_id)
                    missing_roots.append(uid)
            if u:
                if u.course_id != course_id:
                    raise CrossCourseViolationError("KnowledgeUnit", uid, course_id, u.course_id)
                all_units[u.id] = u
        closure_complete = len(missing_roots) == 0

    formatted_units = []
    for u in all_units.values():
        prov_list = repo.get_provenance(u.id)
        provenance_details = []
        uncertainties = []
        for p in prov_list:
            s_ver = src_repo.get_source_version(p.source_version_id)
            if s_ver and s_ver.extraction_status != "extracted":
                uncertainties.append({
                    "source_version_id": s_ver.id,
                    "extraction_status": s_ver.extraction_status,
                    "extraction_notes": s_ver.extraction_notes,
                })
            provenance_details.append({
                "source_version_id": p.source_version_id,
                "original_filename": s_ver.original_filename if s_ver else None,
                "version_num": s_ver.version_num if s_ver else None,
                "page_index": p.page_index,
                "page_label": p.page_label,
                "slide_index": p.slide_index,
                "region_box": p.region_box,
                "origin_type": p.origin_type,
            })

        formatted_units.append({
            "id": u.id,
            "kind": u.kind,
            "title": u.title,
            "status": u.status,
            "is_pending_review": u.status == "pending_review",
            "content": u.content,
            "summary": u.summary,
            "assumptions": u.assumptions,
            "symbol_definitions": u.symbol_definitions,
            "exceptions": u.exceptions,
            "dependencies": u.dependencies,
            "provenance": provenance_details,
            "uncertainty_flags": uncertainties,
            "revision": u.revision,
        })

    return {
        "course_id": course_id,
        "requested_ids": unit_ids,
        "units": formatted_units,
        "total_units_returned": len(formatted_units),
        "expansion_requested": expand_dependencies,
        "closure_complete": closure_complete,
        "dependencies_expanded": expand_dependencies and closure_complete,
        "unresolved_dependencies": unresolved_deps,
        "missing_roots": missing_roots,
        "has_pending_review_units": any(u["status"] == "pending_review" for u in formatted_units),
        "pending_review_unit_ids": [u["id"] for u in formatted_units if u["status"] == "pending_review"],
    }


def read_source_region(
    con: sqlite3.Connection,
    file_store: FileStore,
    source_version_id: str,
    page_index: Optional[int] = None,
    slide_index: Optional[int] = None,
) -> Dict[str, Any]:
    """Inspect the original source version and locator, verifying physical file integrity."""
    src_repo = SourceRepository(con)
    s_ver = src_repo.get_source_version(source_version_id)
    if not s_ver:
        raise SourceNotFoundError(source_version_id)

    # Verify physical file hash integrity (F24)
    file_exists = False
    hash_verified = False
    abs_path = None
    try:
        candidate = file_store.get_absolute_path(s_ver.storage_relpath)
        file_exists = candidate.is_file()
        abs_path = candidate if file_exists else None
        hash_verified = file_store.verify_file_hash(s_ver.storage_relpath, s_ver.file_hash)
    except Exception:
        hash_verified = False

    return {
        "source_version_id": s_ver.id,
        "source_id": s_ver.source_id,
        "course_id": s_ver.course_id,
        "version_num": s_ver.version_num,
        "original_filename": s_ver.original_filename,
        "mime_type": s_ver.mime_type,
        "byte_size": s_ver.byte_size,
        "storage_relpath": s_ver.storage_relpath,
        "absolute_path": str(abs_path) if abs_path else None,
        "file_exists": file_exists,
        "hash_verified": hash_verified,
        "extraction_status": s_ver.extraction_status,
        "extraction_notes": s_ver.extraction_notes,
        "requested_page_index": page_index,
        "requested_slide_index": slide_index,
    }
