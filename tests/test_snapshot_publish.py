import json
import shutil
import subprocess
import sys
from pathlib import Path


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
