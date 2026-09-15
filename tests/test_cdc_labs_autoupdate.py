"""CDC roster daily update: checked new roster versions publish without a person (OD-04 A).

Owner 2026-09-15: 「A 開始做疾管署」, A being automatic checks like NHI and TFDA. Fixtures are
synthetic rosters and a synthetic official page.
"""

import io
import json
import zipfile
from datetime import datetime, timezone
from urllib.parse import quote

import pytest

import taiwan_lab_mcp.importers.nhi as nhi_importer
from taiwan_lab_mcp.adapters.cdc import CDCAdapter
from taiwan_lab_mcp.config import DataContext

CLOCK = datetime(2026, 9, 21, 1, 30, tzinfo=timezone.utc)
HEADER = (
    "證號",
    "縣市別",
    "機構名稱",
    "部門別",
    "疾病代碼",
    "疾病名稱",
    "檢驗目的",
    "檢驗方法",
    "住址",
    "連絡電話",
    "結束時間",
    "最近一次年度能力試驗審查",
)


def _row(certificate, method="病原體分離、鑑定(A1)", **changes):
    values = dict(
        zip(
            HEADER,
            (
                certificate,
                "高雄市",
                f"合成醫院{certificate}",
                "檢驗科",
                "002a",
                "副傷寒",
                "確認",
                method,
                "高雄市合成區1號",
                "(07)000-0001",
                "2028/12/31",
                "2026/09/08",
            ),
        )
    )
    values.update(changes)
    return tuple(values[name] for name in HEADER)


ROWS = [
    _row("097036"),
    _row("097036", "血清型別鑑定(B2)"),
    _row("098029", 最近一次年度能力試驗審查="無需能力試驗"),
    _row("19SC0001", 最近一次年度能力試驗審查=""),
] + [_row(f"1000{number:02d}") for number in range(1, 9)]


def _ods(rows, version):
    def cells(values):
        return "".join(
            f"<table:table-cell><text:p>{value}</text:p></table:table-cell>"
            if value
            else "<table:table-cell/>"
            for value in values
        )

    body = "".join(f"<table:table-row>{cells(row)}</table:table-row>" for row in rows)
    content = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
        f'<office:body><office:spreadsheet><table:table table:name="{version}名冊">'
        f"<table:table-row>{cells(['傳染病檢驗機構認可項目名冊'])}</table:table-row>"
        f"<table:table-row>{cells(HEADER)}</table:table-row>{body}"
        "</table:table></office:spreadsheet></office:body></office:document-content>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            zipfile.ZipInfo("mimetype"), b"application/vnd.oasis.opendocument.spreadsheet"
        )
        info = zipfile.ZipInfo("content.xml", date_time=(2026, 9, 14, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, content.encode("utf-8"))
    return buffer.getvalue()


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


def _responses(rows, version):
    label = f"傳染病認可檢驗機構名冊{version}.ods"
    page = (
        f'<html><body><div class="download"><a href="/File/Get/token{version}">{label}</a>'
        "</div></body></html>"
    ).encode("utf-8")
    return (
        _Response(200, page, {"Content-Type": "text/html; charset=utf-8"}),
        _Response(
            200,
            _ods(rows, version),
            {
                "Content-Type": "application/octet-stream",
                "Content-Disposition": f"attachment; filename*=UTF-8''{quote(label)}",
            },
        ),
    )


@pytest.fixture
def distribution(monkeypatch):
    monkeypatch.setattr(
        nhi_importer, "_application_build_identity", lambda: ("distribution", "d" * 64)
    )


def _serve(data_root):
    from taiwan_lab_mcp.importers.cdc_labs import build_cdc_labs_snapshot

    return build_cdc_labs_snapshot(_ods(ROWS, "1150914"), data_root)


def _auto(data_root, rows, version="1150921"):
    from taiwan_lab_mcp.cdc_labs_autoupdate import run_cdc_labs_auto_update

    return run_cdc_labs_auto_update(
        data_root,
        actor="unit-test-cdc-auto-update",
        opener=_Opener(*_responses(rows, version)),
        clock=lambda: CLOCK,
    )


def _descriptor(data_root):
    return json.loads(
        (data_root / "manifests" / "current" / "cdc_authorized_labs.json").read_bytes()
    )


def _builds(data_root):
    return sorted(path.name for path in (data_root / "curated" / "cdc_authorized_labs").iterdir())


def test_same_roster_needs_no_publish(tmp_path, distribution):
    _serve(tmp_path)
    before = _descriptor(tmp_path)

    summary = _auto(tmp_path, ROWS, version="1150914")

    assert summary["result"] == "unchanged"
    assert len(_builds(tmp_path)) == 1
    after = _descriptor(tmp_path)
    assert after["serving_snapshot_id"] == before["serving_snapshot_id"]
    assert after["generation"] == before["generation"] + 1
    assert (after["stale"], after["latest_seen_version"]) == (False, "1150914")


def test_checked_new_roster_is_published_automatically(tmp_path, distribution):
    _serve(tmp_path)
    before = _descriptor(tmp_path)
    new_rows = [ROWS[0], _row("097036", "血清型別鑑定(B3)"), *ROWS[2:]]

    summary = _auto(tmp_path, new_rows)

    assert (summary["result"], summary["already_reported"]) == ("published", False)
    after = _descriptor(tmp_path)
    assert after["serving_snapshot_id"] == summary["published_snapshot_id"]
    assert after["serving_snapshot_id"] != before["serving_snapshot_id"]
    assert (after["stale"], after["latest_candidate_status"]) == (False, "none")
    build_dir = tmp_path / "curated" / "cdc_authorized_labs" / summary["published_snapshot_id"]
    review = json.loads((build_dir / "audit" / "reviews" / "ODS-R1-CONTENT.json").read_bytes())
    assert review["reviewer_id"] == "automated-check:cdc-labs-auto-update"
    assert review["reviewer_role"] == "automated_checker_delegated_by_owner"
    assert (review["protocol_id"], review["protocol_version"]) == ("cdc-labs-r1-auto-review", "2")
    assert any(ref["artifact_id"] == "cdc-labs-auto-roundtrip" for ref in review["evidence_refs"])
    certificate = json.loads((build_dir / "audit" / "golden-qualification.json").read_bytes())
    assert len(certificate["approved_distinct_case_ids"]) >= 10
    diff_summary = (tmp_path / summary["diff_summary_data_root_relative_path"]).read_text(
        encoding="utf-8"
    )
    assert "上游有新版" in diff_summary
    assert "1150914" in diff_summary and "1150921" in diff_summary

    adapter = CDCAdapter(DataContext(mode="official_snapshot", data_root=tmp_path))
    result = adapter.find_authorized_lab("097036")
    assert [item.record.method for item in result.items] == [
        "病原體分離、鑑定(A1)",
        "血清型別鑑定(B3)",
    ]
    assert result.provenance.official_version_raw == "1150921"


@pytest.mark.parametrize(
    ("rows", "reason"),
    [
        (ROWS[:10], "row_count_change_exceeds_10_percent"),
        (
            [_row("097036", 住址=""), _row("097036", "血清型別鑑定(B2)", 住址=""), *ROWS[2:]],
            "blank_rate_increase:住址",
        ),
    ],
)
def test_large_change_is_held_back_and_reported_once(tmp_path, distribution, rows, reason):
    _serve(tmp_path)
    before = _descriptor(tmp_path)

    first = _auto(tmp_path, rows)
    assert first["result"] == "blocked"
    assert reason in first["block_reasons"]
    assert first["already_reported"] is False
    after = _descriptor(tmp_path)
    assert after["serving_snapshot_id"] == before["serving_snapshot_id"]
    assert after["latest_candidate_status"] == "review_pending"

    second = _auto(tmp_path, rows)
    assert (second["result"], second["already_reported"]) == ("blocked", True)
    assert len(_builds(tmp_path)) == 1


def test_failed_full_table_check_keeps_the_old_roster(tmp_path, distribution, monkeypatch):
    import taiwan_lab_mcp.cdc_labs_autoupdate as autoupdate

    def broken(*args, **kwargs):
        raise autoupdate.AutoUpdateError("ROUNDTRIP_MISMATCH")

    monkeypatch.setattr(autoupdate, "verify_cdc_labs_roundtrip", broken)
    _serve(tmp_path)
    before = _descriptor(tmp_path)
    summary = _auto(tmp_path, [ROWS[0], _row("097036", "血清型別鑑定(B3)"), *ROWS[2:]])
    assert (summary["result"], summary["error_code"]) == (
        "auto_publish_failed",
        "ROUNDTRIP_MISMATCH",
    )
    assert _descriptor(tmp_path)["serving_snapshot_id"] == before["serving_snapshot_id"]


def test_development_install_never_auto_publishes(tmp_path, monkeypatch):
    monkeypatch.setattr(
        nhi_importer, "_application_build_identity", lambda: ("development", "d" * 64)
    )
    _serve(tmp_path)
    before = _descriptor(tmp_path)
    summary = _auto(tmp_path, [ROWS[0], _row("097036", "血清型別鑑定(B3)"), *ROWS[2:]])
    assert (summary["result"], summary["error_code"]) == (
        "auto_publish_failed",
        "APPLICATION_BUILD_IDENTITY_MISSING",
    )
    assert _descriptor(tmp_path)["serving_snapshot_id"] == before["serving_snapshot_id"]


def test_unreachable_page_marks_the_roster_stale(tmp_path, distribution):
    from taiwan_lab_mcp.cdc_labs_autoupdate import run_cdc_labs_auto_update

    _serve(tmp_path)
    summary = run_cdc_labs_auto_update(
        tmp_path, actor="unit-test", opener=_Opener(_Response(503)), clock=lambda: CLOCK
    )
    assert (summary["result"], summary["failed_stage"]) == ("failed", "discover")
    descriptor = _descriptor(tmp_path)
    assert (descriptor["stale"], descriptor["stale_reason_codes"]) == (
        True,
        ["upstream_verification_failed"],
    )


def test_no_serving_roster_only_reports(tmp_path, distribution):
    summary = _auto(tmp_path, ROWS)
    assert summary["result"] == "no_serving_snapshot"
    assert not (tmp_path / "curated").exists()


def test_independent_roundtrip_agrees_with_the_published_build(tmp_path, distribution):
    from taiwan_lab_mcp.cdc_labs_autoupdate import verify_cdc_labs_roundtrip

    _serve(tmp_path)
    new_rows = [ROWS[0], _row("097036", "血清型別鑑定(B3)"), *ROWS[2:]]
    published = _auto(tmp_path, new_rows)
    db_path = (
        tmp_path
        / "curated"
        / "cdc_authorized_labs"
        / published["published_snapshot_id"]
        / "data.sqlite3"
    )
    report = verify_cdc_labs_roundtrip(db_path, _ods(new_rows, "1150921"))
    assert (report["result"], report["rows_compared"]) == ("passed", 12)


def test_cli_check_cdc_roster_takes_no_publisher_oid(tmp_path, monkeypatch, capsys):
    import taiwan_lab_mcp.data_cli as data_cli

    calls = []

    def fake(data_root, **kwargs):
        calls.append((data_root, kwargs))
        return {"result": "published", "failed_stage": None, "error_code": None}

    monkeypatch.setattr("taiwan_lab_mcp.cdc_labs_autoupdate.run_cdc_labs_auto_update", fake)
    arguments = ["--actor", "unit-test", "--data-dir", str(tmp_path)]
    assert (
        data_cli.main(["check", "cdc_authorized_labs", *arguments, "--auto-publish", "--json"]) == 0
    )
    assert calls == [(tmp_path, {"actor": "unit-test"})]
    assert json.loads(capsys.readouterr().out)["result"] == "published"
    for argv in (
        ["check", "cdc_authorized_labs", "--publisher-oid", "1.2.3", *arguments],
        ["check", "nhi_fee", *arguments],
    ):
        with pytest.raises(SystemExit) as error:
            data_cli.main(argv)
        assert error.value.code == 2
