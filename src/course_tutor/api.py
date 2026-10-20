"""Unified high-level API facade for Lumen core operations with idempotency and transactional guarantees."""

import json
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional, Union
import uuid

from .assessment.brief import get_course_brief
from .assessment.diagnostic import DiagnosticService
from .assessment.readiness import blueprint_readiness
from .backup.backup import backup_workspace
from .backup.restore import restore_workspace
from .capabilities import check_capabilities
from .errors import CourseNotFoundError, ValidationError, WorkspaceDetachedError
from .ingestion.pipeline import IngestionPipeline
from .learning.service import LearningService
from .learning.practice import propose_practice
from .questions.catalog import QuestionCatalog
from .questions.history import QuestionHistory
from .questions.review import QuestionReview
from .models import (
    Course,
    Exercise,
    ExerciseVersion,
    OperationReceipt,
    Topic,
    compute_canonical_hash,
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
            # A missing retry key must not weaken rollback or serialization guarantees.
            with atomic_transaction(self.con):
                self._verify_not_detached()
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
    def list_courses(self) -> Dict[str, Any]:
        """Discover courses in this workspace without scanning other databases."""
        self._verify_not_detached()
        from .course_layout import course_directory
        courses = []
        for course in self.course_repo.list_courses():
            row = course.to_dict()
            try:
                row['directory'] = str(course_directory(self.con, self.workspace_root, course.id))
            except ValidationError as exc:
                row['directory'] = None
                row['directory_issue'] = str(exc)
            courses.append(row)
        return {"workspace_path": str(self.workspace_root), "courses": courses}

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
    def update_learner_settings(
        self, course_id: str, learner_id: str = "default_learner",
        teaching_preference: Optional[str] = None, chosen_language: Optional[str] = None,
        explicit_goals: Optional[str] = None, request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Persist course-local teaching preferences through the validated core."""
        params = {"learner_id": learner_id, "teaching_preference": teaching_preference,
                  "chosen_language": chosen_language, "explicit_goals": explicit_goals}
        if not isinstance(learner_id, str) or not learner_id.strip():
            raise ValidationError("learner_id must be a non-empty string.")
        for key, value in params.items():
            if value is not None and not isinstance(value, str):
                raise ValidationError(f"{key} must be a string.")
        if chosen_language is not None and not chosen_language.strip():
            raise ValidationError("chosen_language must be non-empty.")

        def _do():
            if not self.course_repo.get_course(course_id):
                raise CourseNotFoundError(course_id)
            settings = self.course_repo.get_or_create_learner_settings(course_id, learner_id)
            for key in ("teaching_preference", "chosen_language", "explicit_goals"):
                if params[key] is not None:
                    setattr(settings, key, params[key])
            return self.course_repo.update_learner_settings(settings).to_dict()

        return self._execute_idempotent(request_id, "update_learner_settings", course_id, params, _do)

    def ingest_source(
        self,
        course_id: str,
        file_path: Union[str, Path],
        logical_name: Optional[str] = None,
        role: Optional[str] = None,
        structured_units: Optional[List[Dict[str, Any]]] = None,
        topic_slugs: Optional[List[str]] = None,
        request_id: Optional[str] = None,
        catalog_questions: bool = True,
    ) -> Dict[str, Any]:
        # Phase 1: Immutable input preparation, staging, and extraction OUTSIDE write transactions
        self._verify_not_detached()
        if type(catalog_questions) is not bool:
            raise ValidationError('catalog_questions must be a boolean.')
        validate_all_finite_numbers({"structured_units": structured_units, "topic_slugs": topic_slugs}, "parameters")
        import copy
        structured_units = copy.deepcopy(structured_units)
        topic_slugs = copy.deepcopy(topic_slugs)
        prep = self.ingestion.stage_ingestion(
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
        if not catalog_questions:
            params['catalog_questions'] = False
        # Phase 2: Short atomic commit phase persisting prepared results and receipt
        try:
            role = self.ingestion.resolve_role(prep, role)
            params["role"] = role
            canon_hash = compute_canonical_hash(params)
            if request_id:
                prior_receipt = self.receipt_repo.check_idempotency(request_id, canon_hash)
                if prior_receipt:
                    return {
                        "status": "success", "idempotent_replay": True,
                        "receipt": prior_receipt.to_dict(), "data": prior_receipt.response_data,
                    }
            configuration = self.ingestion.configuration(course_id, role, catalog_questions, structured_units, topic_slugs)
            self.ingestion.prepare_staged_ingestion(prep, configuration)
            with atomic_transaction(self.con):
                self._verify_not_detached()
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
                    catalog_questions=catalog_questions,
                    structured_units=structured_units,
                    preparation=prep,
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
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        params = {
            "source_version_id": source_version_id,
            "structured_units": structured_units,
            "publish": publish,
            "topic_slugs": topic_slugs,
        }

        def _do():
            self._verify_not_detached()
            validate_all_finite_numbers(structured_units, "structured_units")
            return self.ingestion.enrich_source_version(
                source_version_id=source_version_id,
                structured_units=structured_units,
                publish=publish,
                topic_slugs=topic_slugs,
            )

        result = self._execute_idempotent(request_id, "enrich_source_version", None, params, _do)
        return result if request_id else result["data"]

    # 4. Course Brief
    def course_brief(self, course_id: str, learner_id: str = "default_learner") -> Dict[str, Any]:
        from .course_layout import course_directory, test_directory
        result = get_course_brief(self.con, course_id, learner_id=learner_id)
        rows = self.con.execute('''SELECT id,title,learner_id FROM assessments WHERE course_id=?
            AND (learner_id=? OR learner_id IS NULL) AND status='open'
            ORDER BY created_at DESC,id DESC LIMIT 10''', (course_id, learner_id)).fetchall()
        result['open_assessments'] = []
        if not rows:
            return result  # Keep ordinary tutoring briefs compact.
        try:
            result['course_directory'] = str(course_directory(self.con, self.workspace_root, course_id))
        except ValidationError as exc:
            result['course_directory'] = None
            result['directory_issue'] = str(exc)
        for row in rows:
            entry = {'assessment_id': row['id'], 'title': row['title'], 'learner_id': row['learner_id']}
            if result['course_directory']:
                path = test_directory(self.con, self.workspace_root, course_id, row['id'])/'test.pdf'
                entry.update(pdf_path=str(path), pdf_exists=path.is_file())
            result['open_assessments'].append(entry)
        return result

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
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        params = {
            "course_id": course_id,
            "name": name,
            "slug": slug,
            "parent_topic_id": parent_topic_id,
            "description": description,
        }

        def _do():
            self._verify_not_detached()
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
            with atomic_transaction(self.con):
                self.topic_repo.create_topic(topic)
            return topic.to_dict()

        result = self._execute_idempotent(request_id, "create_topic", course_id, params, _do)
        return result if request_id else result["data"]

    def add_topic_alias(self, course_id: str, topic_id: str, alias: str, language: str = "en", request_id: Optional[str] = None) -> Dict[str, Any]:
        params = {'course_id': course_id, 'topic_id': topic_id, 'alias': alias, 'language': language}

        def _do():
            self._verify_not_detached()
            with atomic_transaction(self.con):
                a = self.topic_repo.add_alias(course_id, topic_id, alias, language)
            return a.to_dict()

        result = self._execute_idempotent(request_id, "add_topic_alias", course_id, params, _do)
        return result if request_id else result["data"]

    def add_topic_link(self, course_id: str, from_id: str, to_id: str, rel_type: str = "prerequisite", request_id: Optional[str] = None) -> Dict[str, Any]:
        params = {'course_id': course_id, 'from_id': from_id, 'to_id': to_id, 'rel_type': rel_type}

        def _do():
            self._verify_not_detached()
            with atomic_transaction(self.con):
                link = self.topic_repo.add_topic_link(course_id, from_id, to_id, rel_type)
            return link.to_dict()

        result = self._execute_idempotent(request_id, "add_topic_link", course_id, params, _do)
        return result if request_id else result["data"]

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
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        params = {
            "course_id": course_id,
            "exercise_family": exercise_family,
            "question_text": question_text,
            "subparts": subparts,
            "topic_mappings": topic_mappings,
            "skill_mappings": skill_mappings,
            "reference_solution": reference_solution,
            "rubric": rubric,
            "validation_state": validation_state,
            "external_ref": external_ref,
        }

        def _do():
            self._verify_not_detached()
            validate_all_finite_numbers({"subparts": subparts, "rubric": rubric}, "parameters")
            ex_id = str(uuid.uuid4())
            exercise = Exercise(
                id=ex_id,
                course_id=course_id,
                exercise_family=exercise_family,
                external_ref=external_ref,
            )

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
            with atomic_transaction(self.con):
                self.exercise_repo.create_exercise(exercise)
                self.exercise_repo.create_exercise_version(ex_ver)

            return {
                "exercise_id": ex_id,
                "exercise_version_id": ver_id,
                "version_num": 1,
                "validation_state": actual_validation_state,
                "topic_mappings": topic_mappings or [],
                "skill_mappings": skill_mappings or [],
            }

        result = self._execute_idempotent(request_id, "create_exercise", course_id, params, _do)
        return result if request_id else result["data"]

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
    def _question_mutation(self, operation, course_id, request_id, params, service, method):
        return self._execute_idempotent(request_id, operation, course_id, params,
            lambda: getattr(service(self.con), method)(course_id=course_id, **params))

    def batch_questions(self, course_id, items, request_id):
        from .questions.batch import batch_questions
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValidationError('batch_questions requires a stable nonempty request_id.')
        return self._execute_idempotent(request_id, 'batch_questions', course_id, {'items': items},
                                        lambda: batch_questions(self.con, course_id, items))

    def catalog_exam_questions(self, course_id, source_version_id, questions=None, exam_label=None, request_id=None):
        return self._question_mutation("catalog_exam_questions", course_id, request_id,
            dict(source_version_id=source_version_id, questions=questions, exam_label=exam_label), QuestionCatalog, "catalog")

    def annotate_question(self, course_id, occurrence_id, expected_revision, metadata, solution_links=None, request_id=None):
        return self._question_mutation('annotate_question', course_id, request_id,
            dict(occurrence_id=occurrence_id, expected_revision=expected_revision, metadata=metadata, solution_links=solution_links), QuestionReview, 'annotate')

    def review_question_visual(self, course_id, occurrence_id, expected_revision, status, notes, checks=None, request_id=None):
        return self._question_mutation('review_question_visual', course_id, request_id,
            dict(occurrence_id=occurrence_id, expected_revision=expected_revision, status=status, notes=notes, checks=checks), QuestionReview, 'review_visual')

    def review_question_occurrence(self, course_id, occurrence_id, expected_revision, status, notes, request_id=None):
        return self._question_mutation("review_question_occurrence", course_id, request_id,
            dict(occurrence_id=occurrence_id, expected_revision=expected_revision, status=status, notes=notes), QuestionCatalog, "review_question")

    def review_exam_catalog(self, course_id, source_version_id, expected_revision, expected_question_count, notes, checks, request_id=None):
        return self._question_mutation("review_exam_catalog", course_id, request_id,
            dict(source_version_id=source_version_id, expected_revision=expected_revision,
                 expected_question_count=expected_question_count, notes=notes, checks=checks), QuestionCatalog, "review_exam")

    def review_question_relation(self, course_id, relation_id, expected_revision, status, notes, request_id=None):
        return self._question_mutation("review_question_relation", course_id, request_id,
            dict(relation_id=relation_id, expected_revision=expected_revision, status=status, notes=notes), QuestionCatalog, "review_relation")

    def list_questions(self, course_id, source_version_id=None, limit=50, after_id=""):
        self._verify_not_detached()
        return QuestionCatalog(self.con).list_questions(course_id, source_version_id, limit, after_id)

    def student_preview(self, course_id, exercise_version_id):
        self._verify_not_detached()
        from .student import student_preview
        return student_preview(self.con, course_id, exercise_version_id)

    def student_search(self, course_id, query, limit=20):
        self._verify_not_detached()
        from .student import student_search
        return student_search(self.con, course_id, query, limit)

    def search_questions(self, course_id, query, limit=20):
        self._verify_not_detached()
        return QuestionCatalog(self.con).search_questions(course_id, query, limit)

    def exam_catalog_status(self, course_id, source_version_id):
        self._verify_not_detached()
        return QuestionCatalog(self.con).exam_status(course_id, source_version_id)

    def lexical_question_overlap(self, course_id, exercise_version_id, threshold=0.45, limit=20):
        self._verify_not_detached()
        return QuestionCatalog(self.con).lexical_overlap(course_id, exercise_version_id, threshold, limit)

    def list_question_relations(self, course_id, exercise_version_id=None, limit=50, after_id=""):
        self._verify_not_detached()
        return QuestionCatalog(self.con).list_relations(course_id, exercise_version_id, limit, after_id)

    def question_history(self, course_id, learner_id, exercise_version_id, limit=20, after_id=""):
        self._verify_not_detached()
        return QuestionHistory(self.con).question_history(course_id, learner_id, exercise_version_id, limit, after_id)

    def attempt_history(self, course_id, learner_id, attempt_id, limit=50, event_after=0, evidence_after=0, grade_after=0):
        self._verify_not_detached()
        return QuestionHistory(self.con).attempt_history(course_id, learner_id, attempt_id, limit, event_after, evidence_after, grade_after)

    def grade_attempt(self, course_id, learner_id, attempt_id, expected_grade_revision, points_awarded,
                      max_points, feedback, evidence_ids, correction_reason="", allow_partial=False, request_id=None):
        return self._question_mutation("grade_attempt", course_id, request_id,
            dict(learner_id=learner_id, attempt_id=attempt_id, expected_grade_revision=expected_grade_revision,
                 points_awarded=points_awarded, max_points=max_points, feedback=feedback, evidence_ids=evidence_ids,
                 correction_reason=correction_reason, allow_partial=allow_partial), QuestionHistory, "grade_attempt")

    def propose_practice(
        self, course_id: str, learner_id: str = "default_learner", count: int = 1,
        topic_ids: Optional[List[str]] = None, exclude_exercise_version_ids: Optional[List[str]] = None,
        allow_repeats: bool = False,
        focus: str = "all",
        source_only: bool = False,
    ) -> Dict[str, Any]:
        self._verify_not_detached()
        return propose_practice(
            self.con, course_id, learner_id, count, topic_ids, exclude_exercise_version_ids, allow_repeats, focus, source_only,
        )

    def blueprint_readiness(self, course_id, blueprint, learner_id="default_learner"):
        self._verify_not_detached()
        return blueprint_readiness(self.con, course_id, blueprint, learner_id)

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
            result = self.diagnostic_service.create_assessment(
                course_id=course_id,
                title=title,
                blueprint=blueprint,
                selected_exercise_version_ids=selected_exercise_version_ids,
                learner_id=learner_id,
            )
            return {**result, "delivery": {
                "default_format": "pdf", "status": "not_exported",
                "next_operation": "export-assessment",
                "note": "Saved selection only. For a test request, export and visually check the PDF before returning its link, unless the learner explicitly requested another format.",
            }}

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
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        params = {
            "version_id": version_id,
            "reviewer": reviewer,
            "checks": checks,
            "notes": notes,
            "validation_state": validation_state,
            "reference_solution": reference_solution,
            "rubric": rubric,
            "expected_revision": expected_revision,
            "expected_question_text": expected_question_text,
            "expected_reference_solution": expected_reference_solution,
            "expected_rubric": expected_rubric,
            "expected_content_hash": expected_content_hash,
        }

        def _do():
            self._verify_not_detached()
            validate_all_finite_numbers({"checks": checks, "rubric": rubric}, "parameters")
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

        result = self._execute_idempotent(request_id, "validate_exercise_version", None, params, _do)
        return result if request_id else result["data"]

    def update_exercise_version(
        self,
        version_id: str,
        question_text: Optional[str] = None,
        reference_solution: Optional[str] = None,
        rubric: Optional[Dict[str, Any]] = None,
        expected_revision: Optional[int] = None,
        request_id: Optional[str] = None,
        subparts: Optional[List[Dict[str, Any]]] = None,
        topic_mappings: Optional[List[str]] = None,
        skill_mappings: Optional[List[str]] = None,
        context_blocks: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        if context_blocks is not None:
            from .questions.batch import compose_question_text
            question_text = compose_question_text(question_text, context_blocks)
        params = {
            "version_id": version_id,
            "question_text": question_text,
            "reference_solution": reference_solution,
            "rubric": rubric,
            "expected_revision": expected_revision,
        }
        for name, value in (("subparts", subparts), ("topic_mappings", topic_mappings), ("skill_mappings", skill_mappings)):
            if value is not None:
                params[name] = value

        def _do():
            self._verify_not_detached()
            validate_all_finite_numbers(rubric, "rubric")
            with atomic_transaction(self.con):
                before = self.exercise_repo.get_exercise_version(version_id)
                ver = self.exercise_repo.update_exercise_version(
                    version_id=version_id,
                    question_text=question_text,
                    reference_solution=reference_solution,
                    rubric=rubric,
                    expected_revision=expected_revision,
                    subparts=subparts, topic_mappings=topic_mappings, skill_mappings=skill_mappings,
                )
                for t_id in ver.topic_mappings:
                    self.evidence_repo.recompute_topic_state(ver.course_id, t_id)
                current_revision = len(ver.revision_history)+1
                changed = before is not None and len(before.revision_history)+1 != current_revision
                return {**ver.to_dict(), 'current_revision': current_revision, 'changed': changed,
                        'revision_note': 'Use current_revision for the next call; no-op updates do not increment revision.'}

        result = self._execute_idempotent(request_id, "update_exercise_version", None, params, _do)
        return result if request_id else result["data"]

    def assessment_progress(self, assessment_id: str) -> Dict[str, Any]:
        self._verify_not_detached()
        return self.diagnostic_service.get_progress(assessment_id)

    def assessment_paper(self, assessment_id: str, course_id: Optional[str] = None) -> Dict[str, Any]:
        self._verify_not_detached()
        from .assessment.paper import assessment_paper
        return assessment_paper(self.con, assessment_id, course_id)

    def assemble_exam(self, course_id: str, learner_id: str, blueprint: dict,
                      seed: int, request_id: str, title: Optional[str] = None) -> Dict[str, Any]:
        from .assessment.assembly import assemble_exam
        return {"status": "success", "data": assemble_exam(
            self, course_id, learner_id, blueprint, seed, request_id, title)}

    def release_reservation(self, course_id: str, learner_id: Optional[str],
                            assessment_id: str, request_id: str,
                            reason: str = "released") -> Dict[str, Any]:
        from .assessment.reservations import release_reservation
        return release_reservation(self, course_id, learner_id, assessment_id, request_id, reason)

    def expire_reservations(self, course_id: str, learner_id: Optional[str],
                            request_id: str) -> Dict[str, Any]:
        from .assessment.reservations import expire_reservations
        return expire_reservations(self, course_id, learner_id, request_id)

    def export_assessment(self, assessment_id: str, course_id: Optional[str] = None,
                          output_directory: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
        from .assessment.export import export_paper
        paper = self.assessment_paper(assessment_id, course_id)
        from .storage.repositories import AssemblyRepository
        job = AssemblyRepository(self.con).get_by_assessment(assessment_id)
        if job is not None:
            from .assessment.assembly import export_saved_assessment
            return export_saved_assessment(self, job, output_directory)
        from .course_layout import test_directory
        destination = output_directory or test_directory(self.con, self.workspace_root, paper['course_id'], paper['assessment_id'])
        return export_paper(paper, destination)

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
        self._verify_not_detached()
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


# Compatibility name for callers using the course-oriented facade contract.
CourseTutor = LumenCore
