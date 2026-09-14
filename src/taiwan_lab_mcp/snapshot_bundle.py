"""Redistributable NHI snapshot bundle: export the serving build, install it elsewhere.

Owner decision 2026-09-14 (OD-01 B): owner-reviewed NHI snapshots are published as
GitHub Release assets. The bundle carries the raw CSV (license allows redistribution with
attribution), the curated build with its audit evidence and a bundle manifest listing
every file hash. Installing re-verifies every byte, never overwrites a different existing
file, and switches the local current descriptor through the normal generation CAS.
"""

from __future__ import annotations

import io
import json
import os
import re
import zipfile
import zlib
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from .adapters.base import NHI_NOT_OFFICIAL_NOTE
from .canonical import canonical_json_bytes, sha256_bytes
from .importers.nhi import NHIImportError, _load_official_raw_revision, _write_immutable_json
from .publish import publish_current_descriptor
from .stores import read_nhi_state
from .sync import _write_new_file

BUNDLE_MANIFEST_NAME = "bundle-manifest.json"
MIB = 1024 * 1024
MAX_BUNDLE_BYTES = 64 * MIB
MAX_BUNDLE_UNCOMPRESSED_BYTES = 256 * MIB
MAX_BUNDLE_ENTRIES = 256
_MAX_MANIFEST_BYTES = MIB
_FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
_BUILD_ID_RE = re.compile(r"^nhi_fee-build-[0-9a-f]{64}$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_SYMLINK_MODE = 0o120000
_MANIFEST_KEYS = frozenset(
    {
        "bundle_schema_version",
        "source_id",
        "snapshot_id",
        "curated_build_id",
        "raw_revision_id",
        "manifest_sha256",
        "last_successful_check_at",
        "attribution",
        "license_name",
        "license_url",
        "notice",
        "files",
    }
)


class SnapshotBundleError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        super().__init__(f"{code}{(': ' + detail) if detail else ''}")


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _unsafe_path(name: str) -> bool:
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or _DRIVE_RE.match(normalized):
        return True
    return any(part in {"", ".", ".."} for part in normalized.split("/"))


def _read_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON document must be an object")
    return value


def _tree_files(data_root: Path, relative_dir: str) -> list[tuple[str, bytes]]:
    base = data_root / PurePosixPath(relative_dir)
    files = []
    for path in sorted(base.rglob("*")):
        if path.is_symlink():
            raise SnapshotBundleError("EXPORT_SERVING_INTEGRITY", "symlink in build")
        if path.is_file():
            files.append((path.relative_to(data_root).as_posix(), path.read_bytes()))
    return files


def export_nhi_snapshot_bundle(data_root: Path, *, output_dir: Path) -> dict[str, Any]:
    """Pack the verified, fresh serving NHI build into one release ZIP plus a checksum."""

    data_root = Path(data_root)
    output_dir = Path(output_dir)
    state = read_nhi_state(data_root)
    if state.availability != "available":
        raise SnapshotBundleError("EXPORT_NO_SERVING_SNAPSHOT")
    if state.status.stale:
        raise SnapshotBundleError("EXPORT_SERVING_STALE", ",".join(state.status.stale_reason_codes))
    try:
        descriptor = _read_json_object(data_root / "manifests" / "current" / "nhi_fee.json")
        build_id = descriptor["serving_curated_build_id"]
        manifest = _read_json_object(
            data_root / PurePosixPath(descriptor["manifest_data_root_relative_path"])
        )
        raw_revision_id = manifest["raw_revision_id"]
        source = manifest["source"]
    except (KeyError, OSError, TypeError, ValueError) as exc:
        raise SnapshotBundleError("EXPORT_SERVING_INTEGRITY") from exc

    files = _tree_files(data_root, f"raw/nhi_fee/{raw_revision_id}") + _tree_files(
        data_root, f"curated/nhi_fee/{build_id}"
    )
    bundle_manifest = {
        "bundle_schema_version": 1,
        "source_id": "nhi_fee",
        "snapshot_id": build_id,
        "curated_build_id": build_id,
        "raw_revision_id": raw_revision_id,
        "manifest_sha256": descriptor["manifest_sha256"],
        "last_successful_check_at": descriptor["last_successful_check_at"],
        "attribution": source["attribution"],
        "license_name": source["license_name"],
        "license_url": source["license_url"],
        "notice": NHI_NOT_OFFICIAL_NOTE,
        "files": [
            {"path": path, "bytes": len(payload), "sha256": sha256_bytes(payload)}
            for path, payload in files
        ],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in [
            (BUNDLE_MANIFEST_NAME, canonical_json_bytes(bundle_manifest))
        ] + files:
            info = zipfile.ZipInfo(name, date_time=_FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, payload)
    bundle_bytes = buffer.getvalue()
    bundle_sha256 = sha256_bytes(bundle_bytes)
    name = f"nhi_fee-snapshot-{build_id[-64:][:12]}.zip"
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = output_dir / name
    checksum_path = output_dir / f"{name}.sha256"
    _write_new_file(bundle_path, bundle_bytes)
    _write_new_file(checksum_path, f"{bundle_sha256}  {name}\n".encode("ascii"))
    return {
        "result": "exported",
        "snapshot_id": build_id,
        "raw_revision_id": raw_revision_id,
        "bundle_path": str(bundle_path),
        "bundle_sha256": bundle_sha256,
        "bundle_bytes": len(bundle_bytes),
        "checksum_path": str(checksum_path),
        "file_count": len(files),
    }


def _read_entry(archive: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int) -> bytes:
    chunks = []
    total = 0
    with archive.open(info) as stream:
        while True:
            chunk = stream.read(MIB)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise SnapshotBundleError("BUNDLE_SIZE_LIMIT", info.filename)
            chunks.append(chunk)
    return b"".join(chunks)


def _validated_bundle_manifest(payload: bytes) -> dict[str, Any]:
    def invalid(detail: str) -> SnapshotBundleError:
        return SnapshotBundleError("BUNDLE_MANIFEST_INVALID", detail)

    try:
        manifest = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise invalid("not JSON") from exc
    if not isinstance(manifest, dict) or set(manifest) != _MANIFEST_KEYS:
        raise invalid("keys")
    if (
        manifest["bundle_schema_version"] != 1
        or manifest["source_id"] != "nhi_fee"
        or not isinstance(manifest["snapshot_id"], str)
        or not _BUILD_ID_RE.fullmatch(manifest["snapshot_id"])
        or manifest["curated_build_id"] != manifest["snapshot_id"]
        or not isinstance(manifest["raw_revision_id"], str)
        or not _HEX64_RE.fullmatch(manifest["raw_revision_id"])
        or not isinstance(manifest["manifest_sha256"], str)
        or not _HEX64_RE.fullmatch(manifest["manifest_sha256"])
    ):
        raise invalid("identity")
    try:
        checked_at = datetime.fromisoformat(
            str(manifest["last_successful_check_at"]).replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise invalid("last_successful_check_at") from exc
    if checked_at.utcoffset() is None:
        raise invalid("last_successful_check_at")
    files = manifest["files"]
    if not isinstance(files, list) or not files:
        raise invalid("files")
    for item in files:
        if (
            not isinstance(item, dict)
            or set(item) != {"path", "bytes", "sha256"}
            or not isinstance(item["path"], str)
            or type(item["bytes"]) is not int
            or item["bytes"] < 0
            or not isinstance(item["sha256"], str)
            or not _HEX64_RE.fullmatch(item["sha256"])
        ):
            raise invalid("file entry")
    if len({item["path"] for item in files}) != len(files):
        raise invalid("duplicate file path")
    return manifest


# Windows without the LongPathsEnabled policy fails above MAX_PATH (260 including NUL).
_DEFAULT_MAX_PATH_LENGTH = 259 if os.name == "nt" else None
# _write_new_file creates ".<name>.<8 random characters>" next to each target first.
_TEMP_NAME_OVERHEAD = len("..") + 8


def install_nhi_snapshot_bundle(
    data_root: Path,
    *,
    bundle_path: Path,
    actor: str,
    expected_sha256: str | None = None,
    max_path_length: int | None = _DEFAULT_MAX_PATH_LENGTH,
) -> dict[str, Any]:
    """Verify a release bundle, copy its files into the data root and serve it."""

    if not isinstance(actor, str) or not actor.strip():
        raise SnapshotBundleError("BUNDLE_ACTOR_INVALID")
    try:
        payload = Path(bundle_path).read_bytes()
    except OSError as exc:
        raise SnapshotBundleError("BUNDLE_UNREADABLE") from exc
    if len(payload) > MAX_BUNDLE_BYTES:
        raise SnapshotBundleError("BUNDLE_SIZE_LIMIT", "bundle")
    bundle_sha256 = sha256_bytes(payload)
    if expected_sha256 is not None and expected_sha256.strip().lower() != bundle_sha256:
        raise SnapshotBundleError("BUNDLE_SHA256_MISMATCH")
    if not payload.startswith(b"PK\x03\x04"):
        raise SnapshotBundleError("BUNDLE_MAGIC_MISMATCH")

    contents: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_BUNDLE_ENTRIES:
                raise SnapshotBundleError("BUNDLE_ENTRY_COUNT")
            names = [info.filename for info in infos]
            if len(set(names)) != len(names):
                raise SnapshotBundleError("BUNDLE_ENTRY_UNEXPECTED", "duplicate entry")
            for info in infos:
                if (
                    _unsafe_path(info.filename)
                    or info.is_dir()
                    or (info.external_attr >> 16) & 0o170000 == _SYMLINK_MODE
                    or info.flag_bits & 0x1
                ):
                    raise SnapshotBundleError("BUNDLE_PATH_INVALID", info.filename)
            by_name = {info.filename: info for info in infos}
            if BUNDLE_MANIFEST_NAME not in by_name:
                raise SnapshotBundleError("BUNDLE_MANIFEST_INVALID", "missing")
            manifest = _validated_bundle_manifest(
                _read_entry(archive, by_name[BUNDLE_MANIFEST_NAME], _MAX_MANIFEST_BYTES)
            )
            listed = {item["path"] for item in manifest["files"]}
            archived = set(by_name) - {BUNDLE_MANIFEST_NAME}
            if archived - listed:
                raise SnapshotBundleError("BUNDLE_ENTRY_UNEXPECTED")
            if listed - archived:
                raise SnapshotBundleError("BUNDLE_ENTRY_MISSING")
            build_id = manifest["snapshot_id"]
            raw_revision_id = manifest["raw_revision_id"]
            allowed = (f"raw/nhi_fee/{raw_revision_id}/", f"curated/nhi_fee/{build_id}/")
            for path in listed:
                if _unsafe_path(path) or not path.startswith(allowed):
                    raise SnapshotBundleError("BUNDLE_PATH_INVALID", path)
            remaining = MAX_BUNDLE_UNCOMPRESSED_BYTES
            for item in manifest["files"]:
                data = _read_entry(archive, by_name[item["path"]], min(item["bytes"], remaining))
                if len(data) != item["bytes"] or sha256_bytes(data) != item["sha256"]:
                    raise SnapshotBundleError("BUNDLE_FILE_HASH_MISMATCH", item["path"])
                remaining -= len(data)
                contents[item["path"]] = data
    except SnapshotBundleError:
        raise
    except (zipfile.BadZipFile, zlib.error, EOFError, OSError, RuntimeError) as exc:
        raise SnapshotBundleError("BUNDLE_CORRUPT") from exc
    except NotImplementedError as exc:
        raise SnapshotBundleError("BUNDLE_CORRUPT", "unsupported compression") from exc

    curated_manifest_path = f"curated/nhi_fee/{build_id}/manifest.json"
    required = {
        f"raw/nhi_fee/{raw_revision_id}/artifacts/source.csv",
        f"raw/nhi_fee/{raw_revision_id}/fetch.json",
        curated_manifest_path,
        f"curated/nhi_fee/{build_id}/data.sqlite3",
    }
    if not required <= set(contents):
        raise SnapshotBundleError("BUNDLE_MANIFEST_INVALID", "required build files missing")
    if sha256_bytes(contents[curated_manifest_path]) != manifest["manifest_sha256"]:
        raise SnapshotBundleError("BUNDLE_FILE_HASH_MISMATCH", curated_manifest_path)
    try:
        curated_manifest = json.loads(contents[curated_manifest_path].decode("utf-8"))
        raw_artifact_sha256 = curated_manifest["artifacts"][0]["sha256"]
    except (KeyError, IndexError, TypeError, UnicodeDecodeError, ValueError) as exc:
        raise SnapshotBundleError("BUNDLE_CONTENT_INVALID", "curated manifest") from exc

    data_root = Path(data_root)
    if max_path_length is not None:
        absolute_root = os.path.abspath(data_root)
        longest = max(
            len(os.path.join(absolute_root, *PurePosixPath(path).parts)) + _TEMP_NAME_OVERHEAD
            for path in contents
        )
        if longest > max_path_length:
            raise SnapshotBundleError(
                "BUNDLE_PATH_TOO_LONG", f"{longest} characters > {max_path_length}"
            )
    for path, data in contents.items():
        target = data_root / PurePosixPath(path)
        if target.exists() and (not target.is_file() or target.read_bytes() != data):
            raise SnapshotBundleError("BUNDLE_FILE_CONFLICT", path)

    current_path = data_root / "manifests" / "current" / "nhi_fee.json"
    current = None
    if current_path.is_file():
        try:
            current = _read_json_object(current_path)
        except (OSError, ValueError) as exc:
            raise SnapshotBundleError("CURRENT_POINTER_INTEGRITY") from exc

    written = 0
    try:
        for path in sorted(contents):
            target = data_root / PurePosixPath(path)
            if not target.exists():
                _write_new_file(target, contents[path])
                written += 1
    except OSError as exc:
        raise SnapshotBundleError("BUNDLE_WRITE_FAILED", type(exc).__name__) from exc
    try:
        _load_official_raw_revision(data_root, raw_revision_id)
    except NHIImportError as exc:
        raise SnapshotBundleError("BUNDLE_CONTENT_INVALID", exc.code) from exc

    if current is not None and current.get("serving_snapshot_id") == build_id:
        return {
            "result": "already_installed",
            "snapshot_id": build_id,
            "raw_revision_id": raw_revision_id,
            "generation": current.get("generation"),
            "bundle_sha256": bundle_sha256,
            "files_written": written,
        }

    expected_generation = current["generation"] if current is not None else 0
    expected_parent = current["serving_snapshot_id"] if current is not None else None
    generation = expected_generation + 1
    # The bundle carries the publisher's last successful upstream check of this exact
    # raw artifact. This machine has not checked upstream itself, so freshness keeps
    # counting from that time and turns overdue unless a local check runs.
    checked_at = manifest["last_successful_check_at"]
    check_id = f"nhi_fee-check-install-{bundle_sha256[:32]}-g{generation}"
    check_relative = f"checks/nhi_fee/{check_id}.json"
    check = {
        "check_schema_version": 1,
        "check_id": check_id,
        "source_id": "nhi_fee",
        "generation": generation,
        "serving_snapshot_id": build_id,
        "serving_curated_build_id": build_id,
        "checked_at": checked_at,
        "latest_seen_version": None,
        "latest_seen_artifact_sha256": raw_artifact_sha256,
        "latest_candidate_id": None,
        "latest_candidate_status": "none",
        "check_result": "success",
        "failed_stage": None,
        "error_code": None,
        "stale": False,
        "stale_reason_codes": [],
        "freshness_policy_version": "nhi-v1",
        "content_age_status": "unknown",
        "content_age_evidence": None,
    }
    check_path = data_root / PurePosixPath(check_relative)
    try:
        _write_immutable_json(check_path, check)
    except OSError as exc:
        raise SnapshotBundleError("BUNDLE_WRITE_FAILED", type(exc).__name__) from exc
    except NHIImportError as exc:
        raise SnapshotBundleError("BUNDLE_FILE_CONFLICT", check_relative) from exc
    descriptor = {
        "descriptor_schema_version": 1,
        "source_id": "nhi_fee",
        "generation": generation,
        "serving_snapshot_id": build_id,
        "serving_curated_build_id": build_id,
        "manifest_data_root_relative_path": curated_manifest_path,
        "manifest_sha256": manifest["manifest_sha256"],
        "parent_snapshot_id": expected_parent,
        "last_successful_publish_at": _utc_now_text(),
        "publisher_actor_id": actor,
        "last_check_at": checked_at,
        "last_successful_check_at": checked_at,
        "latest_seen_version": None,
        "latest_seen_artifact_sha256": raw_artifact_sha256,
        "latest_candidate_id": None,
        "latest_candidate_status": "none",
        "check_result": "success",
        "failed_stage": None,
        "error_code": None,
        "stale": False,
        "stale_reason_codes": [],
        "freshness_policy_version": "nhi-v1",
        "content_age_status": "unknown",
        "content_age_evidence": None,
        "latest_check_data_root_relative_path": check_relative,
        "latest_check_sha256": sha256_bytes(check_path.read_bytes()),
    }
    event = publish_current_descriptor(
        data_root,
        descriptor,
        expected_generation=expected_generation,
        expected_parent_snapshot_id=expected_parent,
        actor=actor,
    )
    return {
        "result": "installed",
        "snapshot_id": build_id,
        "raw_revision_id": raw_revision_id,
        "generation": generation,
        "publish_event_id": event["event_id"],
        "bundle_sha256": bundle_sha256,
        "files_written": written,
    }
