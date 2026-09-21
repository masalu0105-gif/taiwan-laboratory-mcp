"""CDC recognized laboratory roster: find the attachment on the official page, keep raw ODS.

Owner 2026-09-15: 「A 開始做疾管署」. The official page lists shared site links next to the
roster attachment, so discovery picks the attachment by its label (SDD 10.4). Fixtures are
synthetic; the page shape follows the 2026-09-15 page.
"""

import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone
from urllib.parse import quote

import pytest

LANDING = "https://www.cdc.gov.tw/Category/Page/02d-tR1nzB8QuflX-NmM_w"
ROSTER_URL = "https://www.cdc.gov.tw/File/Get/35jzmDYRqYO_xsXgEqAivA"
LABEL = "傳染病認可檢驗機構名冊1150914.ods"
SHARED_LINK = (
    '<a href="/File/Get/sqrAKrJg_Uq8Ki5B0HtO3g?path=abc&amp;name=def" target="_blank">'
    "傳染病檢驗機構品質保證作業要求</a>"
)
ROSTER_LINK = (
    f'<a href="/File/Get/35jzmDYRqYO_xsXgEqAivA" target="_blank" title="{LABEL}(檔案下載)">'
    f"{LABEL}</a>"
)
TEACHING_LINK = (
    '<a href="/File/Get/znEEhUJ-b8S-ALdCZBHtnA" target="_blank">'
    "(1150624教材)115年度第一次教育訓練.pdf</a>"
)
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
ROW = (
    "097036",
    "高雄市",
    "合成總醫院",
    "檢驗科",
    "002",
    "傷寒",
    "確認",
    "病原體分離、鑑定(A1)",
    "高雄市合成區測試路5號",
    "(07)000-1013",
    "2028/12/31",
    "2026/09/08",
)


def _page(*links):
    anchors = links if links else (SHARED_LINK, ROSTER_LINK, TEACHING_LINK)
    return (
        "<html><body><nav>"
        + anchors[0]
        + '</nav><div class="download"><h3>附件</h3><p>'
        + "</p><p>".join(anchors[1:])
        + "</p></div><span>最後更新日期 2023/9/27</span></body></html>"
    ).encode("utf-8")


def _ods(sheet_name="1150914名冊"):
    def cells(values):
        return "".join(f"<table:table-cell><text:p>{v}</text:p></table:table-cell>" for v in values)

    content = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
        f'<office:body><office:spreadsheet><table:table table:name="{sheet_name}">'
        f"<table:table-row>{cells(['傳染病檢驗機構認可項目名冊'])}</table:table-row>"
        f"<table:table-row>{cells(HEADER)}</table:table-row>"
        f"<table:table-row>{cells(ROW)}</table:table-row>"
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
        self.urls = []

    def open(self, request, timeout):
        self.urls.append(request.full_url)
        return self.responses.pop(0)


def _html(body):
    return _Response(200, body, {"Content-Type": "text/html; charset=utf-8"})


def _attachment(body, *, filename=LABEL, content_type="application/octet-stream"):
    headers = {"Content-Type": content_type}
    if filename is not None:
        headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(filename)}"
    return _Response(200, body, headers)


def _clock():
    return datetime(2026, 9, 15, 5, 0, tzinfo=timezone.utc)


def _sync(data_root, opener):
    from taiwan_lab_mcp.cdc_source import run_cdc_labs_upstream_sync

    return run_cdc_labs_upstream_sync(data_root, opener=opener, clock=_clock)


def test_discover_picks_the_roster_attachment_by_its_label():
    from taiwan_lab_mcp.cdc_source import discover_cdc_labs_resource

    page = _page()
    discovery = discover_cdc_labs_resource(page, landing_url=LANDING)

    assert discovery == {
        "provider": "衛生福利部疾病管制署",
        "dataset_name": "傳染病認可檢驗機構名冊",
        "landing_url": LANDING,
        "landing_sha256": hashlib.sha256(page).hexdigest(),
        "landing_last_updated_raw": "2023/9/27",
        "attachment_label": LABEL,
        "roster_version_raw": "1150914",
        "resource_url": ROSTER_URL,
        "license_name": "衛生福利部疾病管制署政府網站資料開放宣告",
        "license_url": "https://www.cdc.gov.tw/Category/FPage/TxkBIR9agw_IBRRmvn9TcQ",
    }


def test_discover_accepts_a_space_before_the_roster_version():
    """CDC spaced the version on 2026-09-18: 傳染病認可檢驗機構名冊 1150918.ods."""
    from taiwan_lab_mcp.cdc_source import discover_cdc_labs_resource

    spaced_label = "傳染病認可檢驗機構名冊 1150918.ods"
    page = _page(SHARED_LINK, ROSTER_LINK.replace(LABEL, spaced_label), TEACHING_LINK)

    discovery = discover_cdc_labs_resource(page, landing_url=LANDING)

    assert discovery["attachment_label"] == spaced_label
    assert discovery["roster_version_raw"] == "1150918"
    assert discovery["resource_url"] == ROSTER_URL


@pytest.mark.parametrize(
    ("links", "expected_code"),
    [
        ((SHARED_LINK, TEACHING_LINK), "DISCOVERY_RESOURCE_MISSING"),
        (
            (
                SHARED_LINK,
                ROSTER_LINK,
                ROSTER_LINK.replace("1150914", "1150909").replace("35jzm", "otherT"),
            ),
            "DISCOVERY_RESOURCE_AMBIGUOUS",
        ),
        (
            (SHARED_LINK, ROSTER_LINK.replace('"/File/Get/', '"https://evil.example/File/Get/')),
            "FETCH_HOST_NOT_ALLOWED",
        ),
        (
            (SHARED_LINK, ROSTER_LINK.replace('"/File/Get/35jzm', '"/Uploads/35jzm')),
            "DISCOVERY_RESOURCE_MISSING",
        ),
        (
            (SHARED_LINK, ROSTER_LINK.replace("1150914", "115091")),
            "DISCOVERY_RESOURCE_MISSING",
        ),
    ],
)
def test_discover_rejects_missing_ambiguous_or_offsite_attachments(links, expected_code):
    from taiwan_lab_mcp.cdc_source import discover_cdc_labs_resource
    from taiwan_lab_mcp.fetch import FetchError

    with pytest.raises(FetchError) as error:
        discover_cdc_labs_resource(_page(*links), landing_url=LANDING)
    assert error.value.code == expected_code


def test_upstream_sync_keeps_the_raw_ods_and_writes_a_validation_report(tmp_path):
    page, payload = _page(), _ods()
    opener = _Opener(_html(page), _attachment(payload))

    report = _sync(tmp_path, opener)

    assert opener.urls == [LANDING, ROSTER_URL]
    assert (report["source_id"], report["status"], report["stage"]) == (
        "cdc_authorized_labs",
        "passed",
        "validate",
    )
    assert report["candidate_status"] == "none"
    assert report["summary"]["rows"] == 1
    raw_dir = tmp_path / "raw" / "cdc_authorized_labs" / report["raw_revision_id"]
    assert (raw_dir / "artifacts" / "source.ods").read_bytes() == payload
    assert report["raw_artifact_data_root_relative_path"] == (
        f"raw/cdc_authorized_labs/{report['raw_revision_id']}/artifacts/source.ods"
    )
    fetch = json.loads((raw_dir / "fetch.json").read_bytes())
    assert fetch["source_id"] == "cdc_authorized_labs"
    assert fetch["discovery"]["roster_version_raw"] == "1150914"
    assert fetch["discovery"]["landing_sha256"] == hashlib.sha256(page).hexdigest()
    assert fetch["artifact"]["media_type_verified"] == (
        "application/vnd.oasis.opendocument.spreadsheet"
    )
    assert fetch["artifact"]["sha256"] == hashlib.sha256(payload).hexdigest()
    assert (tmp_path / report["report_data_root_relative_path"]).is_file()
    assert not (tmp_path / "curated").exists()
    assert not (tmp_path / "manifests").exists()


def test_same_bytes_reuse_the_raw_revision(tmp_path):
    first = _sync(tmp_path, _Opener(_html(_page()), _attachment(_ods())))
    fetch_path = tmp_path / "raw" / "cdc_authorized_labs" / first["raw_revision_id"] / "fetch.json"
    fetch_before = fetch_path.read_bytes()
    # The page itself changed (a new last-updated date), the roster did not.
    changed_page = _page().replace(b"2023/9/27", b"2026/9/16")
    second = _sync(tmp_path, _Opener(_html(changed_page), _attachment(_ods())))

    assert second["raw_revision_id"] == first["raw_revision_id"]
    assert fetch_path.read_bytes() == fetch_before


@pytest.mark.parametrize(
    ("response", "expected_code"),
    [
        (_attachment(b"<html>login</html>", content_type="text/html"), "FETCH_CONTENT_TYPE"),
        (
            _attachment(_ods(), filename="傳染病認可檢驗機構名冊1150913.ods"),
            "DISCOVERY_ATTACHMENT_MISMATCH",
        ),
    ],
)
def test_wrong_download_fails_at_fetch_and_keeps_no_raw(tmp_path, response, expected_code):
    report = _sync(tmp_path, _Opener(_html(_page()), response))

    assert (report["status"], report["stage"], report["error_code"]) == (
        "failed",
        "fetch",
        expected_code,
    )
    assert report["raw_revision_id"] is None
    assert not (tmp_path / "raw").exists()


@pytest.mark.parametrize(
    ("payload", "expected_stage", "expected_code"),
    [
        (_ods(sheet_name="1150913名冊"), "validate", "ODS_VERSION_MISMATCH"),
        (b"PK\x03\x04 not really a zip", "parse", "ODS_NOT_ZIP"),
    ],
)
def test_invalid_roster_keeps_raw_and_fails_validation(
    tmp_path, payload, expected_stage, expected_code
):
    report = _sync(tmp_path, _Opener(_html(_page()), _attachment(payload)))

    assert (report["status"], report["stage"], report["error_code"]) == (
        "failed",
        expected_stage,
        expected_code,
    )
    raw = tmp_path / report["raw_artifact_data_root_relative_path"]
    assert raw.read_bytes() == payload


def test_page_fetch_failure_keeps_no_raw(tmp_path):
    report = _sync(tmp_path, _Opener(_Response(503)))

    assert (report["status"], report["stage"], report["error_code"]) == (
        "failed",
        "discover",
        "FETCH_HTTP_STATUS",
    )
    assert not (tmp_path / "raw").exists()


def test_cli_sync_cdc_labs_requires_the_explicit_upstream_flag(tmp_path, monkeypatch, capsys):
    import taiwan_lab_mcp.cdc_source as cdc_source
    from taiwan_lab_mcp.data_cli import main

    reports = [
        {"status": "passed", "stage": "validate"},
        {"status": "failed", "stage": "fetch"},
        {"status": "failed", "stage": "validate"},
    ]
    calls = []

    def fake(data_root):
        calls.append(data_root)
        return reports[len(calls) - 1]

    monkeypatch.setattr(cdc_source, "run_cdc_labs_upstream_sync", fake)
    arguments = ["sync", "cdc_authorized_labs", "--data-dir", str(tmp_path)]
    assert [main([*arguments, "--upstream", "--json"]) for _ in reports] == [0, 3, 4]
    assert calls == [tmp_path] * 3
    capsys.readouterr()
    with pytest.raises(SystemExit) as error:
        main([*arguments, "--json"])
    assert error.value.code == 2
