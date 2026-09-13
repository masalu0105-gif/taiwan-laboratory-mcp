from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from functools import lru_cache
from importlib.resources import files
from pathlib import Path, PurePosixPath
from typing import Any

from .canonical import canonical_json_bytes

_REPORT_KEYS = {
    "acceptance_report_schema_version",
    "release_id",
    "requirement_id",
    "node_id",
    "node_status",
    "collected_node_count",
    "exit_code",
    "test_output_sha256",
    "stdout_sha256",
    "stderr_sha256",
    "application_build_inventory_sha256",
    "golden_qualification_sha256",
    "source_review_evidence_sha256",
    "evidence_refs",
    "gate_disposition",
}
_NODE_STATUSES = {"collected", "missing", "skipped", "xfail", "planned", "docs_only"}
_GATE_DISPOSITIONS = {"passed", "not_closed", "failed", "blocked"}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_REQUIREMENT_ID = re.compile(r"^[A-Z][A-Z0-9-]{2,31}$")


class AcceptanceReportError(ValueError):
    """Raised when release evidence cannot be safely recorded."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"{code}: {detail}")


def _require_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise AcceptanceReportError("INVALID_HASH", f"{field} must be lowercase SHA-256")
    return value


def _require_identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise AcceptanceReportError("INVALID_IDENTIFIER", f"{field} is invalid")
    return value


@lru_cache(maxsize=1)
def _node_registry() -> dict[tuple[str, str], str]:
    path = files("taiwan_lab_mcp").joinpath("contracts", "acceptance-contract-v1.json")

    def collect(items: list[tuple[str, Any]]) -> dict[str, Any]:
        keys = [key for key, _ in items]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate JSON key")
        return dict(items)

    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=collect)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise AcceptanceReportError(
            "REGISTRY_INVALID", "acceptance node registry cannot be read"
        ) from exc
    if not isinstance(value, dict) or set(value) != {"acceptance_contract_version", "nodes"}:
        raise AcceptanceReportError("REGISTRY_INVALID", "acceptance node registry schema invalid")
    if value["acceptance_contract_version"] != "acceptance-contract-v1":
        raise AcceptanceReportError("REGISTRY_INVALID", "unsupported acceptance registry version")
    nodes = value["nodes"]
    if not isinstance(nodes, list) or not nodes:
        raise AcceptanceReportError("REGISTRY_INVALID", "acceptance node registry is empty")
    registry: dict[tuple[str, str], str] = {}
    for node in nodes:
        if not isinstance(node, dict) or set(node) != {
            "requirement_id",
            "node_id",
            "implementation_status",
        }:
            raise AcceptanceReportError("REGISTRY_INVALID", "acceptance node entry is invalid")
        requirement_id = node["requirement_id"]
        node_id = node["node_id"]
        status = node["implementation_status"]
        if (
            not isinstance(requirement_id, str)
            or _REQUIREMENT_ID.fullmatch(requirement_id) is None
            or not isinstance(node_id, str)
            or not node_id.strip()
            or not isinstance(status, str)
            or status not in {"executable", "planned"}
        ):
            raise AcceptanceReportError(
                "REGISTRY_INVALID", "acceptance node entry value is invalid"
            )
        key = (requirement_id, node_id)
        if key in registry:
            raise AcceptanceReportError("REGISTRY_INVALID", "duplicate acceptance node")
        registry[key] = status
    return registry


def _evidence_file(data_root: Path, relative_path: Any, index: int) -> Path:
    if not isinstance(relative_path, str) or not relative_path or "\\" in relative_path:
        raise AcceptanceReportError("INVALID_EVIDENCE_PATH", f"evidence {index} path is invalid")
    path = PurePosixPath(relative_path)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise AcceptanceReportError("INVALID_EVIDENCE_PATH", f"evidence {index} path is invalid")
    root = data_root.resolve()
    candidate = (data_root / Path(*path.parts)).resolve()
    if candidate == root or not candidate.is_relative_to(root) or not candidate.is_file():
        raise AcceptanceReportError("INVALID_EVIDENCE_PATH", f"evidence {index} file unavailable")
    return candidate


def validate_acceptance_report(data_root: Path, report: dict[str, Any]) -> dict[str, Any]:
    """Validate caller-supplied release evidence without deriving an outcome."""

    if not isinstance(report, dict) or set(report) != _REPORT_KEYS:
        raise AcceptanceReportError("REPORT_SCHEMA_INVALID", "report keys must match schema v1")
    if report["acceptance_report_schema_version"] != 1:
        raise AcceptanceReportError("REPORT_SCHEMA_INVALID", "unsupported report schema version")
    _require_identifier(report["release_id"], "release_id")
    requirement_id = report["requirement_id"]
    if not isinstance(requirement_id, str) or _REQUIREMENT_ID.fullmatch(requirement_id) is None:
        raise AcceptanceReportError("INVALID_IDENTIFIER", "requirement_id is invalid")
    if not isinstance(report["node_id"], str) or not report["node_id"].strip():
        raise AcceptanceReportError("REPORT_SCHEMA_INVALID", "node_id is required")
    node_status = report["node_status"]
    if not isinstance(node_status, str) or node_status not in _NODE_STATUSES:
        raise AcceptanceReportError("REPORT_SCHEMA_INVALID", "node_status is invalid")
    gate_disposition = report["gate_disposition"]
    if not isinstance(gate_disposition, str) or gate_disposition not in _GATE_DISPOSITIONS:
        raise AcceptanceReportError("REPORT_SCHEMA_INVALID", "gate_disposition is invalid")
    registry_status = _node_registry().get((requirement_id, report["node_id"]))
    if registry_status is None:
        raise AcceptanceReportError(
            "NODE_NOT_REGISTERED", "requirement/node is absent from acceptance registry"
        )
    if registry_status == "planned" and report["node_status"] != "planned":
        raise AcceptanceReportError(
            "NODE_NOT_EXECUTABLE", "planned registry node is not executable"
        )
    collected_count = report["collected_node_count"]
    if (
        isinstance(collected_count, bool)
        or not isinstance(collected_count, int)
        or collected_count < 0
    ):
        raise AcceptanceReportError("REPORT_SCHEMA_INVALID", "collected_node_count is invalid")
    exit_code = report["exit_code"]
    if isinstance(exit_code, bool) or not isinstance(exit_code, int):
        raise AcceptanceReportError("REPORT_SCHEMA_INVALID", "exit_code is invalid")

    for field in (
        "test_output_sha256",
        "stdout_sha256",
        "stderr_sha256",
        "application_build_inventory_sha256",
        "golden_qualification_sha256",
        "source_review_evidence_sha256",
    ):
        _require_sha256(report[field], field)

    evidence_refs = report["evidence_refs"]
    if not isinstance(evidence_refs, list) or not evidence_refs:
        raise AcceptanceReportError("REPORT_SCHEMA_INVALID", "evidence_refs must not be empty")
    for index, evidence in enumerate(evidence_refs):
        if not isinstance(evidence, dict) or set(evidence) != {"path", "sha256"}:
            raise AcceptanceReportError("REPORT_SCHEMA_INVALID", f"evidence {index} is invalid")
        path = _evidence_file(Path(data_root), evidence["path"], index)
        digest = _require_sha256(evidence["sha256"], f"evidence_refs[{index}].sha256")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != digest:
            raise AcceptanceReportError("EVIDENCE_HASH_MISMATCH", f"evidence {index} hash mismatch")

    if gate_disposition == "passed" and (
        node_status != "collected" or collected_count < 1 or exit_code != 0
    ):
        raise AcceptanceReportError(
            "NODE_NOT_PASSABLE",
            "passed requires a collected node, positive collection count, and exit code 0",
        )
    return report


def write_acceptance_report(data_root: Path, report: dict[str, Any]) -> Path:
    """Write one canonical, immutable PRD/SDD acceptance report."""

    validate_acceptance_report(Path(data_root), report)
    payload = canonical_json_bytes(report)
    release_id = report["release_id"]
    requirement_id = report["requirement_id"]
    root = Path(data_root).resolve()
    path = root / "reports" / "acceptance" / release_id / f"{requirement_id}.json"
    if not path.resolve(strict=False).is_relative_to(root):
        raise AcceptanceReportError("INVALID_REPORT_PATH", "report path escapes data root")
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise AcceptanceReportError("INVALID_REPORT_PATH", "report target must be a regular file")
    if path.exists():
        if path.read_bytes() != payload:
            raise AcceptanceReportError(
                "IMMUTABLE_REPORT_CONFLICT", "report already exists with different bytes"
            )
        return path
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
    return path
