"""TFDA official build under the owner-delegated AI review, and the daily upstream check."""

import csv
import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

import taiwan_lab_mcp.importers.nhi as nhi_importer
from taiwan_lab_mcp.adapters.tfda import TFDAAdapter
from taiwan_lab_mcp.canonical import canonical_json_bytes, sha256_bytes
from taiwan_lab_mcp.config import DataContext
from taiwan_lab_mcp.importers.tfda import (
    TFDA_COLUMNS,
    TFDA_SERVING_GATES,
    TFDAImportError,
    active_tfda_transform,
    build_official_tfda_snapshot,
    build_tfda_snapshot,
)
from taiwan_lab_mcp.tfda_source import run_tfda_upstream_check, run_tfda_upstream_sync

OID = "2.16.886.101.20003.20065.20065"
REVIEWER = "ai-reviewer:claude-opus-5"
ROLE = "ai_reviewer_delegated_by_owner"
REVIEWED_AT = "2026-09-15T11:30:00+08:00"
CLOCK = datetime(2026, 9, 15, 3, 30, tzinfo=timezone.utc)


def _row(number, **values):
    base = dict.fromkeys(TFDA_COLUMNS, "")
    base.update(
        {
            "許可證字號": f"衛部醫器輸字第{number:06d}號",
            "有效日期": "2027/01/31",
            "中文品名": f"合成品項{number}",
            "醫器主類別一": "B 血液學及病理學",
            "醫器次類別一": "B.9225 合成品項",
            "製造商名稱": "Synthetic Maker",
        }
    )
    base.update(values)
    return [base[name] for name in TFDA_COLUMNS]


ROWS = [_row(number) for number in range(1, 12)]


def _zip(rows=ROWS):
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(list(TFDA_COLUMNS))
    writer.writerows(rows)
    archive = io.BytesIO()
    # A fixed entry time keeps identical rows byte-identical across calls.
    entry = zipfile.ZipInfo("68_2.csv", date_time=(2026, 9, 11, 0, 0, 0))
    entry.compress_type = zipfile.ZIP_DEFLATED
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr(entry, (chr(0xFEFF) + buffer.getvalue()).encode("utf-8"))
    return archive.getvalue()


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


def _metadata():
    body = {
        "success": True,
        "result": {
            "publisherOID": OID,
            "identifier": "A21020000I-000053",
            "license": "1",
            "modifiedDate": "2026-09-11 15:57:04",
            "distribution": [
                {
                    "resourceFormat": "CSV",
                    "resourceCharacterEncoding": "UTF-8",
                    "resourceDownloadUrl": "https://data.fda.gov.tw/data/opendata/export/68/csv",
                }
            ],
        },
    }
    return _Response(
        200, json.dumps(body, ensure_ascii=False).encode(), {"Content-Type": "application/json"}
    )


def _zip_response(payload):
    return _Response(200, payload, {"Content-Type": "application/zip"})


def _fetch(data_root, payload):
    report = run_tfda_upstream_sync(
        data_root,
        expected_publisher_oid=OID,
        opener=_Opener(_metadata(), _zip_response(payload)),
        clock=lambda: CLOCK,
    )
    assert report["status"] == "passed"
    return report["raw_revision_id"], report["raw_artifact_data_root_relative_path"]


def _cases(payload, artifact_relative, count=10, rows=ROWS):
    cases = []
    for source_row_number, values in enumerate(rows[:count], start=2):
        cases.append(
            {
                "golden_case_schema_version": 1,
                "case_id": f"TFDA-G-{source_row_number:03d}",
                "source_id": "tfda_devices",
                "acceptance_id": "TFDA-01",
                "source_title": "醫療器材許可證資料集",
                "official_landing_url": "https://data.gov.tw/dataset/9576",
                "official_version_or_modified_at": "2026-09-11 15:57:04",
                "official_source": True,
                "artifact_id": "tfda-primary-zip",
                "raw_artifact_sha256": sha256_bytes(payload),
                "evidence_data_root_relative_path": artifact_relative,
                "fixture_file": None,
                "fixture_sha256": None,
                "transform": active_tfda_transform(),
                "input": {"license_no": values[0]},
                "source_locator": {
                    "locator_type": "tfda_row",
                    "source_row_number": source_row_number,
                },
                "source_row_sha256": sha256_bytes(canonical_json_bytes(values)),
                "expected_status": "ok",
                "expected_fields": {
                    "license_no_raw": values[0],
                    "name_zh_raw": values[10],
                    "classification_codes": ["B.9225"],
                    "ivd_scope": "included",
                },
                "expected_warnings": [],
                "reviewer_id": REVIEWER,
                "reviewer_role": ROLE,
                "identity_assurance": "local_asserted",
                "reviewed_at": REVIEWED_AT,
                "review_status": "approved",
            }
        )
    return cases


def _reviews(**changes):
    return [
        {
            "gate_id": gate_id,
            "reviewer_id": REVIEWER,
            "reviewer_role": ROLE,
            "reviewed_at": REVIEWED_AT,
            "finding_counts": {"critical": 0, "major": 0, "minor": 0},
            "comments": "Synthetic delegated review for the unit test.",
            **changes,
        }
        for gate_id in TFDA_SERVING_GATES
    ]


@pytest.fixture
def distribution(monkeypatch):
    monkeypatch.setattr(
        nhi_importer, "_application_build_identity", lambda: ("distribution", "d" * 64)
    )


def _build(data_root, **overrides):
    payload = _zip()
    raw_revision_id, artifact_relative = _fetch(data_root, payload)
    arguments = {
        "raw_revision_id": raw_revision_id,
        "approved_golden_cases": _cases(payload, artifact_relative),
        "owner_reviews": _reviews(),
        "publisher_actor_id": "unit-test-publisher",
    }
    arguments.update(overrides)
    return build_official_tfda_snapshot(data_root, **arguments)


def test_official_build_publishes_the_delegated_ai_review(tmp_path, distribution):
    built = _build(tmp_path)
    assert (built["rows"], built["generation"]) == (11, 1)
    build_dir = tmp_path / "curated" / "tfda_devices" / built["snapshot_id"]
    review = json.loads((build_dir / "audit" / "reviews" / "PUB-R1-OWNER.json").read_bytes())
    assert (review["reviewer_id"], review["reviewer_role"]) == (REVIEWER, ROLE)
    assert (review["protocol_id"], review["protocol_version"]) == ("tfda-r1-ai-review", "1")
    certificate = json.loads((build_dir / "audit" / "golden-qualification.json").read_bytes())
    assert certificate["official_qualification_status"] == "approved"
    assert len(certificate["approved_distinct_case_ids"]) == 10

    adapter = TFDAAdapter(DataContext(mode="official_snapshot", data_root=tmp_path))
    adapter.context = DataContext(mode="official_snapshot", data_root=tmp_path, clock=lambda: CLOCK)
    result = adapter.get_license("衛部醫器輸字第000001號")
    assert result.result_status == "ok"
    assert result.provenance.curated_build_id == built["snapshot_id"]
    assert "官方標示更新時間 2026-09-11 15:57:04" in result.provenance.attribution


def test_official_build_refuses_a_development_install(tmp_path, monkeypatch):
    monkeypatch.setattr(
        nhi_importer, "_application_build_identity", lambda: ("development", "d" * 64)
    )
    with pytest.raises(TFDAImportError) as error:
        _build(tmp_path)
    assert error.value.code == "APPLICATION_BUILD_IDENTITY_MISSING"


def test_official_build_requires_the_protocol_reviewer(tmp_path, distribution):
    with pytest.raises(TFDAImportError) as error:
        _build(tmp_path, owner_reviews=_reviews(reviewer_id="專案負責人"))
    assert error.value.code == "OWNER_REVIEW_REVIEWER_MISMATCH"
    assert not (tmp_path / "curated").exists()


def test_official_build_requires_ten_passing_cases(tmp_path, distribution):
    payload = _zip()
    raw_revision_id, artifact_relative = _fetch(tmp_path, payload)
    common = {
        "raw_revision_id": raw_revision_id,
        "owner_reviews": _reviews(),
        "publisher_actor_id": "unit-test-publisher",
    }
    with pytest.raises(TFDAImportError) as error:
        build_official_tfda_snapshot(
            tmp_path, approved_golden_cases=_cases(payload, artifact_relative, 9), **common
        )
    assert error.value.code == "GOLDEN_CASES_INSUFFICIENT"
    cases = _cases(payload, artifact_relative)
    cases[0]["expected_fields"]["name_zh_raw"] = "不是這個品名"
    with pytest.raises(TFDAImportError) as error:
        build_official_tfda_snapshot(tmp_path, approved_golden_cases=cases, **common)
    assert error.value.code == "GOLDEN_CASE_FAILED"
    cases = _cases(payload, artifact_relative)
    cases[0]["reviewer_id"] = "someone-else"
    with pytest.raises(TFDAImportError) as error:
        build_official_tfda_snapshot(tmp_path, approved_golden_cases=cases, **common)
    assert error.value.code == "GOLDEN_CASE_NOT_APPROVED"
    assert not (tmp_path / "curated").exists()


def _descriptor(data_root):
    return json.loads((data_root / "manifests" / "current" / "tfda_devices.json").read_bytes())


def _check(data_root, *responses):
    return run_tfda_upstream_check(
        data_root,
        expected_publisher_oid=OID,
        actor="unit-test-checker",
        opener=_Opener(*responses),
        clock=lambda: CLOCK,
    )


def test_check_with_the_same_zip_records_success(tmp_path):
    build_tfda_snapshot(_zip(), tmp_path)
    before = _descriptor(tmp_path)
    summary = _check(tmp_path, _metadata(), _zip_response(_zip()))
    after = _descriptor(tmp_path)
    assert (summary["result"], summary["rows"]) == ("unchanged", 11)
    assert after["generation"] == before["generation"] + 1
    assert after["serving_snapshot_id"] == before["serving_snapshot_id"]
    assert (after["check_result"], after["stale"]) == ("success", False)
    assert after["last_successful_check_at"] == "2026-09-15T03:30:00Z"


def test_check_with_a_new_zip_keeps_serving_and_writes_a_diff(tmp_path):
    build_tfda_snapshot(_zip(), tmp_path)
    before = _descriptor(tmp_path)
    new_rows = ROWS[1:] + [_row(99), _row(2, 中文品名="改過的品名")]
    summary = _check(tmp_path, _metadata(), _zip_response(_zip(new_rows)))
    after = _descriptor(tmp_path)
    assert summary["result"] == "changed"
    assert after["serving_snapshot_id"] == before["serving_snapshot_id"]
    assert after["latest_candidate_status"] == "review_pending"
    assert after["stale_reason_codes"] == ["newer_candidate_pending_review"]
    diff = json.loads((tmp_path / Path(summary["diff_data_root_relative_path"])).read_bytes())
    assert diff["added_permits"] == ["衛部醫器輸字第000099號"]
    assert diff["removed_permits"] == ["衛部醫器輸字第000001號"]
    assert (diff["rows_only_in_candidate"], diff["rows_only_in_serving"]) == (2, 1)
    text = (tmp_path / Path(summary["diff_summary_data_root_relative_path"])).read_text(
        encoding="utf-8"
    )
    assert "衛部醫器輸字第000099號" in text

    adapter = TFDAAdapter(DataContext(mode="official_snapshot", data_root=tmp_path))
    result = adapter.get_license("衛部醫器輸字第000001號")
    assert result.result_status == "ok"
    assert "newer_candidate_pending_review" in result.warnings


def test_check_failure_keeps_serving_and_marks_stale(tmp_path):
    build_tfda_snapshot(_zip(), tmp_path)
    before = _descriptor(tmp_path)
    summary = _check(tmp_path, _metadata(), _Response(503, b"down", {"Content-Type": "text/plain"}))
    after = _descriptor(tmp_path)
    assert (summary["result"], summary["failed_stage"]) == ("failed", "fetch")
    assert after["stale_reason_codes"] == ["upstream_verification_failed"]
    assert after["last_successful_check_at"] == before["last_successful_check_at"]


def test_check_without_a_serving_snapshot_only_reports(tmp_path):
    summary = _check(tmp_path, _metadata(), _zip_response(_zip()))
    assert summary["result"] == "no_serving_snapshot"
    assert not (tmp_path / "manifests").exists()


def test_cli_check_routes_tfda(tmp_path, monkeypatch, capsys):
    import taiwan_lab_mcp.data_cli as data_cli

    calls = []

    def fake_check(data_root, **kwargs):
        calls.append((data_root, kwargs))
        return {"result": "unchanged", "failed_stage": None, "error_code": None}

    monkeypatch.setattr("taiwan_lab_mcp.tfda_source.run_tfda_upstream_check", fake_check)
    exit_code = data_cli.main(
        [
            "check",
            "tfda_devices",
            "--publisher-oid",
            OID,
            "--actor",
            "unit-test-checker",
            "--data-dir",
            str(tmp_path),
            "--json",
        ]
    )
    assert exit_code == 0
    assert calls == [(tmp_path, {"expected_publisher_oid": OID, "actor": "unit-test-checker"})]
    assert json.loads(capsys.readouterr().out)["result"] == "unchanged"


def test_check_diff_lists_renewals_even_when_the_row_count_is_unchanged(tmp_path):
    build_tfda_snapshot(_zip(), tmp_path)
    renewed = [list(row) for row in ROWS]
    renewed[1][TFDA_COLUMNS.index("有效日期")] = "2032/01/31"
    renewed[2][TFDA_COLUMNS.index("中文品名")] = "改過的品名"
    summary = _check(tmp_path, _metadata(), _zip_response(_zip(renewed)))
    assert summary["result"] == "changed"
    diff = json.loads((tmp_path / Path(summary["diff_data_root_relative_path"])).read_bytes())
    assert diff["row_counts"] == {"serving": 11, "candidate": 11}
    assert (diff["added_permits"], diff["removed_permits"]) == ([], [])
    assert diff["changed_permits"] == [
        {
            "license_no": "衛部醫器輸字第000002號",
            "fields": [{"column": "有效日期", "before": "2027/01/31", "after": "2032/01/31"}],
        },
        {
            "license_no": "衛部醫器輸字第000003號",
            "fields": [{"column": "中文品名", "before": "合成品項3", "after": "改過的品名"}],
        },
    ]
    assert diff["validity_extended_permits"] == ["衛部醫器輸字第000002號"]
    text = (tmp_path / Path(summary["diff_summary_data_root_relative_path"])).read_text(
        encoding="utf-8"
    )
    assert "內容有改的許可證字號（2 個）" in text
    assert "有效日期往後延（通常是展延）：1 個" in text
    assert "衛部醫器輸字第000002號：有效日期 2027/01/31 → 2032/01/31" in text
