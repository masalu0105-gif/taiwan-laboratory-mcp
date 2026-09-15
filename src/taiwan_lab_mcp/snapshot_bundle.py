"""Redistributable snapshot bundles: export the serving build, install it elsewhere.

Owner decisions: NHI on 2026-09-14 (OD-01 B, ADR 0001) and TFDA on 2026-09-15 (OD-10,
ADR 0002). The bundle carries the raw artifact (the open data license allows redistribution
with attribution), the curated build with its audit evidence and a bundle manifest listing
every file hash. Installing re-verifies every byte, never overwrites a different existing
file, and switches the local current descriptor through the normal generation CAS. Files
are streamed in chunks, so a TFDA database of about 160 MB never sits in memory whole.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import zipfile
import zlib
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from .adapters.base import NHI_NOT_OFFICIAL_NOTE, TFDA_NOT_OFFICIAL_NOTE
from .canonical import canonical_json_bytes, sha256_bytes
from .importers.nhi import NHIImportError, _write_immutable_json
from .importers.nhi import _load_official_raw_revision as _load_nhi_raw_revision
from .importers.tfda import TFDAImportError
from .importers.tfda import _load_official_raw_revision as _load_tfda_raw_revision
from .publish import publish_current_descriptor
from .stores import read_nhi_state
from .tfda_store import read_tfda_state

BUNDLE_MANIFEST_NAME = "bundle-manifest.json"
MIB = 1024 * 1024
# Sized for the TFDA build (owner 2026-09-15, ADR 0002): a 166,920,192-byte database that
# compresses to about 48.5 MB, plus a 16 MB raw ZIP.
MAX_BUNDLE_BYTES = 128 * MIB
MAX_BUNDLE_UNCOMPRESSED_BYTES = 512 * MIB
MAX_BUNDLE_ENTRIES = 256
_MAX_MANIFEST_BYTES = MIB
_CHUNK_BYTES = MIB
_FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
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


@dataclass(frozen=True)
class _Source:
    raw_artifact_name: str
    notice: str
    freshness_policy_version: str
    read_state: Callable[..., Any]
    load_raw_revision: Callable[[Path, str], Any]


_SOURCES = {
    "nhi_fee": _Source(
        "source.csv", NHI_NOT_OFFICIAL_NOTE, "nhi-v1", read_nhi_state, _load_nhi_raw_revision
    ),
    "tfda_devices": _Source(
        "source.zip", TFDA_NOT_OFFICIAL_NOTE, "tfda-v1", read_tfda_state, _load_tfda_raw_revision
    ),
}


class SnapshotBundleError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        super().__init__(f"{code}{(': ' + detail) if detail else ''}")


def _source(source_id: str) -> _Source:
    try:
        return _SOURCES[source_id]
    except (KeyError, TypeError) as exc:
        raise SnapshotBundleError("BUNDLE_SOURCE_UNSUPPORTED", str(source_id)) from exc


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


def _file_chunks(path: Path) -> Iterator[bytes]:
    with path.open("rb") as stream:
        while chunk := stream.read(_CHUNK_BYTES):
            yield chunk


def _digest(chunks: Iterable[bytes]) -> tuple[int, str]:
    size = 0
    digest = hashlib.sha256()
    for chunk in chunks:
        size += len(chunk)
        digest.update(chunk)
    return size, digest.hexdigest()


def _write_new_file(path: Path, chunks: Iterable[bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            for chunk in chunks:
                stream.write(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _tree_files(data_root: Path, relative_dir: str) -> list[tuple[str, Path, int, str]]:
    base = data_root / PurePosixPath(relative_dir)
    files = []
    for path in sorted(base.rglob("*")):
        if path.is_symlink():
            raise SnapshotBundleError("EXPORT_SERVING_INTEGRITY", "symlink in build")
        if path.is_file():
            size, sha256 = _digest(_file_chunks(path))
            files.append((path.relative_to(data_root).as_posix(), path, size, sha256))
    return files


def _add_entry(archive: zipfile.ZipFile, name: str, size: int, chunks: Iterable[bytes]) -> None:
    info = zipfile.ZipInfo(name, date_time=_FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    info.file_size = size
    with archive.open(info, "w") as destination:
        for chunk in chunks:
            destination.write(chunk)


def export_snapshot_bundle(
    data_root: Path,
    source_id: str,
    *,
    output_dir: Path,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Pack the verified, fresh serving build of one source into a release ZIP and checksum."""

    source = _source(source_id)
    data_root = Path(data_root)
    output_dir = Path(output_dir)
    state = source.read_state(data_root, clock=clock)
    if state.availability != "available":
        raise SnapshotBundleError("EXPORT_NO_SERVING_SNAPSHOT")
    if state.status.stale:
        raise SnapshotBundleError("EXPORT_SERVING_STALE", ",".join(state.status.stale_reason_codes))
    try:
        descriptor = _read_json_object(data_root / "manifests" / "current" / f"{source_id}.json")
        build_id = descriptor["serving_curated_build_id"]
        manifest = _read_json_object(
            data_root / PurePosixPath(descriptor["manifest_data_root_relative_path"])
        )
        raw_revision_id = manifest["raw_revision_id"]
        manifest_source = manifest["source"]
    except (KeyError, OSError, TypeError, ValueError) as exc:
        raise SnapshotBundleError("EXPORT_SERVING_INTEGRITY") from exc

    files = _tree_files(data_root, f"raw/{source_id}/{raw_revision_id}") + _tree_files(
        data_root, f"curated/{source_id}/{build_id}"
    )
    bundle_manifest = canonical_json_bytes(
        {
            "bundle_schema_version": 1,
            "source_id": source_id,
            "snapshot_id": build_id,
            "curated_build_id": build_id,
            "raw_revision_id": raw_revision_id,
            "manifest_sha256": descriptor["manifest_sha256"],
            "last_successful_check_at": descriptor["last_successful_check_at"],
            "attribution": manifest_source["attribution"],
            "license_name": manifest_source["license_name"],
            "license_url": manifest_source["license_url"],
            "notice": source.notice,
            "files": [
                {"path": relative, "bytes": size, "sha256": sha256}
                for relative, _, size, sha256 in files
            ],
        }
    )
    name = f"{source_id}-snapshot-{build_id[-64:][:12]}.zip"
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = output_dir / name
    fd, temporary_name = tempfile.mkstemp(prefix=f".{name}.", dir=output_dir)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w+b") as stream:
            with zipfile.ZipFile(stream, "w") as archive:
                _add_entry(archive, BUNDLE_MANIFEST_NAME, len(bundle_manifest), [bundle_manifest])
                for relative, path, size, _ in files:
                    _add_entry(archive, relative, size, _file_chunks(path))
            stream.flush()
            os.fsync(stream.fileno())
        bundle_bytes, bundle_sha256 = _digest(_file_chunks(temporary_path))
        os.replace(temporary_path, bundle_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    checksum_path = output_dir / f"{name}.sha256"
    _write_new_file(checksum_path, [f"{bundle_sha256}  {name}\n".encode("ascii")])
    return {
        "result": "exported",
        "source_id": source_id,
        "snapshot_id": build_id,
        "raw_revision_id": raw_revision_id,
        "bundle_path": str(bundle_path),
        "bundle_sha256": bundle_sha256,
        "bundle_bytes": bundle_bytes,
        "checksum_path": str(checksum_path),
        "file_count": len(files),
    }


def export_nhi_snapshot_bundle(data_root: Path, *, output_dir: Path) -> dict[str, Any]:
    return export_snapshot_bundle(data_root, "nhi_fee", output_dir=output_dir)


def _entry_chunks(archive: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int) -> Iterator[bytes]:
    total = 0
    with archive.open(info) as stream:
        while chunk := stream.read(_CHUNK_BYTES):
            total += len(chunk)
            if total > limit:
                raise SnapshotBundleError("BUNDLE_SIZE_LIMIT", info.filename)
            yield chunk


def _validated_bundle_manifest(payload: bytes) -> dict[str, Any]:
    def invalid(detail: str) -> SnapshotBundleError:
        return SnapshotBundleError("BUNDLE_MANIFEST_INVALID", detail)

    try:
        manifest = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise invalid("not JSON") from exc
    if not isinstance(manifest, dict) or set(manifest) != _MANIFEST_KEYS:
        raise invalid("keys")
    source_id = manifest["source_id"]
    if (
        manifest["bundle_schema_version"] != 1
        or not isinstance(source_id, str)
        or source_id not in _SOURCES
        or not isinstance(manifest["snapshot_id"], str)
        or not re.fullmatch(rf"{source_id}-build-[0-9a-f]{{64}}", manifest["snapshot_id"])
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


def install_snapshot_bundle(
    data_root: Path,
    *,
    source_id: str,
    bundle_path: Path,
    actor: str,
    expected_sha256: str | None = None,
    max_path_length: int | None = _DEFAULT_MAX_PATH_LENGTH,
) -> dict[str, Any]:
    """Verify a release bundle of one source, copy its files into the data root and serve it."""

    source = _source(source_id)
    if not isinstance(actor, str) or not actor.strip():
        raise SnapshotBundleError("BUNDLE_ACTOR_INVALID")
    bundle_path = Path(bundle_path)
    try:
        bundle_size = bundle_path.stat().st_size
        if bundle_size > MAX_BUNDLE_BYTES:
            raise SnapshotBundleError("BUNDLE_SIZE_LIMIT", "bundle")
        with bundle_path.open("rb") as stream:
            magic = stream.read(4)
        _, bundle_sha256 = _digest(_file_chunks(bundle_path))
    except OSError as exc:
        raise SnapshotBundleError("BUNDLE_UNREADABLE") from exc
    if expected_sha256 is not None and expected_sha256.strip().lower() != bundle_sha256:
        raise SnapshotBundleError("BUNDLE_SHA256_MISMATCH")
    if magic != b"PK\x03\x04":
        raise SnapshotBundleError("BUNDLE_MAGIC_MISMATCH")

    data_root = Path(data_root)
    written = 0
    try:
        with zipfile.ZipFile(bundle_path) as archive:
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
                b"".join(_entry_chunks(archive, by_name[BUNDLE_MANIFEST_NAME], _MAX_MANIFEST_BYTES))
            )
            if manifest["source_id"] != source_id:
                raise SnapshotBundleError("BUNDLE_SOURCE_MISMATCH", manifest["source_id"])
            items = {item["path"]: item for item in manifest["files"]}
            archived = set(by_name) - {BUNDLE_MANIFEST_NAME}
            if archived - set(items):
                raise SnapshotBundleError("BUNDLE_ENTRY_UNEXPECTED")
            if set(items) - archived:
                raise SnapshotBundleError("BUNDLE_ENTRY_MISSING")
            build_id = manifest["snapshot_id"]
            raw_revision_id = manifest["raw_revision_id"]
            raw_prefix = f"raw/{source_id}/{raw_revision_id}/"
            build_prefix = f"curated/{source_id}/{build_id}/"
            for path in items:
                if _unsafe_path(path) or not path.startswith((raw_prefix, build_prefix)):
                    raise SnapshotBundleError("BUNDLE_PATH_INVALID", path)
            remaining = MAX_BUNDLE_UNCOMPRESSED_BYTES
            for path, item in items.items():
                size, sha256 = _digest(
                    _entry_chunks(archive, by_name[path], min(item["bytes"], remaining))
                )
                if size != item["bytes"] or sha256 != item["sha256"]:
                    raise SnapshotBundleError("BUNDLE_FILE_HASH_MISMATCH", path)
                remaining -= size

            curated_manifest_path = f"{build_prefix}manifest.json"
            required = {
                f"{raw_prefix}artifacts/{source.raw_artifact_name}",
                f"{raw_prefix}fetch.json",
                curated_manifest_path,
                f"{build_prefix}data.sqlite3",
            }
            if not required <= set(items):
                raise SnapshotBundleError("BUNDLE_MANIFEST_INVALID", "required build files missing")
            if items[curated_manifest_path]["sha256"] != manifest["manifest_sha256"]:
                raise SnapshotBundleError("BUNDLE_FILE_HASH_MISMATCH", curated_manifest_path)
            try:
                curated_manifest = json.loads(
                    b"".join(
                        _entry_chunks(archive, by_name[curated_manifest_path], _MAX_MANIFEST_BYTES)
                    ).decode("utf-8")
                )
                raw_artifact_sha256 = curated_manifest["artifacts"][0]["sha256"]
            except (KeyError, IndexError, TypeError, UnicodeDecodeError, ValueError) as exc:
                raise SnapshotBundleError("BUNDLE_CONTENT_INVALID", "curated manifest") from exc

            if max_path_length is not None:
                absolute_root = os.path.abspath(data_root)
                longest = max(
                    len(os.path.join(absolute_root, *PurePosixPath(path).parts))
                    + _TEMP_NAME_OVERHEAD
                    for path in items
                )
                if longest > max_path_length:
                    raise SnapshotBundleError(
                        "BUNDLE_PATH_TOO_LONG", f"{longest} characters > {max_path_length}"
                    )
            for path, item in items.items():
                target = data_root / PurePosixPath(path)
                if target.exists() and (
                    not target.is_file()
                    or _digest(_file_chunks(target)) != (item["bytes"], item["sha256"])
                ):
                    raise SnapshotBundleError("BUNDLE_FILE_CONFLICT", path)

            current_path = data_root / "manifests" / "current" / f"{source_id}.json"
            current = None
            if current_path.is_file():
                try:
                    current = _read_json_object(current_path)
                except (OSError, ValueError) as exc:
                    raise SnapshotBundleError("CURRENT_POINTER_INTEGRITY") from exc

            try:
                for path in sorted(items):
                    target = data_root / PurePosixPath(path)
                    if not target.exists():
                        _write_new_file(
                            target, _entry_chunks(archive, by_name[path], items[path]["bytes"])
                        )
                        written += 1
            except OSError as exc:
                raise SnapshotBundleError("BUNDLE_WRITE_FAILED", type(exc).__name__) from exc
    except SnapshotBundleError:
        raise
    except (zipfile.BadZipFile, zlib.error, EOFError, OSError, RuntimeError) as exc:
        raise SnapshotBundleError("BUNDLE_CORRUPT") from exc
    except NotImplementedError as exc:
        raise SnapshotBundleError("BUNDLE_CORRUPT", "unsupported compression") from exc

    try:
        source.load_raw_revision(data_root, raw_revision_id)
    except (NHIImportError, TFDAImportError) as exc:
        raise SnapshotBundleError("BUNDLE_CONTENT_INVALID", exc.code) from exc

    if current is not None and current.get("serving_snapshot_id") == build_id:
        return {
            "result": "already_installed",
            "source_id": source_id,
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
    check_id = f"{source_id}-check-install-{bundle_sha256[:32]}-g{generation}"
    check_relative = f"checks/{source_id}/{check_id}.json"
    operational = {
        "latest_seen_version": None,
        "latest_seen_artifact_sha256": raw_artifact_sha256,
        "latest_candidate_id": None,
        "latest_candidate_status": "none",
        "check_result": "success",
        "failed_stage": None,
        "error_code": None,
        "stale": False,
        "stale_reason_codes": [],
        "freshness_policy_version": source.freshness_policy_version,
        "content_age_status": "unknown",
        "content_age_evidence": None,
    }
    check = {
        "check_schema_version": 1,
        "check_id": check_id,
        "source_id": source_id,
        "generation": generation,
        "serving_snapshot_id": build_id,
        "serving_curated_build_id": build_id,
        "checked_at": checked_at,
        **operational,
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
        "source_id": source_id,
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
        **operational,
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
        "source_id": source_id,
        "snapshot_id": build_id,
        "raw_revision_id": raw_revision_id,
        "generation": generation,
        "publish_event_id": event["event_id"],
        "bundle_sha256": bundle_sha256,
        "files_written": written,
    }


def install_nhi_snapshot_bundle(data_root: Path, **kwargs: Any) -> dict[str, Any]:
    return install_snapshot_bundle(data_root, source_id="nhi_fee", **kwargs)
