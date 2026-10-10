"""Unified high-level API facade for Lumen core operations with idempotency and transactional guarantees."""

import json
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional, Union
import uuid

from .assessment.brief import get_course_brief
from .assessment.diagnostic import DiagnosticService
from .backup.backup import backup_workspace
from .backup.restore import restore_workspace
from .capabilities import check_capabilities
from .errors import CourseNotFoundError, LumenError, ValidationError, WorkspaceDetachedError
from .ingestion.pipeline import IngestionPipeline
from .learning.service import LearningService
from .models import (
    Course,
    Exercise,
    ExerciseVersion,
    OperationReceipt,
    Topic,
    compute_canonical_hash,
    utc_now_iso,
    validate_all_finite_numbers,
)
from .retrieval.read import read_source_region, read_units
from .retrieval.search import SearchService
from .storage.db import atomic_transaction, get_connection
from .storage.file_store import FileStore
from .storage.migrations import repair_legacy_duplicate_links, run_migrations
from .storage.repositories import (
    AssessmentRepository,
    AttemptRepository,
    CourseRepository,
    EvidenceRepository,
    ExerciseRepository,
    KnowledgeRepository,
    ReceiptRepository,
    TopicRepository,
)
from .storage.sync import WorkspaceSync


class LumenCore:
    """Core controller for Lumen course tutor workspace."""

    def __init__(self, workspace_path: Union[str, Path]):
        self.workspace_root = Path(workspace_path).resolve()
        self.db_path = self.workspace_root / "lumen.db"
        self.sync: Optional[WorkspaceSync] = None
        self.con: Optional[sqlite3.Connection] = None

        try:
            # Shared synchronization lock for this workspace session (Defect 6)
            self.sync = WorkspaceSync(self.workspace_root)
            self.sync.acquire_shared()

            self.workspace_root.mkdir(parents=True, exist_ok=True)

            # Initialize connection and ensure migrations are applied
            self.con = get_connection(self.db_path)
            run_migrations(self.con)

            stat = self.db_path.stat()
            self._expected_db_inode = (stat.st_dev, stat.st_ino)

            self.file_store = FileStore(self.workspace_root)
            self.receipt_repo = ReceiptRepository(self.con)
            self.course_repo = CourseRepository(self.con)
            self.topic_repo = TopicRepository(self.con)
            self.knowledge_repo = KnowledgeRepository(self.con)
            self.exercise_repo = ExerciseRepository(self.con)
            self.evidence_repo = EvidenceRepository(self.con)
            self.assessment_repo = AssessmentRepository(self.con)
            self.attempt_repo = AttemptRepository(self.con)
            self.ingestion = IngestionPipeline(self.con, self.file_store)
            self.search_service = SearchService(self.con)
            self.learning_service = LearningService(self.con)
            self.diagnostic_service = DiagnosticService(self.con)
        except Exception:
            # Release every acquired resource if any initialization stage fails (Defect 6)
            if self.con is not None:
                try:
                    self.con.close()
                except Exception:
                    pass
                self.con = None
            if self.sync is not None:
                try:
                    self.sync.release()
                except Exception:
                    pass
                self.sync = None
            raise

    def close(self):
        con = getattr(self, "con", None)
        if con is not None:
            try:
                con.close()
            except Exception:
                pass
            self.con = None

        sync = getattr(self, "sync", None)
        if sync is not None:
            try:
                sync.release()
            except Exception:
                pass
            self.sync = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _verify_not_detached(self) -> None:
        """Detect detached or replaced database handles (Defect 7)."""
        if not self.db_path.exists():
            raise WorkspaceDetachedError(
                str(self.workspace_root),
                f"Database file '{self.db_path}' no longer exists; workspace handle is detached.",
            )
        stat = self.db_path.stat()
        if (stat.st_dev, stat.st_ino) != self._expected_db_inode:
            raise WorkspaceDetachedError(
                str(self.workspace_root),
                f"Database file inode has changed from {self._expected_db_inode} to {(stat.st_dev, stat.st_ino)}; handle is detached.",
            )

    def _execute_idempotent(
        self,
        request_id: Optional[str],
        operation_name: str,
        course_id: Optional[str],
        params: Dict[str, Any],
        func,
    ) -> Dict[str, Any]:
        """Wrap mutating operations with request hashing and idempotency receipts (F15, F16)."""
        self._verify_not_detached()
        validate_all_finite_numbers(params, "parameters")
        if not request_id:
            # Non-idempotent direct execution
            data = func()
            try:
                json.dumps(data, allow_nan=False)
            except (ValueError, TypeError) as e:
                raise ValidationError(f"Response serialization failed (non-finite or non-serializable value): {e}")
            return {"status": "success", "data": data}

        intent = {
            "operation": operation_name,
            "course_id": course_id,
            "params": params,
        }
        canon_hash = compute_canonical_hash(intent)

        # Check idempotency outside transaction
        prior_receipt = self.receipt_repo.check_idempotency(request_id, canon_hash)
        if prior_receipt:
            return {
                "status": "success",
                "idempotent_replay": True,
                "receipt": prior_receipt.to_dict(),
                "data": prior_receipt.response_data,
            }

        # Atomically commit mutation and receipt in the same database transaction
        with atomic_transaction(self.con):
            self._verify_not_detached()
            # Recheck idempotency inside write transaction in case of concurrent retries
            prior_receipt = self.receipt_repo.check_idempotency(request_id, canon_hash)
            if prior_receipt:
                return {
                    "status": "success",
                    "idempotent_replay": True,
                    "receipt": prior_receipt.to_dict(),
                    "data": prior_receipt.response_data,
                }

            data = func()
            # Test response serialization before committing transaction or recording receipt
            try:
                json.dumps(data, allow_nan=False)
            except (ValueError, TypeError) as e:
                raise ValidationError(f"Response serialization failed (non-finite or non-serializable value): {e}")

            affected_ids = []
            if isinstance(data, dict):
                for k in ("course_id", "source_version_id", "attempt_id", "evidence_id", "assessment_id"):
                    if k in data and data[k]:
                        affected_ids.append(str(data[k]))

            cid = course_id or (data.get("course_id") if isinstance(data, dict) else None)
            receipt = OperationReceipt(
                request_id=request_id,
                course_id=cid,
                canonical_request_hash=canon_hash,
                operation_name=operation_name,
                affected_ids=affected_ids,
                response_data=data if isinstance(data, dict) else {"result": data},
            )
            self.receipt_repo.record_receipt(receipt)

        return {
            "status": "success",
            "receipt": receipt.to_dict(),
            "data": data,
        }

    # 1. Capabilities
    def capabilities(self) -> Dict[str, Any]:
        return check_capabilities(self.workspace_root)

    # 2. Courses
    def create_course(
        self,
        name: str,
        course_id: Optional[str] = None,
        scope: str = "",
        default_language: str = "en",
        notation_settings: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        params = {
            "name": name,
            "course_id": course_id,
            "scope": scope,
            "default_language": default_language,
            "notation_settings": notation_settings or {},
        }

        def _do():
            cid = course_id or str(uuid.uuid4())
            course = Course(
                id=cid,
                name=name,
                scope=scope,
                default_language=default_language,
                notation_settings=notation_settings or {},
            )
            self.course_repo.create_course(course)
            return course.to_dict()

        return self._execute_idempotent(request_id, "create_course", course_id, params, _do)

    # 3. Source Ingestion
    def ingest_source(
        self,
        course_id: str,
        file_path: Union[str, Path],
        logical_name: Optional[str] = None,
        role: str = "reference",
        structured_units: Optional[List[Dict[str, Any]]] = None,
        topic_slugs: Optional[List[str]] = None,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        # Phase 1: Immutable input preparation, staging, and extraction OUTSIDE write transactions
        prep = self.ingestion.prepare_ingestion(
            course_id=course_id,
            file_path=file_path,
            logical_name=logical_name,
        )
        staged_path = prep["staged_path"]
        file_sha256 = prep["file_hash"]

        params = {
            "course_id": course_id,
            "file_sha256": file_sha256,
            "logical_name": prep["log_name"],
            "role": role,
            "structured_units": structured_units or [],
            "topic_slugs": sorted(topic_slugs or []),
        }
        canon_hash = compute_canonical_hash(params)

        # Check idempotency outside transaction
        if request_id:
            prior_receipt = self.receipt_repo.check_idempotency(request_id, canon_hash)
            if prior_receipt:
                staged_path.unlink(missing_ok=True)
                return {
                    "status": "success",
                    "idempotent_replay": True,
                    "receipt": prior_receipt.to_dict(),
                    "data": prior_receipt.response_data,
                }

        # Phase 2: Short atomic commit phase persisting prepared results and receipt
        try:
            with atomic_transaction(self.con):
                # Recheck idempotency inside write transaction in case of simultaneous requests
                if request_id:
                    prior_receipt = self.receipt_repo.check_idempotency(request_id, canon_hash)
                    if prior_receipt:
                        staged_path.unlink(missing_ok=True)
                        return {
                            "status": "success",
                            "idempotent_replay": True,
                            "receipt": prior_receipt.to_dict(),
                            "data": prior_receipt.response_data,
                        }

                # Publish staged file to immutable store
                stored = self.file_store.publish_staged(
                    staged_path=staged_path,
                    file_hash=file_sha256,
                    original_filename=prep["orig_filename"],
                )

                data = self.ingestion.commit_prepared_ingestion(
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
                )

                receipt = None
                if request_id:
                    affected_ids = [str(data.get("source_version_id") or data.get("source_id") or "")]
                    receipt = OperationReceipt(
                        request_id=request_id,
                        course_id=course_id,
                        canonical_request_hash=canon_hash,
                        operation_name="ingest_source",
                        affected_ids=[a for a in affected_ids if a],
                        response_data=data if isinstance(data, dict) else {"result": data},
                    )
                    self.receipt_repo.record_receipt(receipt)

            res = {"status": "success", "data": data}
            if receipt:
                res["receipt"] = receipt.to_dict()
            return res
        finally:
            if staged_path.exists():
                staged_path.unlink(missing_ok=True)

    def get_extracted_sections(self, source_version_id: str) -> List[Dict[str, Any]]:
        return self.ingestion.get_extracted_sections(source_version_id)

    def enrich_source_version(
        self,
        source_version_id: str,
        structured_units: List[Dict[str, Any]],
        publish: bool = True,
        topic_slugs: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        return self.ingestion.enrich_source_version(
            source_version_id=source_version_id,
            structured_units=structured_units,
            publish=publish,
            topic_slugs=topic_slugs,
        )

    # 4. Course Brief
    def course_brief(self, course_id: str, learner_id: str = "default_learner") -> Dict[str, Any]:
        return get_course_brief(self.con, course_id, learner_id=learner_id)

    # 5. Search & Retrieval
    def search(
        self,
        course_id: str,
        query: str,
        topic_id: Optional[str] = None,
        source_id: Optional[str] = None,
        limit: int = 10,
    ) -> Dict[str, Any]:
        results = self.search_service.search(
            course_id=course_id,
            query=query,
            topic_id=topic_id,
            source_id=source_id,
            limit=limit,
        )
        return {
            "course_id": course_id,
            "query": query,
            "results_count": len(results),
            "results": results,
        }

    def read_units(
        self,
        course_id: str,
        unit_ids: List[str],
        expand_dependencies: bool = False,
    ) -> Dict[str, Any]:
        return read_units(self.con, course_id, unit_ids, expand_dependencies=expand_dependencies)

    def read_source_region(
        self,
        source_version_id: str,
        page_index: Optional[int] = None,
        slide_index: Optional[int] = None,
    ) -> Dict[str, Any]:
        return read_source_region(self.con, self.file_store, source_version_id, page_index, slide_index)

    # 6. Topics and Aliases
    def create_topic(
        self,
        course_id: str,
        name: str,
        slug: Optional[str] = None,
        parent_topic_id: Optional[str] = None,
        description: str = "",
    ) -> Dict[str, Any]:
        tid = str(uuid.uuid4())
        tslug = slug or name.lower().replace(" ", "-")
        topic = Topic(
            id=tid,
            course_id=course_id,
            name=name,
            slug=tslug,
            parent_topic_id=parent_topic_id,
            description=description,
        )
        self.topic_repo.create_topic(topic)
        return topic.to_dict()

    def add_topic_alias(self, course_id: str, topic_id: str, alias: str, language: str = "en") -> Dict[str, Any]:
        a = self.topic_repo.add_alias(course_id, topic_id, alias, language)
        return a.to_dict()

    def add_topic_link(self, course_id: str, from_id: str, to_id: str, rel_type: str = "prerequisite") -> Dict[str, Any]:
        link = self.topic_repo.add_topic_link(course_id, from_id, to_id, rel_type)
        return link.to_dict()

    # 7. Exercises
    def create_exercise(
        self,
        course_id: str,
        exercise_family: str,
        question_text: str,
        subparts: Optional[List[Dict[str, Any]]] = None,
        topic_mappings: Optional[List[str]] = None,
        skill_mappings: Optional[List[str]] = None,
        reference_solution: str = "",
        rubric: Optional[Dict[str, Any]] = None,
        validation_state: str = "pending_review",
        external_ref: str = "",
    ) -> Dict[str, Any]:
        ex_id = str(uuid.uuid4())
        exercise = Exercise(
            id=ex_id,
            course_id=course_id,
            exercise_family=exercise_family,
            external_ref=external_ref,
        )
        self.exercise_repo.create_exercise(exercise)

        # New questions always default to pending_review.
        # Do not accept "validated" merely because caller supplied that string;
        # validation must be an explicit transition backed by recorded checks.
        actual_validation_state = "pending_review" if validation_state == "validated" else validation_state

        ver_id = str(uuid.uuid4())
        ex_ver = ExerciseVersion(
            id=ver_id,
            exercise_id=ex_id,
            course_id=course_id,
            version_num=1,
            question_text=question_text,
            subparts=subparts or [],
            topic_mappings=topic_mappings or [],
            skill_mappings=skill_mappings or [],
            reference_solution=reference_solution,
            rubric=rubric or {},
            validation_state=actual_validation_state,
        )
        self.exercise_repo.create_exercise_version(ex_ver)

        return {
            "exercise_id": ex_id,
            "exercise_version_id": ver_id,
            "version_num": 1,
            "validation_state": actual_validation_state,
            "topic_mappings": topic_mappings or [],
            "skill_mappings": skill_mappings or [],
        }

    # 8. Attempts & Learning
    def start_attempt(
        self,
        course_id: str,
        exercise_version_id: str,
        learner_id: str = "default_learner",
        mode: str = "practice",
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        params = {
            "course_id": course_id,
            "exercise_version_id": exercise_version_id,
            "learner_id": learner_id,
            "mode": mode,
        }

        def _do():
            att = self.learning_service.start_attempt(
                course_id=course_id,
                exercise_version_id=exercise_version_id,
                learner_id=learner_id,
                mode=mode,
            )
            return att.to_dict()

        return self._execute_idempotent(request_id, "start_attempt", course_id, params, _do)

    def record_attempt_event(
        self,
        attempt_id: str,
        expected_revision: int,
        event_type: str,
        subpart_key: Optional[str] = None,
        content: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        params = {
            "attempt_id": attempt_id,
            "expected_revision": expected_revision,
            "event_type": event_type,
            "subpart_key": subpart_key,
            "content": content,
            "metadata": metadata or {},
        }

        def _do():
            ev, next_rev = self.learning_service.record_attempt_event(
                attempt_id=attempt_id,
                expected_revision=expected_revision,
                event_type=event_type,
                subpart_key=subpart_key,
                content=content,
                metadata=metadata,
            )
            return {
                "event": ev.to_dict(),
                "next_revision": next_rev,
            }

        return self._execute_idempotent(request_id, "record_attempt_event", None, params, _do)

    def pause_attempt(
        self,
        attempt_id: str,
        expected_revision: int,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        params = {"attempt_id": attempt_id, "expected_revision": expected_revision}

        def _do():
            att = self.learning_service.pause_attempt(attempt_id, expected_revision)
            return att.to_dict()

        return self._execute_idempotent(request_id, "pause_attempt", None, params, _do)

    def resume_attempt(
        self,
        attempt_id: str,
        expected_revision: int,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        params = {"attempt_id": attempt_id, "expected_revision": expected_revision}

        def _do():
            att = self.learning_service.resume_attempt(attempt_id, expected_revision)
            return att.to_dict()

        return self._execute_idempotent(request_id, "resume_attempt", None, params, _do)

    def commit_evidence(
        self,
        attempt_id: str,
        evaluations: List[Dict[str, Any]],
        complete_attempt: bool = False,
        submission_event_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        params = {
            "attempt_id": attempt_id,
            "evaluations": evaluations,
            "complete_attempt": complete_attempt,
            "submission_event_id": submission_event_id,
        }

        def _do():
            return self.learning_service.commit_evidence(
                attempt_id, evaluations, complete_attempt, submission_event_id=submission_event_id
            )

        return self._execute_idempotent(request_id, "commit_evidence", None, params, _do)

    def correct_evidence(
        self,
        evidence_id: str,
        correction_reason: str,
        replacement: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        params = {
            "evidence_id": evidence_id,
            "correction_reason": correction_reason,
            "replacement": replacement,
        }

        def _do():
            return self.learning_service.correct_evidence(evidence_id, correction_reason, replacement)

        return self._execute_idempotent(request_id, "correct_evidence", None, params, _do)

    # 9. Diagnostics
    def create_assessment(
        self,
        course_id: str,
        title: str,
        blueprint: Optional[Dict[str, Any]] = None,
        selected_exercise_version_ids: Optional[List[str]] = None,
        learner_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        params = {
            "course_id": course_id,
            "title": title,
            "blueprint": blueprint or {},
            "selected_exercise_version_ids": selected_exercise_version_ids or [],
            "learner_id": learner_id,
        }

        def _do():
            return self.diagnostic_service.create_assessment(
                course_id=course_id,
                title=title,
                blueprint=blueprint,
                selected_exercise_version_ids=selected_exercise_version_ids,
                learner_id=learner_id,
            )

        return self._execute_idempotent(request_id, "create_assessment", course_id, params, _do)

    def validate_exercise_version(
        self,
        version_id: str,
        reviewer: str = "host_agent",
        checks: Optional[Union[Dict[str, Any], List[str]]] = None,
        notes: str = "",
        validation_state: str = "validated",
        reference_solution: Optional[str] = None,
        rubric: Optional[Dict[str, Any]] = None,
        expected_revision: Optional[int] = None,
        expected_question_text: Optional[str] = None,
        expected_reference_solution: Optional[str] = None,
        expected_rubric: Optional[Dict[str, Any]] = None,
        expected_content_hash: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._verify_not_detached()
        ver = self.exercise_repo.validate_exercise_version(
            version_id=version_id,
            reviewer=reviewer,
            checks=checks,
            notes=notes,
            status=validation_state,
            reference_solution=reference_solution,
            rubric=rubric,
            expected_revision=expected_revision,
            expected_question_text=expected_question_text,
            expected_reference_solution=expected_reference_solution,
            expected_rubric=expected_rubric,
            expected_content_hash=expected_content_hash,
        )
        return ver.to_dict()

    def update_exercise_version(
        self,
        version_id: str,
        question_text: Optional[str] = None,
        reference_solution: Optional[str] = None,
        rubric: Optional[Dict[str, Any]] = None,
        expected_revision: Optional[int] = None,
    ) -> Dict[str, Any]:
        self._verify_not_detached()
        with atomic_transaction(self.con):
            ver = self.exercise_repo.update_exercise_version(
                version_id=version_id,
                question_text=question_text,
                reference_solution=reference_solution,
                rubric=rubric,
                expected_revision=expected_revision,
            )
            for t_id in ver.topic_mappings:
                self.evidence_repo.recompute_topic_state(ver.course_id, t_id)
            return ver.to_dict()

    def assessment_progress(self, assessment_id: str) -> Dict[str, Any]:
        self._verify_not_detached()
        return self.diagnostic_service.get_progress(assessment_id)

    def start_assessment_item_attempt(
        self,
        assessment_id: str,
        item_order: int,
        learner_id: str = "default_learner",
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._verify_not_detached()
        if not request_id:
            return self.diagnostic_service.start_assessment_item_attempt(
                assessment_id=assessment_id,
                item_order=item_order,
                learner_id=learner_id,
            )
        params = {
            "assessment_id": assessment_id,
            "item_order": item_order,
            "learner_id": learner_id,
        }

        def _do():
            return self.diagnostic_service.start_assessment_item_attempt(
                assessment_id=assessment_id,
                item_order=item_order,
                learner_id=learner_id,
            )

        return self._execute_idempotent(request_id, "start_assessment_item_attempt", None, params, _do)

    def link_assessment_item_attempt(
        self,
        assessment_id: str,
        item_order: int,
        attempt_id: str,
        learner_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._verify_not_detached()
        if not request_id:
            return self.diagnostic_service.link_assessment_item_attempt(
                assessment_id=assessment_id,
                item_order=item_order,
                attempt_id=attempt_id,
                learner_id=learner_id,
            )
        params = {
            "assessment_id": assessment_id,
            "item_order": item_order,
            "attempt_id": attempt_id,
            "learner_id": learner_id,
        }

        def _do():
            return self.diagnostic_service.link_assessment_item_attempt(
                assessment_id=assessment_id,
                item_order=item_order,
                attempt_id=attempt_id,
                learner_id=learner_id,
            )

        return self._execute_idempotent(request_id, "link_assessment_item_attempt", None, params, _do)

    def record_assessment_item_score(
        self,
        assessment_id: str,
        item_order: int,
        points_awarded: float,
        attempt_id: Optional[str] = None,
        allow_partial: bool = False,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._verify_not_detached()
        if not isinstance(allow_partial, bool):
            raise ValidationError(
                f"allow_partial must be a boolean (True or False), got {type(allow_partial).__name__} ({allow_partial!r})."
            )
        if not request_id:
            return self.diagnostic_service.record_assessment_item_score(
                assessment_id=assessment_id,
                item_order=item_order,
                points_awarded=points_awarded,
                attempt_id=attempt_id,
                allow_partial=allow_partial,
            )
        params = {
            "assessment_id": assessment_id,
            "item_order": item_order,
            "points_awarded": float(points_awarded) if isinstance(points_awarded, (int, float)) and not isinstance(points_awarded, bool) else points_awarded,
            "attempt_id": attempt_id,
            "allow_partial": allow_partial,
        }

        def _do():
            return self.diagnostic_service.record_assessment_item_score(
                assessment_id=assessment_id,
                item_order=item_order,
                points_awarded=points_awarded,
                attempt_id=attempt_id,
                allow_partial=allow_partial,
            )

        return self._execute_idempotent(request_id, "record_assessment_item_score", None, params, _do)

    # 10. Backup and Restore
    def backup(self, output_path: Union[str, Path]) -> Dict[str, Any]:
        return backup_workspace(self.workspace_root, output_path, con=self.con)

    @classmethod
    def restore(
        cls,
        backup_path: Union[str, Path],
        target_workspace: Union[str, Path],
        force: bool = False,
    ) -> Dict[str, Any]:
        return restore_workspace(backup_path, target_workspace, force=force)

    def get_quarantined_legacy_duplicate_links(self) -> List[Dict[str, Any]]:
        """Retrieve audit records for quarantined legacy duplicate attempt links."""
        self._verify_not_detached()
        table_exists = self.con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='legacy_duplicate_attempt_links'"
        ).fetchone()
        if not table_exists:
            return []
        rows = self.con.execute(
            "SELECT * FROM legacy_duplicate_attempt_links ORDER BY quarantined_at ASC"
        ).fetchall()
        return [dict(r) for r in rows]

    def repair_legacy_duplicate_links(
        self,
        resolved_assignments: Optional[Dict[str, str]] = None,
        expected_link_states: Optional[Dict[str, Optional[str]]] = None,
    ) -> Dict[str, Any]:
        """Resolve quarantined legacy duplicate attempt links with explicit assignments."""
        self._verify_not_detached()
        return repair_legacy_duplicate_links(
            self.con,
            resolved_assignments=resolved_assignments,
            expected_link_states=expected_link_states,
        )

