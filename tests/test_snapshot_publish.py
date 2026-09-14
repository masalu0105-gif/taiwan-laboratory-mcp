import json
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest


def test_sdd_audit_01_subject_digest_binds_all_evidence(tmp_path, monkeypatch):
    from taiwan_lab_mcp.adapters.nhi import NHIAdapter
    from taiwan_lab_mcp.audit import compute_review_subject_digest
    from taiwan_lab_mcp.canonical import sha256_bytes
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot
    from taiwan_lab_mcp.nhi_source import nhi_discovery_metadata_sha256

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()
    built = build_nhi_snapshot(payload, tmp_path)
    build_dir = tmp_path / "curated" / "nhi_fee" / built["snapshot_id"]
    manifest_path = build_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    evidence = manifest["audit_evidence"]
    assert manifest["discovery_metadata_sha256"] == nhi_discovery_metadata_sha256(
        {
            "landing_url": "https://data.gov.tw/dataset/174450",
            "publisher_oid": "A21030000I",
            "dataset_id": "174450",
            "license_name": "政府資料開放授權條款－第 1 版",
            "license_url": "https://data.gov.tw/license",
            "official_version_label_raw": None,
            "official_modified_at_raw": None,
            "official_modified_at_precision": None,
            "official_modified_timezone_known": False,
        }
    )

    for key in ("validation", "qualification_candidate", "golden_qualification"):
        reference = evidence[key]
        path = tmp_path / Path(reference["data_root_relative_path"])
        assert path.is_file()
        assert sha256_bytes(path.read_bytes()) == reference["sha256"]
    assert [item["gate_id"] for item in evidence["reviews"]] == manifest["review"][
        "completed_gates"
    ]
    assert manifest["review_subject_digest"] == compute_review_subject_digest(
        manifest,
        curated_db_sha256=manifest["publication"]["curated_sha256"],
        validation_report_sha256=evidence["validation"]["sha256"],
        qualification_candidate_sha256=evidence["qualification_candidate"]["sha256"],
    )

    validation_path = tmp_path / Path(evidence["validation"]["data_root_relative_path"])
    validation_path.write_bytes(b"tampered validation")
    monkeypatch.setenv("TAIWAN_LAB_DATA_MODE", "official_snapshot")
    monkeypatch.setenv("TAIWAN_LAB_DATA_DIR", str(tmp_path))
    result = NHIAdapter().get_points("09006C")
    assert result.result_status == "data_unavailable"
    assert result.availability_reason_code == "serving_integrity_failure"
    assert result.items == []
    assert result.provenance is None

    from taiwan_lab_mcp.acceptance import _node_registry

    assert (
        _node_registry()[
            (
                "SDD-AUDIT-01",
                "tests/test_snapshot_publish.py::test_sdd_audit_01_subject_digest_binds_all_evidence",
            )
        ]
        == "executable"
    )


def test_sdd_pub_01_availability_descriptor_is_atomic_under_concurrency(tmp_path):
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot

    def payload(code: str) -> bytes:
        return (
            "\ufeff"
            + ",".join(NHI_COLUMNS)
            + "\n"
            + f"{code},0,20120101,29101231,HbA1c,醣化血紅素,\n"
        ).encode()

    build_nhi_snapshot(payload("09006C"), tmp_path)
    second_root = tmp_path / "second-build"
    second = build_nhi_snapshot(payload("09007C"), second_root)
    for relative in (
        Path("raw") / "nhi_fee" / second["raw_revision_id"],
        Path("curated") / "nhi_fee" / second["snapshot_id"],
        Path("checks") / "nhi_fee" / f"nhi_fee-check-{second['snapshot_id'].split('-')[-1]}.json",
    ):
        source = second_root / relative
        target = tmp_path / relative
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    barrier = tmp_path / "barrier.ready"
    child = """
import json
import sys
import time
from pathlib import Path
from taiwan_lab_mcp.publish import PublishError, rollback_current_descriptor

root = Path(sys.argv[1])
barrier = Path(sys.argv[2])
actor = sys.argv[3]
while not barrier.exists():
    time.sleep(0.01)
try:
    result = rollback_current_descriptor(
        root, "nhi_fee", sys.argv[4], expected_generation=1,
        reason="two-process CAS test", actor=actor,
    )
    print(json.dumps({"result": result["result"]}))
except PublishError as exc:
    print(json.dumps({"error_code": exc.code}))
"""
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                child,
                str(tmp_path),
                str(barrier),
                actor,
                second["snapshot_id"],
            ],
            cwd=str(Path.cwd()),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for actor in ("process-a", "process-b")
    ]
    try:
        barrier.write_bytes(b"ready")
        outputs = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=15)
            assert process.returncode == 0, stderr
            outputs.append(json.loads(stdout.strip()))
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait()

    results = [output.get("result", output.get("error_code")) for output in outputs]
    assert results.count("success") == 1
    assert (
        sum(result in {"PUBLISH_CAS_MISMATCH", "ROLLBACK_TARGET_IS_CURRENT"} for result in results)
        == 1
    )
    descriptor = json.loads(
        (tmp_path / "manifests" / "current" / "nhi_fee.json").read_text(encoding="utf-8")
    )
    assert descriptor["generation"] == 2


def test_audit_rejects_qualification_candidate_with_unknown_keys(tmp_path):
    from taiwan_lab_mcp.audit import AuditIntegrityError, validate_audit_evidence
    from taiwan_lab_mcp.canonical import canonical_json_bytes, sha256_bytes
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()
    built = build_nhi_snapshot(payload, tmp_path)
    manifest = json.loads(
        (tmp_path / "curated" / "nhi_fee" / built["snapshot_id"] / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    reference = manifest["audit_evidence"]["qualification_candidate"]
    candidate_path = tmp_path / Path(reference["data_root_relative_path"])
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    candidate["unexpected"] = True
    candidate_path.write_bytes(canonical_json_bytes(candidate))
    reference["sha256"] = sha256_bytes(candidate_path.read_bytes())

    with pytest.raises(AuditIntegrityError, match="qualification candidate invalid"):
        validate_audit_evidence(tmp_path, manifest)


def _approved_case_fixture(index: int, transform: dict, artifact_sha256: str) -> dict:
    from taiwan_lab_mcp.canonical import sha256_json

    golden = {
        "golden_case_schema_version": 1,
        "case_id": f"UNIT-NHI-G-{index:03d}",
        "source_id": "nhi_fee",
        "acceptance_id": "NHI-01",
        "source_title": "unit-test-only validator fixture; not official evidence",
        "official_landing_url": "https://example.invalid/unit-test-only",
        "official_version_or_modified_at": None,
        "official_source": True,
        "artifact_id": "nhi-primary-csv",
        "raw_artifact_sha256": artifact_sha256,
        "evidence_data_root_relative_path": "raw/nhi_fee/rev-1/artifacts/source.csv",
        "fixture_file": None,
        "fixture_sha256": None,
        "transform": deepcopy(transform),
        "input": {"code": f"UNIT{index:03d}"},
        "source_locator": {"locator_type": "nhi_row", "source_row_number": index + 1},
        "source_row_sha256": "c" * 64,
        "expected_status": "ok",
        "expected_fields": {"points": 0},
        "expected_warnings": ["coverage_review_incomplete"],
        "reviewer_id": "unit-test-only-reviewer",
        "reviewer_role": "unit_test_role",
        "identity_assurance": "local_asserted",
        "reviewed_at": "2026-09-14T00:00:00+08:00",
        "review_status": "approved",
    }
    return {
        "golden_case": golden,
        "golden_case_sha256": sha256_json(golden),
        "evaluation_status": "passed",
        "failure_codes": [],
    }


def test_approved_certificate_counts_only_official_cases_that_passed_evaluation():
    from taiwan_lab_mcp.audit import AuditIntegrityError, _validate_approved_qualification

    artifact_sha256 = "a" * 64
    transform = {
        "parser": {"version": "nhi-csv-v1", "bundle_sha256": "b" * 64},
        "schema": {"version": "nhi-7-v1", "bundle_sha256": "b" * 64},
        "normalization": {"version": "text-v1", "bundle_sha256": "b" * 64},
        "rules": [],
        "qualifier": {
            "name": None,
            "version": None,
            "spec_sha256": None,
            "extractor_output_sha256": None,
        },
    }
    manifest = {
        "source_id": "nhi_fee",
        "raw_revision_id": "rev-1",
        "review": {"completed_gates": ["NHI-R1-SOURCE", "NHI-R1-SCHEMA", "PUB-R1-OWNER"]},
        "build_fingerprint": {"fingerprint_schema": "curated-build-v1", **deepcopy(transform)},
        "artifacts": [
            {
                "artifact_id": "nhi-primary-csv",
                "role": "primary",
                "sha256": artifact_sha256,
                "storage_scope": "data_root",
                "local_artifact_available": True,
                "data_root_relative_path": "raw/nhi_fee/rev-1/artifacts/source.csv",
            }
        ],
    }
    cases = [_approved_case_fixture(index, transform, artifact_sha256) for index in range(1, 11)]
    candidate = {"case_ids": [case["golden_case"]["case_id"] for case in cases], "cases": cases}
    certificate = {
        "official_qualification_status": "approved",
        "approved_distinct_case_ids": list(candidate["case_ids"]),
    }

    _validate_approved_qualification(manifest, candidate, certificate)

    failed = deepcopy(candidate)
    failed["cases"][3]["evaluation_status"] = "failed"
    failed["cases"][3]["failure_codes"] = ["FIELD_MISMATCH:points"]
    with pytest.raises(AuditIntegrityError, match="did not pass evaluation"):
        _validate_approved_qualification(manifest, failed, certificate)

    stale = deepcopy(candidate)
    stale["cases"][0]["golden_case"]["transform"]["parser"]["version"] = "nhi-csv-v0"
    with pytest.raises(AuditIntegrityError, match="transform is stale"):
        _validate_approved_qualification(manifest, stale, certificate)

    synthetic = deepcopy(candidate)
    synthetic["cases"][1]["golden_case"]["official_source"] = False
    with pytest.raises(AuditIntegrityError, match="not official reviewed evidence"):
        _validate_approved_qualification(manifest, synthetic, certificate)

    wrong_evidence = deepcopy(candidate)
    wrong_evidence["cases"][2]["golden_case"]["evidence_data_root_relative_path"] = (
        "raw/nhi_fee/other-rev/artifacts/source.csv"
    )
    with pytest.raises(AuditIntegrityError, match="not official reviewed evidence"):
        _validate_approved_qualification(manifest, wrong_evidence, certificate)


def test_official_runtime_requires_publication_owner_gate(tmp_path, monkeypatch):
    from taiwan_lab_mcp.adapters.nhi import NHIAdapter
    from taiwan_lab_mcp.canonical import canonical_json_bytes, sha256_bytes
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()
    built = build_nhi_snapshot(payload, tmp_path)
    manifest_path = tmp_path / "curated" / "nhi_fee" / built["snapshot_id"] / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for key in ("required_gates", "completed_gates"):
        manifest["review"][key] = [
            gate_id for gate_id in manifest["review"][key] if gate_id != "PUB-R1-OWNER"
        ]
    manifest["audit_evidence"]["reviews"] = [
        item for item in manifest["audit_evidence"]["reviews"] if item["gate_id"] != "PUB-R1-OWNER"
    ]
    golden_ref = manifest["audit_evidence"]["golden_qualification"]
    golden_path = tmp_path / Path(golden_ref["data_root_relative_path"])
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    golden["accepted_review_hashes"] = [
        item["sha256"] for item in manifest["audit_evidence"]["reviews"]
    ]
    golden_path.write_bytes(canonical_json_bytes(golden))
    golden_ref["sha256"] = sha256_bytes(golden_path.read_bytes())
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    descriptor_path = tmp_path / "manifests" / "current" / "nhi_fee.json"
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    descriptor["manifest_sha256"] = sha256_bytes(manifest_path.read_bytes())
    descriptor_path.write_bytes(canonical_json_bytes(descriptor))
    monkeypatch.setenv("TAIWAN_LAB_DATA_MODE", "official_snapshot")
    monkeypatch.setenv("TAIWAN_LAB_DATA_DIR", str(tmp_path))

    result = NHIAdapter().get_points("09006C")
    assert result.result_status == "data_unavailable"
    assert result.availability_reason_code == "serving_integrity_failure"
