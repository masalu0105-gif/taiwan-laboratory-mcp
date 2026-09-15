import io
import json
import zipfile
from datetime import datetime
from pathlib import Path

import pytest

from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, parse_nhi_csv

_LIVE_OID = "2.16.886.101.20003.20065.20022"
_GATES = ("NHI-R1-SOURCE", "NHI-R1-SCHEMA", "PUB-R1-OWNER")


def _rows(points_by_index=None):
    points_by_index = points_by_index or {}
    return [
        f"9{index:04d}C,{points_by_index.get(index, index * 10)},20240101,29101231,"
        f"Unit test {index},單元測試項目{index},"
        for index in range(1, 11)
    ]


def _csv(rows):
    return (chr(0xFEFF) + ",".join(NHI_COLUMNS) + "\n" + "\n".join(rows) + "\n").encode("utf-8")


def _write_raw_revision(data_root, payload):
    from taiwan_lab_mcp.canonical import sha256_bytes
    from taiwan_lab_mcp.fetch import FetchedArtifact
    from taiwan_lab_mcp.sync import run_nhi_sync

    discovery = {
        "dataset_id": "174450",
        "identifier": "A21030000I-D20021",
        "publisher_oid": _LIVE_OID,
        "landing_url": "https://data.gov.tw/dataset/174450",
        "metadata_url": "https://data.gov.tw/api/v2/rest/dataset/174450",
        "license_code": "1",
        "license_name": "政府資料開放授權條款-第1版",
        "license_url": "https://data.gov.tw/license",
        "resource_format": "CSV",
        "resource_character_encoding": "UTF-8",
        "resource_url": "https://info.nhi.gov.tw/data.csv",
        "official_modified_at_raw": "2026-09-14 07:05:47",
        "official_modified_at_precision": "second",
        "official_modified_timezone_known": False,
    }
    artifact = FetchedArtifact(
        requested_url="https://info.nhi.gov.tw/data.csv",
        final_url="https://info.nhi.gov.tw/data.csv",
        status_code=200,
        payload=payload,
        sha256=sha256_bytes(payload),
        fetched_at="2026-09-14T03:42:43Z",
        headers={"content-type": "application/csv"},
        redirect_trace=("https://info.nhi.gov.tw/data.csv",),
    )
    report = run_nhi_sync(payload, data_root, discovery=discovery, fetched_artifact=artifact)
    assert report["status"] == "passed"
    return report["raw_revision_id"]


def _approved_cases(payload, raw_revision_id):
    from taiwan_lab_mcp.canonical import sha256_bytes
    from taiwan_lab_mcp.importers.nhi import active_nhi_transform

    return [
        {
            "golden_case_schema_version": 1,
            "case_id": f"UNIT-BUNDLE-G-{index:03d}",
            "source_id": "nhi_fee",
            "acceptance_id": "NHI-01",
            "source_title": "unit test NHI bundle fixture",
            "official_landing_url": "https://data.gov.tw/dataset/174450",
            "official_version_or_modified_at": "2026-09-14 07:05:47",
            "official_source": True,
            "artifact_id": "nhi-primary-csv",
            "raw_artifact_sha256": sha256_bytes(payload),
            "evidence_data_root_relative_path": f"raw/nhi_fee/{raw_revision_id}/artifacts/source.csv",
            "fixture_file": None,
            "fixture_sha256": None,
            "transform": active_nhi_transform(),
            "input": {"code": row.code_raw},
            "source_locator": {
                "locator_type": "nhi_row",
                "source_row_number": row.source_row_number,
            },
            "source_row_sha256": row.source_row_sha256,
            "expected_status": "ok",
            "expected_fields": {"points": row.points},
            # Official builds count unreviewed codes as lab items (owner 2026-09-15).
            "expected_warnings": [],
            "reviewer_id": "project-owner-alias",
            "reviewer_role": "project_owner",
            "identity_assurance": "local_asserted",
            "reviewed_at": "2026-09-14T18:09:42+08:00",
            "review_status": "approved",
        }
        for index, row in enumerate(parse_nhi_csv(payload).rows, start=1)
    ]


@pytest.fixture
def distribution_identity(monkeypatch):
    import taiwan_lab_mcp.importers.nhi as nhi_importer

    monkeypatch.setattr(
        nhi_importer, "_application_build_identity", lambda: ("distribution", "d" * 64)
    )


def _serve_official(data_root, rows=None):
    from taiwan_lab_mcp.importers.nhi import build_official_nhi_snapshot

    payload = _csv(rows or _rows())
    raw_revision_id = _write_raw_revision(data_root, payload)
    return build_official_nhi_snapshot(
        data_root,
        raw_revision_id=raw_revision_id,
        approved_golden_cases=_approved_cases(payload, raw_revision_id),
        owner_reviews=[
            {
                "gate_id": gate_id,
                "reviewer_id": "project-owner-alias",
                "reviewer_role": "project_owner",
                "reviewed_at": "2026-09-14T18:30:00+08:00",
                "finding_counts": {"critical": 0, "major": 0, "minor": 0},
                "comments": "unit test only",
            }
            for gate_id in _GATES
        ],
        publisher_actor_id="unit-test-only-publisher",
    )


def _descriptor(data_root):
    return json.loads(
        (data_root / "manifests" / "current" / "nhi_fee.json").read_text(encoding="utf-8")
    )


def _export(source_root, output_dir):
    from taiwan_lab_mcp.snapshot_bundle import export_nhi_snapshot_bundle

    return export_nhi_snapshot_bundle(source_root, output_dir=output_dir)


def _rewrite_zip(bundle_path, mutate):
    """Rebuild a bundle after mutate(entries) edits the {name: bytes} mapping."""

    with zipfile.ZipFile(bundle_path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    mutate(entries)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    bundle_path.write_bytes(buffer.getvalue())
    return bundle_path


def test_export_packs_only_the_serving_raw_and_curated_build(tmp_path, distribution_identity):
    from taiwan_lab_mcp.canonical import sha256_bytes

    source_root = tmp_path / "source"
    built = _serve_official(source_root)

    exported = _export(source_root, tmp_path / "release")

    assert exported["result"] == "exported"
    assert exported["snapshot_id"] == built["snapshot_id"]
    bundle_path = Path(exported["bundle_path"])
    assert bundle_path.name == f"nhi_fee-snapshot-{built['snapshot_id'][-64:][:12]}.zip"
    assert sha256_bytes(bundle_path.read_bytes()) == exported["bundle_sha256"]
    checksum_line = Path(exported["checksum_path"]).read_text(encoding="utf-8")
    assert checksum_line == f"{exported['bundle_sha256']}  {bundle_path.name}\n"

    with zipfile.ZipFile(bundle_path) as archive:
        names = archive.namelist()
        manifest = json.loads(archive.read("bundle-manifest.json"))
        for item in manifest["files"]:
            payload = archive.read(item["path"])
            assert len(payload) == item["bytes"]
            assert sha256_bytes(payload) == item["sha256"]
    assert names[0] == "bundle-manifest.json"
    assert sorted(names[1:]) == sorted(item["path"] for item in manifest["files"])
    raw_revision_id = built["raw_revision_id"]
    assert f"raw/nhi_fee/{raw_revision_id}/artifacts/source.csv" in names
    assert f"raw/nhi_fee/{raw_revision_id}/fetch.json" in names
    build_prefix = f"curated/nhi_fee/{built['snapshot_id']}/"
    assert f"{build_prefix}data.sqlite3" in names
    assert f"{build_prefix}manifest.json" in names
    assert any(name.startswith(f"{build_prefix}audit/reviews/") for name in names)
    assert all(
        name == "bundle-manifest.json"
        or name.startswith((f"raw/nhi_fee/{raw_revision_id}/", build_prefix))
        for name in names
    )
    source_descriptor = _descriptor(source_root)
    assert manifest["bundle_schema_version"] == 1
    assert manifest["source_id"] == "nhi_fee"
    assert manifest["snapshot_id"] == built["snapshot_id"]
    assert manifest["raw_revision_id"] == raw_revision_id
    assert manifest["last_successful_check_at"] == source_descriptor["last_successful_check_at"]
    assert manifest["attribution"] == "資料提供機關：衛生福利部中央健康保險署"
    assert manifest["license_url"] == "https://data.gov.tw/license"
    assert "非健保署官方服務" in manifest["notice"]


def test_export_refuses_a_serving_build_with_a_pending_candidate(tmp_path, distribution_identity):
    from taiwan_lab_mcp.canonical import canonical_json_bytes, sha256_bytes
    from taiwan_lab_mcp.snapshot_bundle import SnapshotBundleError

    source_root = tmp_path / "source"
    _serve_official(source_root)
    descriptor_path = source_root / "manifests" / "current" / "nhi_fee.json"
    descriptor = _descriptor(source_root)
    check_path = source_root / Path(descriptor["latest_check_data_root_relative_path"])
    check = json.loads(check_path.read_text(encoding="utf-8"))
    for record in (check, descriptor):
        record["latest_candidate_id"] = "c" * 64
        record["latest_candidate_status"] = "review_pending"
        record["stale"] = True
        record["stale_reason_codes"] = ["newer_candidate_pending_review"]
    check_bytes = canonical_json_bytes(check)
    check_path.write_bytes(check_bytes)
    descriptor["latest_check_sha256"] = sha256_bytes(check_bytes)
    descriptor_path.write_bytes(canonical_json_bytes(descriptor))

    with pytest.raises(SnapshotBundleError) as error:
        _export(source_root, tmp_path / "release")
    assert error.value.code == "EXPORT_SERVING_STALE"
    assert not (tmp_path / "release").exists()


def test_install_bundle_into_empty_data_root_serves_the_same_snapshot(
    tmp_path, distribution_identity
):
    from taiwan_lab_mcp.adapters.nhi import NHIAdapter
    from taiwan_lab_mcp.config import DataContext
    from taiwan_lab_mcp.snapshot_bundle import install_nhi_snapshot_bundle
    from taiwan_lab_mcp.stores import read_nhi_state

    source_root = tmp_path / "source"
    built = _serve_official(source_root)
    exported = _export(source_root, tmp_path / "release")
    user_root = tmp_path / "user-data"

    installed = install_nhi_snapshot_bundle(
        user_root,
        bundle_path=Path(exported["bundle_path"]),
        expected_sha256=exported["bundle_sha256"],
        actor="unit-test-installer",
    )

    assert installed["result"] == "installed"
    assert installed["snapshot_id"] == built["snapshot_id"]
    assert installed["generation"] == 1
    descriptor = _descriptor(user_root)
    assert descriptor["serving_snapshot_id"] == built["snapshot_id"]
    assert descriptor["publisher_actor_id"] == "unit-test-installer"
    assert descriptor["parent_snapshot_id"] is None
    assert (
        descriptor["last_successful_check_at"]
        == _descriptor(source_root)["last_successful_check_at"]
    )
    assert descriptor["latest_candidate_status"] == "none"

    last_success = datetime.fromisoformat(
        descriptor["last_successful_check_at"].replace("Z", "+00:00")
    )
    state = read_nhi_state(user_root, clock=lambda: last_success)
    assert state.availability == "available"
    assert state.provenance.artifacts[0].local_artifact_available is True
    result = NHIAdapter(
        DataContext(mode="official_snapshot", data_root=user_root, clock=lambda: last_success)
    ).get_points("90003C")
    assert result.result_status == "ok"
    assert result.items[0].record.points == 30
    assert result.provenance.snapshot_id == built["snapshot_id"]


def test_install_same_bundle_again_is_a_no_op(tmp_path, distribution_identity):
    from taiwan_lab_mcp.snapshot_bundle import install_nhi_snapshot_bundle

    source_root = tmp_path / "source"
    _serve_official(source_root)
    exported = _export(source_root, tmp_path / "release")
    user_root = tmp_path / "user-data"
    kwargs = {"bundle_path": Path(exported["bundle_path"]), "actor": "unit-test-installer"}
    install_nhi_snapshot_bundle(user_root, **kwargs)
    before = (user_root / "manifests" / "current" / "nhi_fee.json").read_bytes()

    again = install_nhi_snapshot_bundle(user_root, **kwargs)

    assert again["result"] == "already_installed"
    assert (user_root / "manifests" / "current" / "nhi_fee.json").read_bytes() == before


def test_install_newer_bundle_switches_serving_and_keeps_parent(tmp_path, distribution_identity):
    from taiwan_lab_mcp.snapshot_bundle import install_nhi_snapshot_bundle

    first_root = tmp_path / "source-1"
    second_root = tmp_path / "source-2"
    first = _serve_official(first_root)
    second = _serve_official(second_root, _rows({3: 35}))
    first_bundle = _export(first_root, tmp_path / "release-1")
    second_bundle = _export(second_root, tmp_path / "release-2")
    user_root = tmp_path / "user-data"

    install_nhi_snapshot_bundle(
        user_root, bundle_path=Path(first_bundle["bundle_path"]), actor="unit-test-installer"
    )
    upgraded = install_nhi_snapshot_bundle(
        user_root, bundle_path=Path(second_bundle["bundle_path"]), actor="unit-test-installer"
    )

    assert upgraded["result"] == "installed"
    assert upgraded["generation"] == 2
    descriptor = _descriptor(user_root)
    assert descriptor["serving_snapshot_id"] == second["snapshot_id"]
    assert descriptor["parent_snapshot_id"] == first["snapshot_id"]


def _tamper_db(entries):
    name = next(name for name in entries if name.endswith("data.sqlite3"))
    payload = bytearray(entries[name])
    payload[-1] ^= 0xFF
    entries[name] = bytes(payload)


def _add_extra_entry(entries):
    entries["curated/nhi_fee/extra.txt"] = b"extra"


def _add_traversal_entry(entries):
    entries["../outside.txt"] = b"x"


def _list_forbidden_path(entries):
    manifest = json.loads(entries["bundle-manifest.json"])
    payload = b"{}"
    manifest["files"].append(
        {
            "path": "manifests/current/nhi_fee.json",
            "bytes": len(payload),
            "sha256": __import__("hashlib").sha256(payload).hexdigest(),
        }
    )
    entries["manifests/current/nhi_fee.json"] = payload
    entries["bundle-manifest.json"] = json.dumps(manifest).encode()


def _drop_manifest(entries):
    del entries["bundle-manifest.json"]


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        (_tamper_db, "BUNDLE_FILE_HASH_MISMATCH"),
        (_add_extra_entry, "BUNDLE_ENTRY_UNEXPECTED"),
        (_add_traversal_entry, "BUNDLE_PATH_INVALID"),
        (_list_forbidden_path, "BUNDLE_PATH_INVALID"),
        (_drop_manifest, "BUNDLE_MANIFEST_INVALID"),
    ],
)
def test_install_rejects_tampered_bundles_before_writing(
    tmp_path, distribution_identity, mutate, expected_code
):
    from taiwan_lab_mcp.snapshot_bundle import SnapshotBundleError, install_nhi_snapshot_bundle

    source_root = tmp_path / "source"
    _serve_official(source_root)
    exported = _export(source_root, tmp_path / "release")
    bundle_path = _rewrite_zip(Path(exported["bundle_path"]), mutate)
    user_root = tmp_path / "user-data"

    with pytest.raises(SnapshotBundleError) as error:
        install_nhi_snapshot_bundle(user_root, bundle_path=bundle_path, actor="unit-test-installer")

    assert error.value.code == expected_code
    assert not (user_root / "raw").exists()
    assert not (user_root / "curated").exists()
    assert not (user_root / "manifests").exists()


@pytest.mark.parametrize(
    ("payload", "expected_sha256", "expected_code"),
    [
        (b"<html>not a zip</html>", None, "BUNDLE_MAGIC_MISMATCH"),
        (None, "0" * 64, "BUNDLE_SHA256_MISMATCH"),
    ],
)
def test_install_checks_bundle_bytes_first(
    tmp_path, distribution_identity, payload, expected_sha256, expected_code
):
    from taiwan_lab_mcp.snapshot_bundle import SnapshotBundleError, install_nhi_snapshot_bundle

    source_root = tmp_path / "source"
    _serve_official(source_root)
    exported = _export(source_root, tmp_path / "release")
    bundle_path = Path(exported["bundle_path"])
    if payload is not None:
        bundle_path.write_bytes(payload)

    with pytest.raises(SnapshotBundleError) as error:
        install_nhi_snapshot_bundle(
            tmp_path / "user-data",
            bundle_path=bundle_path,
            expected_sha256=expected_sha256,
            actor="unit-test-installer",
        )
    assert error.value.code == expected_code


def test_install_refuses_to_overwrite_a_different_existing_file(tmp_path, distribution_identity):
    from taiwan_lab_mcp.snapshot_bundle import SnapshotBundleError, install_nhi_snapshot_bundle

    source_root = tmp_path / "source"
    built = _serve_official(source_root)
    exported = _export(source_root, tmp_path / "release")
    user_root = tmp_path / "user-data"
    conflict = user_root / "raw" / "nhi_fee" / built["raw_revision_id"] / "fetch.json"
    conflict.parent.mkdir(parents=True)
    conflict.write_bytes(b"{}")

    with pytest.raises(SnapshotBundleError) as error:
        install_nhi_snapshot_bundle(
            user_root, bundle_path=Path(exported["bundle_path"]), actor="unit-test-installer"
        )

    assert error.value.code == "BUNDLE_FILE_CONFLICT"
    assert conflict.read_bytes() == b"{}"
    assert not (user_root / "curated").exists()
    assert not (user_root / "manifests").exists()


def test_cli_export_and_install_snapshot(tmp_path, distribution_identity, capsys):
    from taiwan_lab_mcp.data_cli import main

    source_root = tmp_path / "source"
    _serve_official(source_root)
    capsys.readouterr()

    assert (
        main(
            [
                "export-snapshot",
                "nhi_fee",
                "--data-dir",
                str(source_root),
                "--output-dir",
                str(tmp_path / "release"),
                "--json",
            ]
        )
        == 0
    )
    exported = json.loads(capsys.readouterr().out)

    install_args = [
        "install-snapshot",
        "nhi_fee",
        "--bundle",
        exported["bundle_path"],
        "--actor",
        "unit-test-installer",
        "--data-dir",
        str(tmp_path / "user-data"),
        "--json",
    ]
    assert main([*install_args, "--sha256", "0" * 64]) == 4
    assert json.loads(capsys.readouterr().out) == {
        "operation": "install-snapshot",
        "result": "failed",
        "error_code": "BUNDLE_SHA256_MISMATCH",
    }
    assert main([*install_args, "--sha256", exported["bundle_sha256"]]) == 0
    installed = json.loads(capsys.readouterr().out)
    assert installed["result"] == "installed"
    assert installed["snapshot_id"] == exported["snapshot_id"]


def test_install_refuses_paths_over_the_limit_before_writing(tmp_path, distribution_identity):
    from taiwan_lab_mcp.snapshot_bundle import SnapshotBundleError, install_nhi_snapshot_bundle

    source_root = tmp_path / "source"
    _serve_official(source_root)
    exported = _export(source_root, tmp_path / "release")
    user_root = tmp_path / "user-data"

    # Build directory names alone are 78 characters, so a limit this small is always hit.
    with pytest.raises(SnapshotBundleError) as error:
        install_nhi_snapshot_bundle(
            user_root,
            bundle_path=Path(exported["bundle_path"]),
            actor="unit-test-installer",
            max_path_length=len(str(user_root)) + 60,
        )

    assert error.value.code == "BUNDLE_PATH_TOO_LONG"
    assert not (user_root / "raw").exists()
    assert not (user_root / "curated").exists()
    assert not (user_root / "manifests").exists()


def test_install_reports_write_failures_as_a_bundle_error(
    tmp_path, distribution_identity, monkeypatch
):
    import taiwan_lab_mcp.snapshot_bundle as bundle_module

    source_root = tmp_path / "source"
    _serve_official(source_root)
    exported = _export(source_root, tmp_path / "release")
    user_root = tmp_path / "user-data"

    def failing_write(path, payload):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(bundle_module, "_write_new_file", failing_write)
    with pytest.raises(bundle_module.SnapshotBundleError) as error:
        bundle_module.install_nhi_snapshot_bundle(
            user_root, bundle_path=Path(exported["bundle_path"]), actor="unit-test-installer"
        )

    assert error.value.code == "BUNDLE_WRITE_FAILED"
    assert not (user_root / "manifests").exists()


def test_bundle_path_and_write_errors_have_cli_exit_codes():
    from taiwan_lab_mcp.data_cli import _bundle_exit_code
    from taiwan_lab_mcp.snapshot_bundle import SnapshotBundleError

    assert _bundle_exit_code(SnapshotBundleError("BUNDLE_PATH_TOO_LONG")) == 2
    assert _bundle_exit_code(SnapshotBundleError("BUNDLE_WRITE_FAILED")) == 6
