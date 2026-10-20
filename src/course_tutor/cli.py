"""Structured JSON Command-Line Interface for Lumen."""

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

from .api import LumenCore
from .errors import LumenError, ValidationError
from .models import validate_all_finite_numbers
from .capabilities import check_capabilities


def _reject_json_constants(c: str) -> Any:
    raise ValueError(f"Non-standard JSON constant rejected: {c}")


def parse_json_payload(raw_json: Optional[str]) -> Dict[str, Any]:
    if raw_json:
        try:
            val = json.loads(raw_json, parse_constant=_reject_json_constants)
        except (json.JSONDecodeError, ValueError) as e:
            raise ValueError(f"Malformed JSON argument: {e}")
        if not isinstance(val, dict):
            raise ValueError(f"JSON input must be an object (dictionary), got {type(val).__name__}.")
        validate_all_finite_numbers(val, "payload")
        return val
    if not sys.stdin.isatty():
        content = sys.stdin.read().strip()
        if content:
            try:
                val = json.loads(content, parse_constant=_reject_json_constants)
            except (json.JSONDecodeError, ValueError) as e:
                raise ValueError(f"Malformed stdin JSON: {e}")
            if not isinstance(val, dict):
                raise ValueError(f"JSON input must be an object (dictionary), got {type(val).__name__}.")
            validate_all_finite_numbers(val, "payload")
            return val
    return {}


def output_json(payload: Dict[str, Any], exit_code: int = 0) -> None:
    try:
        data = json.dumps(payload, ensure_ascii=False, allow_nan=False) + "\n"
    except (ValueError, TypeError) as e:
        err_payload = {
            "status": "error",
            "error_code": "SERIALIZATION_ERROR",
            "message": f"Output contained non-standard JSON values (e.g. NaN/Inf): {e}",
            "details": {},
        }
        data = json.dumps(err_payload, ensure_ascii=False, allow_nan=False) + "\n"
        exit_code = 1
    sys.stdout.write(data)
    sys.stdout.flush()
    sys.exit(exit_code)


def output_operation_result(result: Dict[str, Any]) -> None:
    """Preserve receipt envelopes while wrapping legacy direct API results."""
    output_json(result if "data" in result and "status" in result else {"status": "success", "data": result})


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Lumen - Portable course learning and assessment core")
    parser.add_argument("operation", nargs="?", default="capabilities", help="Operation to execute")
    parser.add_argument("--workspace", "-w", default=".lumen", help="Path to workspace directory")
    parser.add_argument("--json-input", "-j", help="Input parameters as JSON string")
    parser.add_argument("--course-id", "-c", help="Course ID")
    parser.add_argument("--query", "-q", help="Search query")
    parser.add_argument("--request-id", "-r", help="Stable request ID for idempotent mutations")

    parser.add_argument("--host", help="Explicit host declaration; also LUMEN_HOST")
    parser.add_argument("--usage-log-location", action="append", help="Repeatable Codex log file/directory; may be outside project")
    parser.add_argument("--audience", choices=("tutor", "student"), default="tutor")
    args = parser.parse_args(argv)

    try:
        payload = parse_json_payload(args.json_input)
    except (ValueError, ValidationError) as e:
        output_json({
            "status": "error",
            "error_code": "INVALID_JSON_INPUT",
            "message": str(e),
            "details": {},
        }, exit_code=1)

    op = args.operation.lower().replace("-", "_")
    if args.audience == 'student' and op not in {'student_preview', 'student_search', 'assessment_paper', 'export_assessment', 'capabilities'}:
        output_json({'status': 'error', 'error_code': 'TUTOR_ONLY',
                     'message': 'This command is tutor-only; use student-search or student-preview.'}, exit_code=1)
    ws_path = Path(args.workspace).resolve()
    if op == "assemble_exam":
        try:
            blueprint_file = payload.get("blueprint_file")
            if not isinstance(blueprint_file, str) or not blueprint_file.strip():
                raise ValueError("blueprint_file is required")
            blueprint = json.loads(Path(blueprint_file).read_text(encoding="utf-8"),
                                   parse_constant=_reject_json_constants)
            if not isinstance(blueprint, dict):
                raise ValueError("blueprint must be an object")
            validate_all_finite_numbers(blueprint, "blueprint")
        except (OSError, UnicodeError, ValueError, ValidationError):
            output_json({"status": "error", "error_code": "INVALID_BLUEPRINT_FILE",
                         "message": "blueprint_file must name a readable finite JSON object.",
                         "details": {}}, exit_code=1)

    try:
        if op == "doctor":
            from .doctor import check_dependencies
            res = check_dependencies()
            output_json({"status": res["status"], "data": res},
                        exit_code=1 if res["missing"] else 0)

        elif op == "capabilities":
            res = check_capabilities(ws_path, host=args.host)
            output_json({"status": "success", "data": res})

        elif op in {"record_usage", "usage_summary"}:
            from .usage import record_usage, summarize_usage

            log_path = ws_path / "usage.jsonl"
            res = (record_usage(log_path, payload) if op == "record_usage"
                   else summarize_usage(log_path, payload.get("run_id")))
            output_json({"status": "success", "data": res})

        elif op in {"collect_usage", "watch_usage"}:
            from .usage_collector import collect_usage, watch_usage

            params = {"log_path": ws_path / "usage.jsonl",
                      "project_path": payload.get("project_path", Path.cwd()),
                      "codex_home": payload.get("codex_home"),
                      "log_locations": args.usage_log_location or payload.get("log_locations"),
                      "antigravity_app_home": payload.get("antigravity_app_home"),
                      "claude_home": payload.get("claude_home"), "hosts": payload.get("hosts")}
            if op == "watch_usage":
                res = watch_usage(**params, poll_seconds=payload.get("poll_seconds", 5),
                                  duration_seconds=payload.get("duration_seconds"),
                                  emit=lambda event: print(json.dumps(event, ensure_ascii=False, allow_nan=False), flush=True))
            else:
                res = collect_usage(**params)
            output_json({"status": "success", "data": res})

        elif op == "configure_usage":
            from .host_usage import configure_usage
            res = configure_usage(payload.get("project_path", Path.cwd()), ws_path / "usage.jsonl",
                                  hosts=payload.get("hosts"), claude_home=payload.get("claude_home"),
                                  antigravity_home=payload.get("antigravity_home"))
            output_json({"status": "success", "data": res})

        elif op == "restore":
            backup_path = payload.get("backup_path") or payload.get("backup_file")
            target_ws = payload.get("target_workspace") or ws_path
            force = payload.get("force", False)
            if not backup_path:
                output_json({
                    "status": "error",
                    "error_code": "VALIDATION_ERROR",
                    "message": "Missing 'backup_path' parameter for restore.",
                    "details": {},
                }, exit_code=1)
            res = LumenCore.restore(backup_path, target_ws, force=force)
            output_json({"status": "success", "data": res})

        else:
            core = LumenCore(ws_path)
            try:
                if args.request_id and "request_id" in payload and payload["request_id"] != args.request_id:
                    output_json({
                        "status": "error",
                        "error_code": "CONFLICTING_PARAMETERS",
                        "message": f"Conflicting request ID: CLI option --request-id is '{args.request_id}', but JSON payload request_id is '{payload['request_id']}'.",
                        "details": {"cli_request_id": args.request_id, "payload_request_id": payload["request_id"]},
                    }, exit_code=1)

                if args.course_id and "course_id" in payload and payload["course_id"] != args.course_id:
                    output_json({
                        "status": "error",
                        "error_code": "CONFLICTING_PARAMETERS",
                        "message": f"Conflicting course ID: CLI option --course-id is '{args.course_id}', but JSON payload course_id is '{payload['course_id']}'.",
                        "details": {"cli_course_id": args.course_id, "payload_course_id": payload["course_id"]},
                    }, exit_code=1)

                req_id = args.request_id or payload.get("request_id")
                cid = args.course_id or payload.get("course_id")

                if op == "list_courses":
                    output_json({"status": "success", "data": core.list_courses()})

                elif op == "create_course":
                    res = core.create_course(
                        name=payload.get("name", "Untitled Course"),
                        course_id=cid,
                        scope=payload.get("scope", ""),
                        default_language=payload.get("default_language", "en"),
                        notation_settings=payload.get("notation_settings"),
                        request_id=req_id,
                    )
                    output_json(res)

                elif op == "update_learner_settings":
                    res = core.update_learner_settings(
                        course_id=cid, learner_id=payload.get("learner_id", "default_learner"),
                        teaching_preference=payload.get("teaching_preference"),
                        chosen_language=payload.get("chosen_language"), explicit_goals=payload.get("explicit_goals"),
                        request_id=req_id,
                    )
                    output_json(res)

                elif op == "ingest_source":
                    res = core.ingest_source(
                        course_id=cid,
                        file_path=payload["file_path"],
                        logical_name=payload.get("logical_name"),
                        role=payload.get("role"),
                        structured_units=payload.get("structured_units"),
                        topic_slugs=payload.get("topic_slugs"),
                        request_id=req_id,
                        catalog_questions=payload.get('catalog_questions', True),
                    )
                    output_json(res)

                elif op == "course_brief":
                    res = core.course_brief(course_id=cid, learner_id=payload.get("learner_id", "default_learner"))
                    output_json({"status": "success", "data": res})

                elif op == "search":
                    query_str = args.query or payload.get("query", "")
                    res = core.search(
                        course_id=cid,
                        query=query_str,
                        topic_id=payload.get("topic_id"),
                        source_id=payload.get("source_id"),
                        limit=payload.get("limit", 10),
                    )
                    output_json({"status": "success", "data": res})

                elif op == "read_units":
                    res = core.read_units(
                        course_id=cid,
                        unit_ids=payload.get("unit_ids", []),
                        expand_dependencies=payload.get("expand_dependencies", False),
                    )
                    output_json({"status": "success", "data": res})

                elif op == "read_source_region":
                    res = core.read_source_region(
                        source_version_id=payload["source_version_id"],
                        page_index=payload.get("page_index"),
                        slide_index=payload.get("slide_index"),
                    )
                    output_json({"status": "success", "data": res})

                elif op == "create_topic":
                    res = core.create_topic(
                        course_id=cid,
                        name=payload["name"],
                        slug=payload.get("slug"),
                        parent_topic_id=payload.get("parent_topic_id"),
                        description=payload.get("description", ""),
                        request_id=req_id,
                    )
                    output_operation_result(res)

                elif op == "add_topic_alias":
                    res = core.add_topic_alias(
                        course_id=cid,
                        topic_id=payload["topic_id"],
                        alias=payload["alias"],
                        language=payload.get("language", "en"),
                        request_id=req_id,
                    )
                    output_operation_result(res)

                elif op == "add_topic_link":
                    res = core.add_topic_link(cid, payload["from_id"], payload["to_id"],
                                              rel_type=payload.get("rel_type", "prerequisite"), request_id=req_id)
                    output_operation_result(res)

                elif op == "create_exercise":
                    res = core.create_exercise(
                        course_id=cid,
                        exercise_family=payload["exercise_family"],
                        question_text=payload["question_text"],
                        subparts=payload.get("subparts"),
                        topic_mappings=payload.get("topic_mappings"),
                        skill_mappings=payload.get("skill_mappings"),
                        reference_solution=payload.get("reference_solution", ""),
                        rubric=payload.get("rubric"),
                        validation_state=payload.get("validation_state", "validated"),
                        external_ref=payload.get("external_ref", ""),
                        request_id=req_id,
                    )
                    output_operation_result(res)

                elif op == "start_attempt":
                    res = core.start_attempt(
                        course_id=cid,
                        exercise_version_id=payload["exercise_version_id"],
                        learner_id=payload.get("learner_id", "default_learner"),
                        mode=payload.get("mode", "practice"),
                        request_id=req_id,
                    )
                    output_json(res)

                elif op == "record_attempt_event":
                    res = core.record_attempt_event(
                        attempt_id=payload["attempt_id"],
                        expected_revision=payload["expected_revision"],
                        event_type=payload["event_type"],
                        subpart_key=payload.get("subpart_key"),
                        content=payload.get("content", ""),
                        metadata=payload.get("metadata"),
                        request_id=req_id,
                    )
                    output_json(res)

                elif op == "pause_attempt":
                    res = core.pause_attempt(
                        attempt_id=payload["attempt_id"],
                        expected_revision=payload["expected_revision"],
                        request_id=req_id,
                    )
                    output_json(res)

                elif op == "resume_attempt":
                    res = core.resume_attempt(
                        attempt_id=payload["attempt_id"],
                        expected_revision=payload["expected_revision"],
                        request_id=req_id,
                    )
                    output_json(res)

                elif op == "commit_evidence":
                    res = core.commit_evidence(
                        attempt_id=payload["attempt_id"],
                        evaluations=payload["evaluations"],
                        complete_attempt=payload.get("complete_attempt", False),
                        submission_event_id=payload.get("submission_event_id"),
                        request_id=req_id,
                    )
                    output_json(res)

                elif op == "correct_evidence":
                    res = core.correct_evidence(
                        evidence_id=payload["evidence_id"],
                        correction_reason=payload["correction_reason"],
                        replacement=payload.get("replacement"),
                        request_id=req_id,
                    )
                    output_json(res)

                elif op in {"batch_questions", "catalog_exam_questions", "review_question_occurrence", "review_exam_catalog", "review_question_relation", "grade_attempt", "annotate_question", "review_question_visual"}:
                    params = {k: v for k, v in payload.items() if k not in {"course_id", "request_id"}}
                    output_operation_result(getattr(core, op)(course_id=cid, request_id=req_id, **params))

                elif op in {"list_questions", "exam_catalog_status", "list_question_relations", "question_history", "attempt_history", "search_questions", "student_search", "student_preview"}:
                    params = {k: v for k, v in payload.items() if k not in {"course_id", "request_id"}}
                    output_json({"status": "success", "data": getattr(core, op)(course_id=cid, **params)})

                elif op == "blueprint_readiness":
                    res = core.blueprint_readiness(cid, payload.get("blueprint"),
                                                   payload.get("learner_id", "default_learner"))
                    output_json({"status": "success", "data": res})

                elif op == "propose_practice":
                    res = core.propose_practice(
                        course_id=cid, learner_id=payload.get("learner_id", "default_learner"),
                        count=payload.get("count", 1), topic_ids=payload.get("topic_ids"),
                        exclude_exercise_version_ids=payload.get("exclude_exercise_version_ids"),
                        allow_repeats=payload.get("allow_repeats", False),
                        focus=payload.get("focus", "all"),
                        source_only=payload.get("source_only", False),
                    )
                    output_json({"status": "success", "data": res})

                elif op == "assemble_exam":
                    output_operation_result(core.assemble_exam(
                        course_id=cid, learner_id=payload.get("learner_id"),
                        blueprint=blueprint, seed=payload.get("seed"),
                        request_id=req_id, title=payload.get("title"),
                    ))

                elif op in {"release_reservation", "expire_reservations"}:
                    if "learner_id" not in payload:
                        raise ValidationError("learner_id is required; use explicit null for an unowned draft.")
                    params = dict(course_id=cid, learner_id=payload["learner_id"], request_id=req_id)
                    if op == "release_reservation":
                        params.update(assessment_id=payload.get("assessment_id"),
                                      reason=payload.get("reason", "released"))
                    output_operation_result(getattr(core, op)(**params))

                elif op == "create_assessment":
                    res = core.create_assessment(
                        course_id=cid,
                        title=payload["title"],
                        blueprint=payload["blueprint"],
                        selected_exercise_version_ids=payload.get("selected_exercise_version_ids"),
                        learner_id=payload.get("learner_id"),
                        request_id=req_id,
                    )
                    output_json(res)

                elif op in {"assessment_paper", "export_assessment"}:
                    params = {"assessment_id": payload["assessment_id"], "course_id": cid}
                    if op == "export_assessment":
                        params["output_directory"] = payload.get("output_directory")
                    output_json({"status": "success", "data": getattr(core, op)(**params)})

                elif op == "assessment_progress":
                    res = core.assessment_progress(assessment_id=payload["assessment_id"])
                    output_json({"status": "success", "data": res})

                elif op == "get_extracted_sections":
                    res = core.get_extracted_sections(source_version_id=payload["source_version_id"])
                    output_json({"status": "success", "data": res})

                elif op == "enrich_source_version":
                    res = core.enrich_source_version(
                        source_version_id=payload["source_version_id"],
                        structured_units=payload["structured_units"],
                        publish=payload.get("publish", True),
                        topic_slugs=payload.get("topic_slugs"),
                        request_id=req_id,
                    )
                    output_operation_result(res)

                elif op == "validate_exercise_version":
                    res = core.validate_exercise_version(
                        version_id=payload["version_id"],
                        reviewer=payload.get("reviewer", "cli_user"),
                        checks=payload.get("checks", {}),
                        notes=payload.get("notes", ""),
                        validation_state=payload.get("validation_state", "validated"),
                        reference_solution=payload.get("reference_solution"),
                        rubric=payload.get("rubric"),
                        expected_revision=payload.get("expected_revision"),
                        expected_question_text=payload.get("expected_question_text"),
                        expected_reference_solution=payload.get("expected_reference_solution"),
                        expected_rubric=payload.get("expected_rubric"),
                        expected_content_hash=payload.get("expected_content_hash"),
                        request_id=req_id,
                    )
                    output_operation_result(res)

                elif op == "update_exercise_version":
                    res = core.update_exercise_version(
                        version_id=payload["version_id"],
                        question_text=payload.get("question_text"),
                        reference_solution=payload.get("reference_solution"),
                        rubric=payload.get("rubric"),
                        expected_revision=payload.get("expected_revision"),
                        subparts=payload.get("subparts"), topic_mappings=payload.get("topic_mappings"),
                        skill_mappings=payload.get("skill_mappings"),
                        context_blocks=payload.get("context_blocks"),
                        request_id=req_id,
                    )
                    output_operation_result(res)

                elif op == "repair_legacy_duplicate_links":
                    res = core.repair_legacy_duplicate_links(
                        resolved_assignments=payload.get("resolved_assignments"),
                        expected_link_states=payload.get("expected_link_states"),
                    )
                    output_json({"status": "success", "data": res})

                elif op == "start_assessment_item_attempt":
                    res = core.start_assessment_item_attempt(
                        assessment_id=payload["assessment_id"],
                        item_order=payload["item_order"],
                        learner_id=payload.get("learner_id", "default_learner"),
                        request_id=req_id,
                    )
                    if isinstance(res, dict) and "status" in res:
                        output_json(res)
                    else:
                        output_json({"status": "success", "data": res})

                elif op == "link_assessment_item_attempt":
                    res = core.link_assessment_item_attempt(
                        assessment_id=payload["assessment_id"],
                        item_order=payload["item_order"],
                        attempt_id=payload["attempt_id"],
                        learner_id=payload.get("learner_id"),
                        request_id=req_id,
                    )
                    if isinstance(res, dict) and "status" in res:
                        output_json(res)
                    else:
                        output_json({"status": "success", "data": res})

                elif op == "record_assessment_item_score":
                    res = core.record_assessment_item_score(
                        assessment_id=payload["assessment_id"],
                        item_order=payload["item_order"],
                        points_awarded=payload["points_awarded"],
                        attempt_id=payload.get("attempt_id"),
                        allow_partial=payload.get("allow_partial", False),
                        request_id=req_id,
                    )
                    if isinstance(res, dict) and "status" in res:
                        output_json(res)
                    else:
                        output_json({"status": "success", "data": res})

                elif op == "backup":
                    out_path = payload.get("output_path") or (ws_path / "backup.zip")
                    res = core.backup(out_path)
                    output_json({"status": "success", "data": res})

                else:
                    output_json({
                        "status": "error",
                        "error_code": "UNKNOWN_OPERATION",
                        "message": f"Unknown operation '{args.operation}'.",
                        "details": {},
                    }, exit_code=1)
            finally:
                core.close()

    except LumenError as e:
        output_json({
            "status": "error",
            "error_code": e.error_code,
            "message": e.message,
            "details": e.details,
        }, exit_code=1)
    except Exception as e:
        if op in {"release_reservation", "expire_reservations"}:
            output_json({"status": "error", "error_code": "RESERVATION_FAILED",
                         "message": "Reservation operation incomplete; retry with the same request ID.",
                         "details": {}}, exit_code=1)
        if op == "assemble_exam":
            output_json({"status": "error", "error_code": "ASSEMBLY_FAILED",
                         "message": "Assembly incomplete; retry with the same request ID.",
                         "details": {}}, exit_code=1)
        output_json({
            "status": "error",
            "error_code": "INTERNAL_ERROR",
            "message": str(e),
            "details": {"type": type(e).__name__},
        }, exit_code=2)


if __name__ == "__main__":
    main()
