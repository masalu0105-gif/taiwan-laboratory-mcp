from __future__ import annotations

import argparse
import json
from pathlib import Path

from .models import DataStatusResult


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="taiwan-lab-data")
    subparsers = parser.add_subparsers(dest="command", required=True)
    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--data-dir", type=Path)
    status_parser.add_argument("--json", action="store_true")
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("source_id", choices=["nhi_fee"])
    validate_parser.add_argument("--input", required=True, type=Path)
    validate_parser.add_argument("--json", action="store_true")
    sync_parser = subparsers.add_parser("sync")
    sync_parser.add_argument("source_id", choices=["nhi_fee"])
    sync_parser.add_argument("--input", type=Path)
    sync_parser.add_argument(
        "--publisher-oid",
        help="Explicitly enable upstream NHI discovery/fetch; never implied by the default.",
    )
    sync_parser.add_argument("--metadata-url")
    sync_parser.add_argument("--data-dir", required=True, type=Path)
    sync_parser.add_argument(
        "--fail-stage",
        choices=["discover", "fetch", "parse", "normalize", "validate"],
    )
    sync_parser.add_argument("--json", action="store_true")
    check_parser = subparsers.add_parser("check")
    check_parser.add_argument("source_id", choices=["nhi_fee"])
    check_parser.add_argument("--publisher-oid", required=True)
    check_parser.add_argument("--actor", required=True)
    check_parser.add_argument("--data-dir", required=True, type=Path)
    check_parser.add_argument("--json", action="store_true")
    rollback_parser = subparsers.add_parser("rollback")
    rollback_parser.add_argument("source_id", choices=["nhi_fee"])
    rollback_parser.add_argument("target_curated_build_id")
    rollback_parser.add_argument("--expected-generation", required=True, type=int)
    rollback_parser.add_argument("--reason", required=True)
    rollback_parser.add_argument("--actor", required=True)
    rollback_parser.add_argument("--data-dir", required=True, type=Path)
    rollback_parser.add_argument("--json", action="store_true")
    recovery_parser = subparsers.add_parser("recover-current")
    recovery_parser.add_argument("source_id", choices=["nhi_fee"])
    recovery_parser.add_argument("--publish-event", required=True)
    recovery_parser.add_argument("--actor", required=True)
    recovery_parser.add_argument("--data-dir", required=True, type=Path)
    recovery_parser.add_argument("--json", action="store_true")
    review_parser = subparsers.add_parser("prepare-review")
    review_parser.add_argument("source_id", choices=["nhi_fee"])
    review_parser.add_argument("--data-dir", required=True, type=Path)
    review_parser.add_argument("--output-dir", required=True, type=Path)
    review_parser.add_argument("--json", action="store_true")
    publish_parser = subparsers.add_parser("publish")
    publish_parser.add_argument("source_id", choices=["nhi_fee"])
    publish_parser.add_argument("--packet", required=True, type=Path)
    publish_parser.add_argument("--decision", required=True, type=Path)
    publish_parser.add_argument("--actor", required=True)
    publish_parser.add_argument("--data-dir", required=True, type=Path)
    publish_parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "status":
        if args.data_dir is not None:
            # The CLI status command is read-only; callers choose the process mode.
            import os

            os.environ["TAIWAN_LAB_DATA_DIR"] = str(args.data_dir)
            os.environ["TAIWAN_LAB_DATA_MODE"] = "official_snapshot"
        from .server import get_data_status

        result: DataStatusResult = get_data_status()
        print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")))
        return 0
    if args.command == "sync":
        if args.publisher_oid is not None:
            if args.input is not None:
                parser.error("sync --input and --publisher-oid are mutually exclusive")
            if args.fail_stage is not None:
                parser.error("sync --fail-stage is only available with --input")
            from .sync import run_nhi_upstream_sync

            report = run_nhi_upstream_sync(
                args.data_dir,
                expected_publisher_oid=args.publisher_oid,
                metadata_url=args.metadata_url,
            )
        else:
            if args.metadata_url is not None:
                parser.error("sync --metadata-url requires --publisher-oid")
            from .sync import run_nhi_sync

            initial_error = None
            payload = None
            if args.input is not None:
                try:
                    payload = args.input.read_bytes()
                except OSError:
                    initial_error = "FETCH_INPUT_UNAVAILABLE"
            report = run_nhi_sync(
                payload,
                args.data_dir,
                fail_stage=args.fail_stage,
                initial_error=initial_error,
            )
        print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
        if report["status"] == "passed":
            return 0
        if report["stage"] in {"discover", "fetch"}:
            return 3
        return 4
    if args.command == "check":
        from .publish import PublishError
        from .sync import SyncError, run_nhi_upstream_check

        try:
            summary = run_nhi_upstream_check(
                args.data_dir,
                expected_publisher_oid=args.publisher_oid,
                actor=args.actor,
            )
        except (PublishError, SyncError) as exc:
            print(
                json.dumps(
                    {"operation": "check", "result": "failed", "error_code": exc.code},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
            return 6
        print(json.dumps(summary, ensure_ascii=False, separators=(",", ":")))
        if summary.get("failed_stage") in {"discover", "fetch"}:
            return 3
        if summary.get("failed_stage"):
            return 4
        return 0
    if args.command == "validate":
        from .importers.nhi import NHIImportError, parse_nhi_csv

        try:
            payload = args.input.read_bytes()
        except OSError:
            print(
                json.dumps(
                    {
                        "source_id": args.source_id,
                        "validation_status": "failed",
                        "error_code": "INPUT_UNAVAILABLE",
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
            return 4
        try:
            parsed = parse_nhi_csv(payload)
        except NHIImportError as exc:
            print(
                json.dumps(
                    {
                        "source_id": args.source_id,
                        "validation_status": "failed",
                        "error_code": exc.code,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
            return 4
        print(
            json.dumps(
                {
                    "source_id": args.source_id,
                    "validation_status": "passed",
                    "rows": len(parsed.rows),
                    "warnings": list(parsed.warnings),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        return 0
    if args.command in {"rollback", "recover-current"}:
        from .publish import PublishError, recover_current, rollback_current_descriptor

        try:
            if args.command == "rollback":
                event = rollback_current_descriptor(
                    args.data_dir,
                    args.source_id,
                    args.target_curated_build_id,
                    expected_generation=args.expected_generation,
                    reason=args.reason,
                    actor=args.actor,
                )
            else:
                event = recover_current(
                    args.data_dir,
                    args.source_id,
                    args.publish_event,
                    actor=args.actor,
                )
        except PublishError as exc:
            print(
                json.dumps(
                    {
                        "operation": args.command,
                        "status": "failed",
                        "error_code": exc.code,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
            return 6
        print(
            json.dumps(
                {
                    "operation": args.command,
                    "status": "success",
                    "event_id": event["event_id"],
                    "generation": event["generation"],
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        return 0
    if args.command in {"prepare-review", "publish"}:
        from .importers.nhi import NHIImportError
        from .nhi_review import (
            NHIReviewError,
            prepare_nhi_review_packet,
            publish_reviewed_nhi_candidate,
        )
        from .publish import PublishError

        try:
            if args.command == "prepare-review":
                summary = prepare_nhi_review_packet(args.data_dir, output_dir=args.output_dir)
            else:
                summary = publish_reviewed_nhi_candidate(
                    args.data_dir,
                    packet_path=args.packet,
                    decision_path=args.decision,
                    actor=args.actor,
                )
        except (NHIReviewError, NHIImportError, PublishError) as exc:
            print(
                json.dumps(
                    {"operation": args.command, "result": "failed", "error_code": exc.code},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
            return _review_exit_code(exc)
        print(json.dumps(summary, ensure_ascii=False, separators=(",", ":")))
        return 0
    parser.error("unsupported command")
    return 2


_USAGE_ERROR_CODES = frozenset(
    {
        "REVIEW_INPUT_UNREADABLE",
        "APPLICATION_BUILD_IDENTITY_MISSING",
        "PUBLISHER_ACTOR_INVALID",
        "EVIDENCE_FILE_INVALID",
        "REVIEW_PROTOCOL_INVALID",
    }
)
_INTEGRITY_ERROR_CODES = frozenset({"SERVING_INTEGRITY_FAILURE", "NO_SERVING_SNAPSHOT"})


def _review_exit_code(exc: Exception) -> int:
    """SDD 12 exit codes: 2 usage/config, 5 review gate, 6 publish/integrity."""

    from .nhi_review import NHIReviewError

    code = getattr(exc, "code", "")
    if code in _USAGE_ERROR_CODES:
        return 2
    if isinstance(exc, NHIReviewError):
        return 6 if code in _INTEGRITY_ERROR_CODES else 5
    if code.startswith(("OWNER_REVIEW_", "GOLDEN_")):
        return 5
    return 6


if __name__ == "__main__":
    raise SystemExit(main())
