import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, parse_nhi_csv

_LIVE_OID = "2.16.886.101.20003.20065.20022"
_GATES = ("NHI-R1-SOURCE", "NHI-R1-SCHEMA", "PUB-R1-OWNER")


def _rows(points_by_index=None, count=10, extra=()):
    points_by_index = points_by_index or {}
    rows = [
        f"9{index:04d}C,{points_by_index.get(index, index * 10)},20240101,29101231,"
        f"Unit test {index},單元測試項目{index},"
        for index in range(1, count + 1)
    ]
    return rows + list(extra)


def _csv(rows):
    return (chr(0xFEFF) + ",".join(NHI_COLUMNS) + "\n" + "\n".join(rows) + "\n").encode("utf-8")


class _Headers(dict):
    def get_content_type(self):
        return self.get("Content-Type", "").split(";", 1)[0].strip().lower()


class _Response:
    def __init__(self, status, body=b"", headers=None):
        self.status = status
        self.body = body
        self.headers = _Headers(headers or {})
        self.offset = 0

    def getcode(self):
        return self.status

    def read(self, size=-1):
        if size is None or size < 0:
            size = len(self.body) - self.offset
        chunk = self.body[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk

    def close(self):
        pass


class _Opener:
    def __init__(self, *responses):
        self.responses = list(responses)

    def open(self, request, timeout):
        return self.responses.pop(0)


def _metadata_response():
    body = json.dumps(
        {
            "success": True,
            "result": {
                "publisherOID": _LIVE_OID,
                "identifier": "A21030000I-D20021",
                "license": "1",
                "modifiedDate": "2026-09-15 07:05:47",
                "distribution": [
                    {
                        "resourceFormat": "CSV",
                        "resourceCharacterEncoding": "UTF-8",
                        "resourceDownloadUrl": "https://info.nhi.gov.tw/data.csv",
                    }
                ],
            },
        },
        ensure_ascii=False,
    ).encode()
    return _Response(200, body, {"Content-Type": "application/json"})


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

    cases = []
    for index, row in enumerate(parse_nhi_csv(payload).rows, start=1):
        cases.append(
            {
                "golden_case_schema_version": 1,
                "case_id": f"UNIT-REVIEW-G-{index:03d}",
                "source_id": "nhi_fee",
                "acceptance_id": "NHI-01",
                "source_title": "unit test NHI review fixture",
                "official_landing_url": "https://data.gov.tw/dataset/174450",
                "official_version_or_modified_at": "2026-09-14 07:05:47",
                "official_source": True,
                "artifact_id": "nhi-primary-csv",
                "raw_artifact_sha256": sha256_bytes(payload),
                "evidence_data_root_relative_path": (
                    f"raw/nhi_fee/{raw_revision_id}/artifacts/source.csv"
                ),
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
                "expected_fields": {"points": row.points, "name_zh_raw": row.name_zh_raw},
                # Official builds count unreviewed codes as lab items (owner 2026-09-15).
                "expected_warnings": [],
                "reviewer_id": "unit-test-only-reviewer",
                "reviewer_role": "project_owner",
                "identity_assurance": "local_asserted",
                "reviewed_at": "2026-09-14T18:09:42+08:00",
                "review_status": "approved",
            }
        )
    return cases


@pytest.fixture
def distribution_identity(monkeypatch):
    import taiwan_lab_mcp.importers.nhi as nhi_importer

    monkeypatch.setattr(
        nhi_importer, "_application_build_identity", lambda: ("distribution", "d" * 64)
    )


def _serve_official(data_root):
    from taiwan_lab_mcp.importers.nhi import build_official_nhi_snapshot

    payload = _csv(_rows())
    raw_revision_id = _write_raw_revision(data_root, payload)
    return build_official_nhi_snapshot(
        data_root,
        raw_revision_id=raw_revision_id,
        approved_golden_cases=_approved_cases(payload, raw_revision_id),
        owner_reviews=[
            {
                "gate_id": gate_id,
                "reviewer_id": "unit-test-only-reviewer",
                "reviewer_role": "project_owner",
                "reviewed_at": "2026-09-14T18:30:00+08:00",
                "finding_counts": {"critical": 0, "major": 0, "minor": 0},
                "comments": "unit test only",
            }
            for gate_id in _GATES
        ],
        publisher_actor_id="unit-test-only-publisher",
    )


def _check(data_root, rows, hour=1):
    from taiwan_lab_mcp.sync import run_nhi_upstream_check

    return run_nhi_upstream_check(
        data_root,
        expected_publisher_oid=_LIVE_OID,
        actor="unit-test-checker",
        opener=_Opener(
            _metadata_response(),
            _Response(200, _csv(rows), {"Content-Type": "application/csv"}),
        ),
        clock=lambda: datetime(2026, 9, 15, hour, 0, tzinfo=timezone.utc),
    )


def _descriptor_bytes(data_root):
    return (data_root / "manifests" / "current" / "nhi_fee.json").read_bytes()


def _decision(packet_summary, **overrides):
    packet = json.loads(Path(packet_summary["packet_path"]).read_text(encoding="utf-8"))
    decision = {
        "review_decision_schema_version": 1,
        "source_id": "nhi_fee",
        "candidate_raw_revision_id": packet_summary["candidate_raw_revision_id"],
        "packet_sha256": packet_summary["packet_sha256"],
        "decision": "approved",
        "reviewer_id": "unit-test-only-reviewer",
        "reviewer_role": "project_owner",
        "reviewed_at": "2026-09-15T10:00:00+08:00",
        "approved_case_ids": [case["case_id"] for case in packet["proposed_cases"]],
        "gate_reviews": [
            {
                "gate_id": gate_id,
                "finding_counts": {"critical": 0, "major": 0, "minor": 0},
                "comments": "unit test only",
            }
            for gate_id in _GATES
        ],
    }
    decision.update(overrides)
    return decision


def _write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def test_review_packet_rebinds_approved_cases_to_pending_candidate(tmp_path, distribution_identity):
    from taiwan_lab_mcp.nhi_review import prepare_nhi_review_packet

    data_root = tmp_path / "data"
    output_dir = tmp_path / "review"
    _serve_official(data_root)
    summary = _check(
        data_root, _rows({3: 35}, extra=["90011C,110,20260901,29101231,New,新增項目,"])
    )
    assert summary["result"] == "changed"
    descriptor_before = _descriptor_bytes(data_root)

    packet_summary = prepare_nhi_review_packet(data_root, output_dir=output_dir)

    assert packet_summary["result"] == "packet_ready"
    assert packet_summary["candidate_raw_revision_id"] == summary["candidate_raw_revision_id"]
    assert packet_summary["case_counts"] == {"unchanged": 9, "changed": 1, "missing": 0}
    packet_path = Path(packet_summary["packet_path"])
    assert packet_path.parent == output_dir
    from taiwan_lab_mcp.canonical import sha256_bytes

    assert sha256_bytes(packet_path.read_bytes()) == packet_summary["packet_sha256"]
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    candidate_id = summary["candidate_raw_revision_id"]
    assert len(packet["proposed_cases"]) == 10
    for case in packet["proposed_cases"]:
        assert case["review_status"] == "review_pending"
        assert case["reviewer_id"] is None
        assert case["reviewed_at"] is None
        assert case["evidence_data_root_relative_path"] == (
            f"raw/nhi_fee/{candidate_id}/artifacts/source.csv"
        )
        assert case["raw_artifact_sha256"] == packet["candidate_raw_artifact_sha256"]
    changed = [item for item in packet["case_comparisons"] if item["status"] == "changed"]
    assert changed == [
        {
            "case_id": "UNIT-REVIEW-G-003",
            "code": "90003C",
            "status": "changed",
            "changes": [{"field": "points", "before": 30, "after": 35}],
        }
    ]
    proposed_003 = next(
        case for case in packet["proposed_cases"] if case["case_id"] == "UNIT-REVIEW-G-003"
    )
    assert proposed_003["expected_fields"]["points"] == 35

    page = Path(packet_summary["review_page_path"]).read_text(encoding="utf-8")
    assert "90003C" in page
    assert "30 → 35" in page
    assert "90011C" in page  # the upstream diff summary is included
    assert packet_summary["packet_sha256"] in page
    template = json.loads(
        Path(packet_summary["decision_template_path"]).read_text(encoding="utf-8")
    )
    assert template["packet_sha256"] == packet_summary["packet_sha256"]
    assert template["decision"] is None
    assert template["reviewer_id"] is None

    # Preparing a packet never touches the serving data root.
    assert _descriptor_bytes(data_root) == descriptor_before


def test_review_packet_rebinds_expected_warnings_to_candidate_scope_coverage(
    tmp_path, distribution_identity, monkeypatch
):
    import taiwan_lab_mcp.importers.nhi as nhi_importer
    import taiwan_lab_mcp.nhi_review as nhi_review

    data_root = tmp_path / "data"
    _serve_official(data_root)
    assert _check(data_root, _rows({3: 35}))["result"] == "changed"
    _, alias_bytes = nhi_importer._packaged_rule_bundles()
    bundle = {
        "rule_version": "nhi-lab-scope-v2",
        "source_id": "nhi_fee",
        "status": "complete",
        "entries": [
            {
                "code": f"9{index:04d}C",
                "scope_status": "in_scope",
                "basis_type": "nhi_fee_schedule_section",
                "basis_url": "https://example.test/scope",
                "basis_locator": "unit test section",
                "rule_version": "nhi-lab-scope-v2",
                "reviewer_id": "ai-reviewer:unit-test",
                "reviewed_at": "2026-09-14T23:00:00+08:00",
                "decision_status": "approved",
            }
            for index in range(1, 11)
        ],
    }

    def patched_bundles():
        return json.dumps(bundle).encode(), alias_bytes

    monkeypatch.setattr(nhi_importer, "_packaged_rule_bundles", patched_bundles)
    monkeypatch.setattr(nhi_review, "_packaged_rule_bundles", patched_bundles)

    packet_summary = nhi_review.prepare_nhi_review_packet(data_root, output_dir=tmp_path / "r")
    packet = json.loads(Path(packet_summary["packet_path"]).read_text(encoding="utf-8"))

    assert [case["expected_warnings"] for case in packet["proposed_cases"]] == [[]] * 10
    unchanged_points = next(item for item in packet["case_comparisons"] if item["code"] == "90001C")
    # Official builds already served unreviewed codes as lab items, so nothing changes.
    assert unchanged_points["changes"] == []


def test_review_packet_reports_golden_codes_missing_from_candidate(tmp_path, distribution_identity):
    from taiwan_lab_mcp.nhi_review import prepare_nhi_review_packet

    data_root = tmp_path / "data"
    _serve_official(data_root)
    _check(data_root, _rows(count=9))

    packet_summary = prepare_nhi_review_packet(data_root, output_dir=tmp_path / "review")

    assert packet_summary["case_counts"] == {"unchanged": 9, "changed": 0, "missing": 1}
    packet = json.loads(Path(packet_summary["packet_path"]).read_text(encoding="utf-8"))
    assert len(packet["proposed_cases"]) == 9
    assert {
        "case_id": "UNIT-REVIEW-G-010",
        "code": "90010C",
        "status": "missing",
        "changes": [],
    } in (packet["case_comparisons"])
    assert "90010C" in Path(packet_summary["review_page_path"]).read_text(encoding="utf-8")


def test_review_packet_requires_a_pending_candidate(tmp_path, distribution_identity):
    from taiwan_lab_mcp.nhi_review import NHIReviewError, prepare_nhi_review_packet

    data_root = tmp_path / "data"
    _serve_official(data_root)

    with pytest.raises(NHIReviewError) as error:
        prepare_nhi_review_packet(data_root, output_dir=tmp_path / "review")
    assert error.value.code == "NO_PENDING_CANDIDATE"
    assert not (tmp_path / "review").exists()


def test_publish_reviewed_candidate_switches_serving_snapshot(
    tmp_path, distribution_identity, monkeypatch
):
    from taiwan_lab_mcp.adapters.nhi import NHIAdapter
    from taiwan_lab_mcp.nhi_review import prepare_nhi_review_packet, publish_reviewed_nhi_candidate

    data_root = tmp_path / "data"
    first = _serve_official(data_root)
    _check(data_root, _rows({3: 35}))
    packet_summary = prepare_nhi_review_packet(data_root, output_dir=tmp_path / "review")
    decision_path = _write_json(tmp_path / "review" / "decision.json", _decision(packet_summary))

    published = publish_reviewed_nhi_candidate(
        data_root,
        packet_path=Path(packet_summary["packet_path"]),
        decision_path=decision_path,
        actor="unit-test-only-publisher",
    )

    assert published["result"] == "published"
    assert published["snapshot_id"] != first["snapshot_id"]
    assert published["raw_revision_id"] == packet_summary["candidate_raw_revision_id"]
    descriptor = json.loads(_descriptor_bytes(data_root))
    assert descriptor["serving_snapshot_id"] == published["snapshot_id"]
    assert descriptor["parent_snapshot_id"] == first["snapshot_id"]
    assert descriptor["latest_candidate_status"] == "none"
    assert descriptor["stale"] is False

    manifest = json.loads(
        (data_root / Path(descriptor["manifest_data_root_relative_path"])).read_text(
            encoding="utf-8"
        )
    )
    reviews = [
        json.loads((data_root / Path(item["data_root_relative_path"])).read_text(encoding="utf-8"))
        for item in manifest["audit_evidence"]["reviews"]
    ]
    assert {review["reviewer_id"] for review in reviews} == {"unit-test-only-reviewer"}
    assert {review["reviewed_at"] for review in reviews} == {"2026-09-15T10:00:00+08:00"}
    evidence_ids = {ref["artifact_id"] for ref in reviews[0]["evidence_refs"]}
    assert {"nhi-review-packet", "nhi-review-decision"} <= evidence_ids

    monkeypatch.setenv("TAIWAN_LAB_DATA_MODE", "official_snapshot")
    monkeypatch.setenv("TAIWAN_LAB_DATA_DIR", str(data_root))
    result = NHIAdapter().get_points("90003C")
    assert result.result_status == "ok"
    assert result.items[0].record.points == 35
    assert result.source_status.latest_candidate_status == "none"


@pytest.mark.parametrize(
    ("override", "expected_code"),
    [
        ({"packet_sha256": "0" * 64}, "REVIEW_DECISION_PACKET_MISMATCH"),
        ({"decision": "rejected"}, "REVIEW_DECISION_NOT_APPROVED"),
        ({"decision": None}, "REVIEW_DECISION_SCHEMA_INVALID"),
        ({"reviewer_id": ""}, "REVIEW_DECISION_SCHEMA_INVALID"),
        ({"reviewed_at": "2026-09-15T10:00:00"}, "REVIEW_DECISION_SCHEMA_INVALID"),
        ({"approved_case_ids": ["UNKNOWN-CASE"]}, "REVIEW_DECISION_CASE_UNKNOWN"),
        ({"unexpected": True}, "REVIEW_DECISION_SCHEMA_INVALID"),
    ],
)
def test_publish_rejects_invalid_review_decision_before_any_write(
    tmp_path, distribution_identity, override, expected_code
):
    from taiwan_lab_mcp.nhi_review import (
        NHIReviewError,
        prepare_nhi_review_packet,
        publish_reviewed_nhi_candidate,
    )

    data_root = tmp_path / "data"
    _serve_official(data_root)
    _check(data_root, _rows({3: 35}))
    packet_summary = prepare_nhi_review_packet(data_root, output_dir=tmp_path / "review")
    decision_path = _write_json(
        tmp_path / "review" / "decision.json", _decision(packet_summary, **override)
    )
    descriptor_before = _descriptor_bytes(data_root)
    builds_before = sorted((data_root / "curated" / "nhi_fee").iterdir())

    with pytest.raises(NHIReviewError) as error:
        publish_reviewed_nhi_candidate(
            data_root,
            packet_path=Path(packet_summary["packet_path"]),
            decision_path=decision_path,
            actor="unit-test-only-publisher",
        )

    assert error.value.code == expected_code
    assert _descriptor_bytes(data_root) == descriptor_before
    assert sorted((data_root / "curated" / "nhi_fee").iterdir()) == builds_before


def test_publish_rejects_tampered_packet(tmp_path, distribution_identity):
    from taiwan_lab_mcp.nhi_review import (
        NHIReviewError,
        prepare_nhi_review_packet,
        publish_reviewed_nhi_candidate,
    )

    data_root = tmp_path / "data"
    _serve_official(data_root)
    _check(data_root, _rows({3: 35}))
    packet_summary = prepare_nhi_review_packet(data_root, output_dir=tmp_path / "review")
    decision_path = _write_json(tmp_path / "review" / "decision.json", _decision(packet_summary))
    packet_path = Path(packet_summary["packet_path"])
    packet_path.write_bytes(
        packet_path.read_bytes().replace(b"UNIT-REVIEW-G-001", b"UNIT-REVIEW-G-999")
    )

    with pytest.raises(NHIReviewError) as error:
        publish_reviewed_nhi_candidate(
            data_root,
            packet_path=packet_path,
            decision_path=decision_path,
            actor="unit-test-only-publisher",
        )
    assert error.value.code == "REVIEW_DECISION_PACKET_MISMATCH"


def test_publish_rejects_packet_after_a_newer_candidate_arrives(tmp_path, distribution_identity):
    from taiwan_lab_mcp.nhi_review import (
        NHIReviewError,
        prepare_nhi_review_packet,
        publish_reviewed_nhi_candidate,
    )

    data_root = tmp_path / "data"
    _serve_official(data_root)
    _check(data_root, _rows({3: 35}))
    packet_summary = prepare_nhi_review_packet(data_root, output_dir=tmp_path / "review")
    decision_path = _write_json(tmp_path / "review" / "decision.json", _decision(packet_summary))
    _check(data_root, _rows({3: 40}), hour=2)
    descriptor_before = _descriptor_bytes(data_root)

    with pytest.raises(NHIReviewError) as error:
        publish_reviewed_nhi_candidate(
            data_root,
            packet_path=Path(packet_summary["packet_path"]),
            decision_path=decision_path,
            actor="unit-test-only-publisher",
        )
    assert error.value.code == "REVIEW_PACKET_STALE"
    assert _descriptor_bytes(data_root) == descriptor_before


def test_publish_passes_owner_findings_to_the_official_builder(tmp_path, distribution_identity):
    from taiwan_lab_mcp.importers.nhi import NHIImportError
    from taiwan_lab_mcp.nhi_review import prepare_nhi_review_packet, publish_reviewed_nhi_candidate

    data_root = tmp_path / "data"
    _serve_official(data_root)
    _check(data_root, _rows({3: 35}))
    packet_summary = prepare_nhi_review_packet(data_root, output_dir=tmp_path / "review")
    decision = _decision(packet_summary)
    decision["gate_reviews"][1]["finding_counts"]["major"] = 1
    decision_path = _write_json(tmp_path / "review" / "decision.json", decision)
    descriptor_before = _descriptor_bytes(data_root)

    with pytest.raises(NHIImportError) as error:
        publish_reviewed_nhi_candidate(
            data_root,
            packet_path=Path(packet_summary["packet_path"]),
            decision_path=decision_path,
            actor="unit-test-only-publisher",
        )
    assert error.value.code == "OWNER_REVIEW_REJECTED"
    assert _descriptor_bytes(data_root) == descriptor_before


def test_cli_prepare_review_and_publish(tmp_path, distribution_identity, capsys):
    from taiwan_lab_mcp.data_cli import main

    data_root = tmp_path / "data"
    _serve_official(data_root)
    _check(data_root, _rows({3: 35}))
    capsys.readouterr()

    assert (
        main(
            [
                "prepare-review",
                "nhi_fee",
                "--data-dir",
                str(data_root),
                "--output-dir",
                str(tmp_path / "review"),
                "--json",
            ]
        )
        == 0
    )
    packet_summary = json.loads(capsys.readouterr().out)
    assert packet_summary["result"] == "packet_ready"

    bad_decision = _write_json(
        tmp_path / "review" / "bad.json", _decision(packet_summary, packet_sha256="0" * 64)
    )
    publish_args = [
        "publish",
        "nhi_fee",
        "--packet",
        packet_summary["packet_path"],
        "--actor",
        "unit-test-only-publisher",
        "--data-dir",
        str(data_root),
        "--json",
    ]
    assert main([*publish_args, "--decision", str(bad_decision)]) == 5
    failure = json.loads(capsys.readouterr().out)
    assert failure == {
        "operation": "publish",
        "result": "failed",
        "error_code": "REVIEW_DECISION_PACKET_MISMATCH",
    }

    decision = _write_json(tmp_path / "review" / "decision.json", _decision(packet_summary))
    assert main([*publish_args, "--decision", str(decision)]) == 0
    published = json.loads(capsys.readouterr().out)
    assert published["result"] == "published"
    assert published["raw_revision_id"] == packet_summary["candidate_raw_revision_id"]


def test_cli_prepare_review_without_candidate_is_review_gate_exit(
    tmp_path, distribution_identity, capsys
):
    from taiwan_lab_mcp.data_cli import main

    data_root = tmp_path / "data"
    _serve_official(data_root)
    capsys.readouterr()

    code = main(
        [
            "prepare-review",
            "nhi_fee",
            "--data-dir",
            str(data_root),
            "--output-dir",
            str(tmp_path / "review"),
            "--json",
        ]
    )

    assert code == 5
    assert json.loads(capsys.readouterr().out) == {
        "operation": "prepare-review",
        "result": "failed",
        "error_code": "NO_PENDING_CANDIDATE",
    }
