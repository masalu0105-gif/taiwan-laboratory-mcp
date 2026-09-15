from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

from .audit import _sha256_file, validate_audit_evidence
from .canonical import canonical_json_bytes, sha256_bytes


class PublishError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


# Per internal source id: the raw artifact file name and the curated row table.
_RAW_ARTIFACT_NAMES = {
    "nhi_fee": "source.csv",
    "tfda_devices": "source.zip",
    "cdc_authorized_labs": "source.ods",
    # The revision table PDF stays in the same raw revision; the served rows come from the manual.
    "cdc_specimen_manual": "manual.pdf",
}
_CURATED_TABLES = {
    "nhi_fee": "nhi_fee",
    "tfda_devices": "tfda_source_row",
    "cdc_authorized_labs": "cdc_lab_row",
    "cdc_specimen_manual": "cdc_specimen_requirement",
}


_DESCRIPTOR_KEYS = frozenset(
    {
        "descriptor_schema_version",
        "source_id",
        "generation",
        "serving_snapshot_id",
        "serving_curated_build_id",
        "manifest_data_root_relative_path",
        "manifest_sha256",
        "parent_snapshot_id",
        "last_successful_publish_at",
        "publisher_actor_id",
        "last_check_at",
        "last_successful_check_at",
        "latest_seen_version",
        "latest_seen_artifact_sha256",
        "latest_candidate_id",
        "latest_candidate_status",
        "check_result",
        "failed_stage",
        "error_code",
        "stale",
        "stale_reason_codes",
        "freshness_policy_version",
        "content_age_status",
        "content_age_evidence",
        "latest_check_data_root_relative_path",
        "latest_check_sha256",
    }
)


def _validate_descriptor_keys(descriptor: dict[str, Any], source_id: str, error_code: str) -> None:
    if (
        set(descriptor) != _DESCRIPTOR_KEYS
        or descriptor.get("descriptor_schema_version") != 1
        or descriptor.get("source_id") != source_id
    ):
        raise PublishError(error_code)


def _read_canonical_object(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    pairs: list[tuple[str, Any]] = []

    def collect(items: list[tuple[str, Any]]) -> dict[str, Any]:
        keys = [key for key, _ in items]
        if len(keys) != len(set(keys)):
            raise PublishError("PUBLISH_EVENT_INDEX_INVALID")
        result = dict(items)
        pairs.append(("", result))
        return result

    value = json.loads(raw.decode("utf-8"), object_pairs_hook=collect)
    if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
        raise PublishError("PUBLISH_EVENT_INDEX_INVALID")
    return value


def _atomic_write_bytes(path: Path, payload: bytes) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return payload


def _atomic_write(path: Path, value: dict[str, Any]) -> bytes:
    return _atomic_write_bytes(path, canonical_json_bytes(value))


@contextmanager
def _source_lock(path: Path, timeout_seconds: float = 5.0) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            deadline = time.monotonic() + timeout_seconds
            while True:
                try:
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise PublishError("PUBLISH_LOCK_TIMEOUT") from exc
                    time.sleep(0.05)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            # Non-blocking attempts with the same bounded retry as Windows; a blocking
            # LOCK_EX would wait forever and never report PUBLISH_LOCK_TIMEOUT.
            deadline = time.monotonic() + timeout_seconds
            while True:
                try:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise PublishError("PUBLISH_LOCK_TIMEOUT") from exc
                    time.sleep(0.05)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _event_index_state(data_root: Path, source_id: str) -> str:
    path = data_root / "publish-events" / f"{source_id}.jsonl"
    if not path.is_file():
        return "none"
    try:
        for line in path.read_bytes().splitlines():
            if not line:
                continue
            event = json.loads(line.decode("utf-8"))
            if not isinstance(event, dict) or canonical_json_bytes(event) != line:
                return "invalid"
            if (
                event.get("source_id") == source_id
                and event.get("event_type") in {"publish", "rollback", "recover_current"}
                and event.get("result") == "success"
            ):
                return "success"
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return "invalid"
    return "none"


def has_successful_publish_event(data_root: Path, source_id: str) -> bool:
    """Return whether a valid successful event exists in the append-only index."""

    state = _event_index_state(Path(data_root), source_id)
    if state == "invalid":
        raise PublishError("PUBLISH_EVENT_INDEX_INVALID")
    return state == "success"


def _append_event(data_root: Path, source_id: str, event: dict[str, Any]) -> None:
    event_path = data_root / "publish-events" / f"{source_id}.jsonl"
    event_path.parent.mkdir(parents=True, exist_ok=True)
    with event_path.open("ab") as stream:
        stream.write(canonical_json_bytes(event) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def _restore_path_bytes(path: Path, before_bytes: bytes | None) -> None:
    if before_bytes is None:
        if path.exists():
            path.unlink()
    elif path.read_bytes() != before_bytes:
        _atomic_write_bytes(path, before_bytes)


def _replace_current_descriptor(
    current_path: Path, descriptor: dict[str, Any], before_descriptor_bytes: bytes | None
) -> bytes:
    """Replace the serving pointer and restore its exact prior bytes on failure."""

    try:
        payload = _atomic_write(current_path, descriptor)
        if current_path.read_bytes() != payload:
            raise PublishError("PUBLISH_READBACK_FAILURE")
        return payload
    except PublishError:
        try:
            _restore_path_bytes(current_path, before_descriptor_bytes)
        except Exception as recovery_exc:
            raise PublishError("PUBLISH_RECOVERY_REQUIRED") from recovery_exc
        raise
    except Exception as exc:
        try:
            _restore_path_bytes(current_path, before_descriptor_bytes)
        except Exception as recovery_exc:
            raise PublishError("PUBLISH_RECOVERY_REQUIRED") from recovery_exc
        raise PublishError("PUBLISH_WRITE_FAILURE") from exc


def _append_event_transactionally(
    data_root: Path,
    source_id: str,
    event: dict[str, Any],
    *,
    current_path: Path,
    before_descriptor_bytes: bytes | None,
    cleanup_paths: tuple[Path, ...] = (),
) -> None:
    """Append an event and recover pointer/index artifacts if the append fails.

    Callers hold the source publish lock. The event index is append-only on the
    success path; on failure, this restores the exact bytes observed before the
    pointer replacement and removes newly-created unreferenced artifacts.
    """

    event_path = data_root / "publish-events" / f"{source_id}.jsonl"
    before_event_bytes = event_path.read_bytes() if event_path.is_file() else None
    try:
        _append_event(data_root, source_id, event)
    except Exception as exc:
        try:
            _restore_path_bytes(current_path, before_descriptor_bytes)

            if before_event_bytes is None:
                if event_path.exists():
                    event_path.unlink()
            elif event_path.read_bytes() != before_event_bytes:
                _atomic_write_bytes(event_path, before_event_bytes)

            for cleanup_path in cleanup_paths:
                if cleanup_path.exists():
                    cleanup_path.unlink()
        except Exception as recovery_exc:
            raise PublishError("PUBLISH_RECOVERY_REQUIRED") from recovery_exc
        raise PublishError("PUBLISH_EVENT_APPEND_FAILURE") from exc


def _read_success_event(data_root: Path, source_id: str, event_id: str) -> dict[str, Any]:
    path = Path(data_root) / "publish-events" / f"{source_id}.jsonl"
    if not path.is_file():
        raise PublishError("PUBLISH_EVENT_NOT_FOUND")
    try:
        for line in path.read_bytes().splitlines():
            if not line:
                continue
            event = json.loads(line.decode("utf-8"))
            if not isinstance(event, dict) or canonical_json_bytes(event) != line:
                raise PublishError("PUBLISH_EVENT_INDEX_INVALID")
            if event.get("event_id") == event_id:
                if (
                    event.get("source_id") != source_id
                    or event.get("result") != "success"
                    or event.get("event_type") not in {"publish", "rollback"}
                ):
                    raise PublishError("PUBLISH_EVENT_INVALID")
                return event
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        if isinstance(exc, PublishError):
            raise
        raise PublishError("PUBLISH_EVENT_INDEX_INVALID") from exc
    raise PublishError("PUBLISH_EVENT_NOT_FOUND")


def _target_manifest(
    data_root: Path, source_id: str, target_curated_build_id: str
) -> tuple[dict[str, Any], Path, str]:
    if not re.fullmatch(rf"{re.escape(source_id)}-build-[0-9a-f]{{64}}", target_curated_build_id):
        raise PublishError("ROLLBACK_TARGET_INVALID")
    manifest_relative = f"curated/{source_id}/{target_curated_build_id}/manifest.json"
    manifest_path = Path(data_root) / PurePosixPath(manifest_relative)
    if not manifest_path.is_file():
        raise PublishError("ROLLBACK_TARGET_UNAVAILABLE")
    try:
        manifest = _read_canonical_object(manifest_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, PublishError) as exc:
        raise PublishError("ROLLBACK_TARGET_INTEGRITY") from exc
    if (
        manifest.get("state") != "approved"
        or manifest.get("source_id") != source_id
        or manifest.get("snapshot_id") != target_curated_build_id
        or manifest.get("curated_build_id") != target_curated_build_id
    ):
        raise PublishError("ROLLBACK_TARGET_INTEGRITY")
    raw_artifact_name = _RAW_ARTIFACT_NAMES.get(source_id)
    if raw_artifact_name is not None:
        artifacts = manifest.get("artifacts")
        raw_revision_id = manifest.get("raw_revision_id")
        if (
            not isinstance(artifacts, list)
            or len(artifacts) != 1
            or not isinstance(raw_revision_id, str)
            or not re.fullmatch(r"[0-9a-f]{64}", raw_revision_id)
        ):
            raise PublishError("ROLLBACK_TARGET_INTEGRITY")
        artifact = artifacts[0]
        expected_raw_relative = f"raw/{source_id}/{raw_revision_id}/artifacts/{raw_artifact_name}"
        if (
            not isinstance(artifact, dict)
            or artifact.get("role") != "primary"
            or artifact.get("storage_scope") != "data_root"
            or artifact.get("data_root_relative_path") != expected_raw_relative
            or type(artifact.get("local_artifact_available")) is not bool
            or not isinstance(artifact.get("sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"])
        ):
            raise PublishError("ROLLBACK_TARGET_INTEGRITY")
        if artifact["local_artifact_available"]:
            raw_path = Path(data_root) / PurePosixPath(expected_raw_relative)
            if not raw_path.is_file() or _sha256_file(raw_path) != artifact["sha256"]:
                raise PublishError("ROLLBACK_TARGET_INTEGRITY")
    publication = manifest.get("publication")
    if not isinstance(publication, dict):
        raise PublishError("ROLLBACK_TARGET_INTEGRITY")
    db_relative = publication.get("curated_build_relative_path")
    expected_db_relative = f"curated/{source_id}/{target_curated_build_id}/data.sqlite3"
    if db_relative != expected_db_relative:
        raise PublishError("ROLLBACK_TARGET_INTEGRITY")
    db_path = Path(data_root) / PurePosixPath(db_relative)
    if not db_path.is_file() or _sha256_file(db_path) != publication.get("curated_sha256"):
        raise PublishError("ROLLBACK_TARGET_INTEGRITY")
    table = _CURATED_TABLES.get(source_id)
    if table is None:
        raise PublishError("ROLLBACK_TARGET_INTEGRITY")
    uri = f"file:{db_path.as_posix()}?mode=ro&immutable=1"
    try:
        connection = sqlite3.connect(uri, uri=True)
        try:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise PublishError("ROLLBACK_TARGET_INTEGRITY")
            counts = manifest.get("counts")
            count = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            if (
                not isinstance(counts, dict)
                or set(counts) != {"input_rows", "curated_rows", "quarantined_rows"}
                or any(type(value) is not int or value < 0 for value in counts.values())
                or counts["input_rows"] != counts["curated_rows"]
                or counts["quarantined_rows"] != 0
                or count != counts["curated_rows"]
            ):
                raise PublishError("ROLLBACK_TARGET_INTEGRITY")
        finally:
            connection.close()
    except (OSError, sqlite3.DatabaseError) as exc:
        raise PublishError("ROLLBACK_TARGET_INTEGRITY") from exc
    try:
        validate_audit_evidence(Path(data_root), manifest)
    except ValueError as exc:
        raise PublishError("ROLLBACK_TARGET_INTEGRITY") from exc
    return manifest, manifest_path, sha256_bytes(manifest_path.read_bytes())


_CHECK_RECORD_KEYS = frozenset(
    {
        "check_schema_version",
        "check_id",
        "source_id",
        "generation",
        "serving_snapshot_id",
        "serving_curated_build_id",
        "checked_at",
        "latest_seen_version",
        "latest_seen_artifact_sha256",
        "latest_candidate_id",
        "latest_candidate_status",
        "check_result",
        "failed_stage",
        "error_code",
        "stale",
        "stale_reason_codes",
        "freshness_policy_version",
        "content_age_status",
        "content_age_evidence",
    }
)


def _load_current_check(data_root: Path, descriptor: dict[str, Any]) -> dict[str, Any]:
    relative = descriptor.get("latest_check_data_root_relative_path")
    digest = descriptor.get("latest_check_sha256")
    if not isinstance(relative, str) or not isinstance(digest, str):
        raise PublishError("CURRENT_OPERATIONAL_INTEGRITY")
    path = PurePosixPath(relative)
    if (
        path.is_absolute()
        or path.parts[:2] != ("checks", descriptor["source_id"])
        or len(path.parts) != 3
    ):
        raise PublishError("CURRENT_OPERATIONAL_INTEGRITY")
    check_path = Path(data_root) / path
    if not check_path.is_file() or sha256_bytes(check_path.read_bytes()) != digest:
        raise PublishError("CURRENT_OPERATIONAL_INTEGRITY")
    try:
        check = _read_canonical_object(check_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, PublishError) as exc:
        raise PublishError("CURRENT_OPERATIONAL_INTEGRITY") from exc
    if set(check) != _CHECK_RECORD_KEYS or check.get("source_id") != descriptor["source_id"]:
        raise PublishError("CURRENT_OPERATIONAL_INTEGRITY")
    if check.get("generation") != descriptor.get("generation"):
        raise PublishError("CURRENT_OPERATIONAL_INTEGRITY")
    if check.get("serving_snapshot_id") != descriptor.get("serving_snapshot_id"):
        raise PublishError("CURRENT_OPERATIONAL_INTEGRITY")
    if check.get("serving_curated_build_id") != descriptor.get("serving_curated_build_id"):
        raise PublishError("CURRENT_OPERATIONAL_INTEGRITY")
    for key in (
        "latest_seen_version",
        "latest_seen_artifact_sha256",
        "latest_candidate_id",
        "latest_candidate_status",
        "check_result",
        "failed_stage",
        "error_code",
        "stale",
        "stale_reason_codes",
        "freshness_policy_version",
        "content_age_status",
        "content_age_evidence",
    ):
        if check.get(key) != descriptor.get(key):
            raise PublishError("CURRENT_OPERATIONAL_INTEGRITY")
    if check.get("checked_at") != descriptor.get("last_check_at"):
        raise PublishError("CURRENT_OPERATIONAL_INTEGRITY")
    if check.get("check_result") == "success" and check.get("checked_at") != descriptor.get(
        "last_successful_check_at"
    ):
        raise PublishError("CURRENT_OPERATIONAL_INTEGRITY")
    return check


def _write_immutable(path: Path, value: dict[str, Any]) -> bytes:
    payload = canonical_json_bytes(value)
    if path.exists():
        if path.read_bytes() != payload:
            raise PublishError("IMMUTABLE_CHECK_CONFLICT")
        return payload
    _atomic_write(path, value)
    return payload


def publish_current_descriptor(
    data_root: Path,
    descriptor: dict[str, Any],
    *,
    expected_generation: int,
    expected_parent_snapshot_id: str | None,
    actor: str,
) -> dict[str, Any]:
    """Atomically publish one already-built descriptor with generation CAS."""

    data_root = Path(data_root)
    source_id = descriptor.get("source_id")
    if not isinstance(source_id, str) or not re.fullmatch(r"[a-z0-9_]+", source_id):
        raise PublishError("PUBLISH_DESCRIPTOR_INVALID")
    if not isinstance(actor, str) or not actor:
        raise PublishError("PUBLISH_ACTOR_INVALID")
    if descriptor.get("publisher_actor_id") != actor:
        raise PublishError("PUBLISH_ACTOR_MISMATCH")
    _validate_descriptor_keys(descriptor, source_id, "PUBLISH_DESCRIPTOR_INVALID")
    current_path = data_root / "manifests" / "current" / f"{source_id}.json"
    lock_path = data_root / "locks" / f"{source_id}.publish.lock"
    with _source_lock(lock_path):
        if current_path.is_file():
            try:
                current = _read_canonical_object(current_path)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, PublishError) as exc:
                raise PublishError("CURRENT_POINTER_INTEGRITY") from exc
            _validate_descriptor_keys(current, source_id, "CURRENT_POINTER_INTEGRITY")
            before_descriptor_bytes = current_path.read_bytes()
            before_hash = sha256_bytes(before_descriptor_bytes)
            current_generation = current.get("generation")
            current_parent = current.get("serving_snapshot_id")
            if (
                type(current_generation) is not int
                or current_generation != expected_generation
                or current_parent != expected_parent_snapshot_id
            ):
                raise PublishError("PUBLISH_CAS_MISMATCH")
        else:
            if expected_generation != 0 or expected_parent_snapshot_id is not None:
                raise PublishError("PUBLISH_CAS_MISMATCH")
            if _event_index_state(data_root, source_id) != "none":
                raise PublishError("CURRENT_POINTER_INTEGRITY")
            current = None
            before_descriptor_bytes = None
            before_hash = None

        new_generation = descriptor.get("generation")
        if type(new_generation) is not int or new_generation != expected_generation + 1:
            raise PublishError("PUBLISH_GENERATION_INVALID")
        if descriptor.get("parent_snapshot_id") != expected_parent_snapshot_id:
            raise PublishError("PUBLISH_PARENT_MISMATCH")
        target_id = descriptor.get("serving_curated_build_id")
        if descriptor.get("serving_snapshot_id") != target_id or not isinstance(target_id, str):
            raise PublishError("PUBLISH_DESCRIPTOR_INVALID")
        try:
            _, _, manifest_hash = _target_manifest(data_root, source_id, target_id)
            _load_current_check(data_root, descriptor)
        except PublishError as exc:
            raise PublishError("PUBLISH_DESCRIPTOR_INTEGRITY") from exc
        expected_manifest_relative = f"curated/{source_id}/{target_id}/manifest.json"
        if (
            descriptor.get("manifest_data_root_relative_path") != expected_manifest_relative
            or descriptor.get("manifest_sha256") != manifest_hash
        ):
            raise PublishError("PUBLISH_DESCRIPTOR_INTEGRITY")
        payload = _replace_current_descriptor(current_path, descriptor, before_descriptor_bytes)
        after_hash = sha256_bytes(payload)
        published_at = descriptor.get("last_successful_publish_at")
        if not published_at:
            published_at = (
                datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            )
        event = {
            "event_schema_version": 1,
            "event_id": f"publish-{after_hash}",
            "event_type": "publish",
            "source_id": source_id,
            "generation": new_generation,
            "before_descriptor_sha256": before_hash,
            "after_descriptor_sha256": after_hash,
            "snapshot_id": descriptor.get("serving_snapshot_id"),
            "actor": actor,
            "published_at": published_at,
            "result": "success",
            "rollback": False,
            "after_descriptor": descriptor,
        }
        _append_event_transactionally(
            data_root,
            source_id,
            event,
            current_path=current_path,
            before_descriptor_bytes=before_descriptor_bytes,
        )
        return event


def publish_operational_check(
    data_root: Path,
    source_id: str,
    check: dict[str, Any],
    *,
    expected_generation: int,
    actor: str,
) -> dict[str, Any]:
    """Publish a status/check revision while preserving the serving snapshot."""

    data_root = Path(data_root)
    if not re.fullmatch(r"[a-z0-9_]+", source_id):
        raise PublishError("CHECK_SOURCE_INVALID")
    if type(expected_generation) is not int or expected_generation < 1:
        raise PublishError("CHECK_GENERATION_INVALID")
    if not isinstance(actor, str) or not actor:
        raise PublishError("PUBLISH_ACTOR_INVALID")
    if not isinstance(check, dict) or set(check) != _CHECK_RECORD_KEYS:
        raise PublishError("CHECK_RECORD_INVALID")
    check_id = check.get("check_id")
    if not isinstance(check_id, str) or not re.fullmatch(
        rf"{re.escape(source_id)}-check-[a-z0-9-]+", check_id
    ):
        raise PublishError("CHECK_RECORD_INVALID")
    if check.get("source_id") != source_id:
        raise PublishError("CHECK_SOURCE_MISMATCH")
    if not isinstance(check.get("check_result"), str) or check.get("check_result") not in {
        "success",
        "failed",
    }:
        raise PublishError("CHECK_RESULT_INVALID")
    try:
        checked_at = datetime.fromisoformat(check["checked_at"].replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise PublishError("CHECK_TIMESTAMP_INVALID") from exc
    if checked_at.utcoffset() is None:
        raise PublishError("CHECK_TIMESTAMP_INVALID")
    candidate_status = check.get("latest_candidate_status")
    candidate_id = check.get("latest_candidate_id")
    if candidate_status == "none" and candidate_id is not None:
        raise PublishError("CHECK_CANDIDATE_INVALID")
    if candidate_status != "none" and (
        not isinstance(candidate_status, str)
        or candidate_status not in {"validating", "review_pending", "rejected", "publishable"}
        or not isinstance(candidate_id, str)
        or not candidate_id
    ):
        raise PublishError("CHECK_CANDIDATE_INVALID")
    if type(check.get("stale")) is not bool or check.get("stale") != bool(
        check.get("stale_reason_codes")
    ):
        raise PublishError("CHECK_STALE_INVALID")
    if check.get("check_result") == "success" and (
        check.get("failed_stage") is not None or check.get("error_code") is not None
    ):
        raise PublishError("CHECK_RESULT_INVALID")
    current_path = data_root / "manifests" / "current" / f"{source_id}.json"
    with _source_lock(data_root / "locks" / f"{source_id}.publish.lock"):
        if not current_path.is_file():
            raise PublishError("CURRENT_POINTER_INTEGRITY")
        try:
            current = _read_canonical_object(current_path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, PublishError) as exc:
            raise PublishError("CURRENT_POINTER_INTEGRITY") from exc
        _validate_descriptor_keys(current, source_id, "CURRENT_POINTER_INTEGRITY")
        if (
            current.get("source_id") != source_id
            or current.get("generation") != expected_generation
        ):
            raise PublishError("PUBLISH_CAS_MISMATCH")
        serving_id = current.get("serving_curated_build_id")
        if current.get("serving_snapshot_id") != serving_id or not isinstance(serving_id, str):
            raise PublishError("CURRENT_POINTER_INTEGRITY")
        try:
            _, _, manifest_hash = _target_manifest(data_root, source_id, serving_id)
            _load_current_check(data_root, current)
        except PublishError as exc:
            raise PublishError("CURRENT_OPERATIONAL_INTEGRITY") from exc
        if (
            current.get("manifest_sha256") != manifest_hash
            or current.get("manifest_data_root_relative_path")
            != f"curated/{source_id}/{serving_id}/manifest.json"
        ):
            raise PublishError("CURRENT_POINTER_INTEGRITY")
        if (
            check.get("serving_snapshot_id") != serving_id
            or check.get("serving_curated_build_id") != serving_id
        ):
            raise PublishError("CHECK_SERVING_IDENTITY_MISMATCH")
        next_generation = expected_generation + 1
        next_check = dict(check)
        next_check["generation"] = next_generation
        check_relative = f"checks/{source_id}/{check_id}.json"
        check_path = data_root / check_relative
        check_preexisted = check_path.exists()
        check_bytes = _write_immutable(check_path, next_check)
        next_descriptor = dict(current)
        next_descriptor["generation"] = next_generation
        for key in (
            "latest_seen_version",
            "latest_seen_artifact_sha256",
            "latest_candidate_id",
            "latest_candidate_status",
            "check_result",
            "failed_stage",
            "error_code",
            "stale",
            "stale_reason_codes",
            "freshness_policy_version",
            "content_age_status",
            "content_age_evidence",
        ):
            next_descriptor[key] = next_check[key]
        next_descriptor["last_check_at"] = next_check["checked_at"]
        if next_check["check_result"] == "success":
            next_descriptor["last_successful_check_at"] = next_check["checked_at"]
        next_descriptor["latest_check_data_root_relative_path"] = check_relative
        next_descriptor["latest_check_sha256"] = sha256_bytes(check_bytes)
        try:
            _load_current_check(data_root, next_descriptor)
        except PublishError as exc:
            raise PublishError("CHECK_RECORD_INVALID") from exc
        before_descriptor_bytes = current_path.read_bytes()
        before_hash = sha256_bytes(before_descriptor_bytes)
        descriptor_bytes = _replace_current_descriptor(
            current_path, next_descriptor, before_descriptor_bytes
        )
        after_hash = sha256_bytes(descriptor_bytes)
        event = {
            "event_schema_version": 1,
            "event_id": f"check-{after_hash}",
            "event_type": "check",
            "source_id": source_id,
            "generation": next_generation,
            "before_descriptor_sha256": before_hash,
            "after_descriptor_sha256": after_hash,
            "snapshot_id": serving_id,
            "check_id": check_id,
            "check_result": next_check["check_result"],
            "actor": actor,
            "published_at": next_check["checked_at"],
            "result": "success",
            "rollback": False,
            "after_descriptor": next_descriptor,
        }
        _append_event_transactionally(
            data_root,
            source_id,
            event,
            current_path=current_path,
            before_descriptor_bytes=before_descriptor_bytes,
            cleanup_paths=(check_path,) if not check_preexisted else (),
        )
        return event


def rollback_current_descriptor(
    data_root: Path,
    source_id: str,
    target_curated_build_id: str,
    *,
    expected_generation: int,
    reason: str,
    actor: str,
) -> dict[str, Any]:
    """Switch current to an existing approved build as an audited rollback."""

    data_root = Path(data_root)
    if not re.fullmatch(r"[a-z0-9_]+", source_id):
        raise PublishError("ROLLBACK_SOURCE_INVALID")
    if type(expected_generation) is not int or expected_generation < 1:
        raise PublishError("ROLLBACK_GENERATION_INVALID")
    if not isinstance(reason, str) or not reason.strip():
        raise PublishError("ROLLBACK_REASON_REQUIRED")
    if not isinstance(actor, str) or not actor:
        raise PublishError("PUBLISH_ACTOR_INVALID")
    current_path = data_root / "manifests" / "current" / f"{source_id}.json"
    with _source_lock(data_root / "locks" / f"{source_id}.publish.lock"):
        if not current_path.is_file():
            raise PublishError("CURRENT_POINTER_INTEGRITY")
        try:
            current = _read_canonical_object(current_path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, PublishError) as exc:
            raise PublishError("CURRENT_POINTER_INTEGRITY") from exc
        _validate_descriptor_keys(current, source_id, "CURRENT_POINTER_INTEGRITY")
        if (
            current.get("source_id") != source_id
            or current.get("generation") != expected_generation
        ):
            raise PublishError("PUBLISH_CAS_MISMATCH")
        if current.get("serving_snapshot_id") == target_curated_build_id:
            raise PublishError("ROLLBACK_TARGET_IS_CURRENT")
        current_check = _load_current_check(data_root, current)
        _, _, target_manifest_hash = _target_manifest(data_root, source_id, target_curated_build_id)
        target_manifest_relative = f"curated/{source_id}/{target_curated_build_id}/manifest.json"
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        next_generation = expected_generation + 1
        next_descriptor = dict(current)
        next_descriptor.update(
            {
                "generation": next_generation,
                "serving_snapshot_id": target_curated_build_id,
                "serving_curated_build_id": target_curated_build_id,
                "manifest_data_root_relative_path": target_manifest_relative,
                "manifest_sha256": target_manifest_hash,
                "parent_snapshot_id": current.get("serving_snapshot_id"),
                "last_successful_publish_at": now,
                "publisher_actor_id": actor,
            }
        )
        check = current_check
        check_id = (
            f"{source_id}-check-r{next_generation}-"
            f"{sha256_bytes(canonical_json_bytes({'target': target_curated_build_id, 'reason': reason}))[:16]}"
        )
        check.update(
            {
                "check_id": check_id,
                "generation": next_generation,
                "serving_snapshot_id": target_curated_build_id,
                "serving_curated_build_id": target_curated_build_id,
            }
        )
        check_relative = f"checks/{source_id}/{check_id}.json"
        check_path = data_root / check_relative
        check_preexisted = check_path.exists()
        check_bytes = _write_immutable(check_path, check)
        next_descriptor["latest_check_data_root_relative_path"] = check_relative
        next_descriptor["latest_check_sha256"] = sha256_bytes(check_bytes)
        before_descriptor_bytes = current_path.read_bytes()
        before_hash = sha256_bytes(before_descriptor_bytes)
        descriptor_bytes = _replace_current_descriptor(
            current_path, next_descriptor, before_descriptor_bytes
        )
        after_hash = sha256_bytes(descriptor_bytes)
        event = {
            "event_schema_version": 1,
            "event_id": f"rollback-{after_hash}",
            "event_type": "rollback",
            "source_id": source_id,
            "generation": next_generation,
            "before_descriptor_sha256": before_hash,
            "after_descriptor_sha256": after_hash,
            "snapshot_id": target_curated_build_id,
            "target_curated_build_id": target_curated_build_id,
            "actor": actor,
            "reason": reason,
            "published_at": now,
            "result": "success",
            "rollback": True,
            "after_descriptor": next_descriptor,
        }
        _append_event_transactionally(
            data_root,
            source_id,
            event,
            current_path=current_path,
            before_descriptor_bytes=before_descriptor_bytes,
            cleanup_paths=(check_path,) if not check_preexisted else (),
        )
        return event


def recover_current(
    data_root: Path, source_id: str, event_id: str, *, actor: str
) -> dict[str, Any]:
    """Reconstruct a missing current pointer from one named successful event."""

    data_root = Path(data_root)
    if not re.fullmatch(r"[a-z0-9_]+", source_id):
        raise PublishError("RECOVERY_SOURCE_INVALID")
    if not isinstance(event_id, str) or not event_id:
        raise PublishError("PUBLISH_EVENT_NOT_FOUND")
    if not isinstance(actor, str) or not actor:
        raise PublishError("PUBLISH_ACTOR_INVALID")
    current_path = data_root / "manifests" / "current" / f"{source_id}.json"
    with _source_lock(data_root / "locks" / f"{source_id}.publish.lock"):
        if current_path.exists():
            raise PublishError("CURRENT_POINTER_PRESENT")
        event = _read_success_event(data_root, source_id, event_id)
        descriptor = event.get("after_descriptor")
        if not isinstance(descriptor, dict):
            raise PublishError("PUBLISH_EVENT_INVALID")
        _validate_descriptor_keys(descriptor, source_id, "PUBLISH_EVENT_INVALID")
        try:
            descriptor_bytes = canonical_json_bytes(descriptor)
        except (TypeError, ValueError) as exc:
            raise PublishError("PUBLISH_EVENT_INVALID") from exc
        if event.get("after_descriptor_sha256") != sha256_bytes(descriptor_bytes):
            raise PublishError("PUBLISH_EVENT_INVALID")
        if descriptor.get("source_id") != source_id:
            raise PublishError("PUBLISH_EVENT_INVALID")
        target_id = descriptor.get("serving_curated_build_id")
        if not isinstance(target_id, str):
            raise PublishError("PUBLISH_EVENT_INVALID")
        _, _, manifest_hash = _target_manifest(data_root, source_id, target_id)
        if (
            descriptor.get("serving_snapshot_id") != target_id
            or descriptor.get("manifest_sha256") != manifest_hash
        ):
            raise PublishError("PUBLISH_EVENT_INVALID")
        _load_current_check(data_root, descriptor)
        before_hash = None
        before_descriptor_bytes = None
        written = _replace_current_descriptor(current_path, descriptor, before_descriptor_bytes)
        after_hash = sha256_bytes(written)
        if after_hash != event["after_descriptor_sha256"]:
            try:
                _restore_path_bytes(current_path, before_descriptor_bytes)
            except Exception as recovery_exc:
                raise PublishError("PUBLISH_RECOVERY_REQUIRED") from recovery_exc
            raise PublishError("PUBLISH_READBACK_FAILURE")
        recovery_event = {
            "event_schema_version": 1,
            "event_id": f"recover-{after_hash}-{event_id}",
            "event_type": "recover_current",
            "source_id": source_id,
            "generation": descriptor["generation"],
            "before_descriptor_sha256": before_hash,
            "after_descriptor_sha256": after_hash,
            "snapshot_id": target_id,
            "actor": actor,
            "published_at": descriptor.get("last_successful_publish_at"),
            "result": "success",
            "rollback": False,
            "recovered_from_event_id": event_id,
            "after_descriptor": descriptor,
        }
        _append_event_transactionally(
            data_root,
            source_id,
            recovery_event,
            current_path=current_path,
            before_descriptor_bytes=None,
        )
        return recovery_event
