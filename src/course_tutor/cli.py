"""Structured JSON Command-Line Interface for Lumen."""

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

from .api import LumenCore
from .errors import LumenError


def parse_json_payload(raw_json: Optional[str]) -> Dict[str, Any]:
    if raw_json:
        try:
            val = json.loads(raw_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Malformed JSON argument: {e}")
        if not isinstance(val, dict):
            raise ValueError(f"JSON input must be an object (dictionary), got {type(val).__name__}.")
        return val
    if not sys.stdin.isatty():
        content = sys.stdin.read().strip()
        if content:
            try:
                val = json.loads(content)
            except json.JSONDecodeError as e:
                raise ValueError(f"Malformed stdin JSON: {e}")
            if not isinstance(val, dict):
                raise ValueError(f"JSON input must be an object (dictionary), got {type(val).__name__}.")
            return val
    return {}


def output_json(payload: Dict[str, Any], exit_code: int = 0) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    sys.exit(exit_code)


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Lumen - Portable course learning and assessment core")
    parser.add_argument("operation", nargs="?", default="capabilities", help="Operation to execute")
    parser.add_argument("--workspace", "-w", default=".lumen", help="Path to workspace directory")
    parser.add_argument("--json-input", "-j", help="Input parameters as JSON string")
    parser.add_argument("--course-id", "-c", help="Course ID")
    parser.add_argument("--query", "-q", help="Search query")
    parser.add_argument("--request-id", "-r", help="Stable request ID for idempotent mutations")

    args = parser.parse_args(argv)

    try:
        payload = parse_json_payload(args.json_input)
    except ValueError as e:
        output_json({
            "status": "error",
            "error_code": "INVALID_JSON_INPUT",
            "message": str(e),
            "details": {},
        }, exit_code=1)

    op = args.operation.lower().replace("-", "_")
    ws_path = Path(args.workspace).resolve()

    try:
        if op == "capabilities":
            res = LumenCore(ws_path).capabilities()
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

                if op == "create_course":
                    res = core.create_course(
                        name=payload.get("name", "Untitled Course"),
                        course_id=cid,
                        scope=payload.get("scope", ""),
                        default_language=payload.get("default_language", "en"),
                        notation_settings=payload.get("notation_settings"),
                        request_id=req_id,
                    )
                    output_json(res)

                elif op == "ingest_source":
                    res = core.ingest_source(
                        course_id=cid,
                        file_path=payload["file_path"],
                        logical_name=payload.get("logical_name"),
                        role=payload.get("role", "reference"),
                        structured_units=payload.get("structured_units"),
                        topic_slugs=payload.get("topic_slugs"),
                        request_id=req_id,
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
                    )
                    output_json({"status": "success", "data": res})

                elif op == "add_topic_alias":
                    res = core.add_topic_alias(
                        course_id=cid,
                        topic_id=payload["topic_id"],
                        alias=payload["alias"],
                        language=payload.get("language", "en"),
                    )
                    output_json({"status": "success", "data": res})

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
                    )
                    output_json({"status": "success", "data": res})

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

                elif op == "create_assessment":
                    res = core.create_assessment(
                        course_id=cid,
                        title=payload["title"],
                        blueprint=payload["blueprint"],
                        selected_exercise_version_ids=payload.get("selected_exercise_version_ids"),
                        request_id=req_id,
                    )
                    output_json(res)

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
                    )
                    output_json({"status": "success", "data": res})

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
                    )
                    output_json({"status": "success", "data": res})

                elif op == "update_exercise_version":
                    res = core.update_exercise_version(
                        version_id=payload["version_id"],
                        question_text=payload.get("question_text"),
                        reference_solution=payload.get("reference_solution"),
                        rubric=payload.get("rubric"),
                        expected_revision=payload.get("expected_revision"),
                    )
                    output_json({"status": "success", "data": res})

                elif op == "repair_legacy_duplicate_links":
                    res = core.repair_legacy_duplicate_links(
                        resolved_assignments=payload.get("resolved_assignments"),
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
        output_json({
            "status": "error",
            "error_code": "INTERNAL_ERROR",
            "message": str(e),
            "details": {"type": type(e).__name__},
        }, exit_code=2)


if __name__ == "__main__":
    main()
