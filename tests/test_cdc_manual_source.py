"""CDC specimen collection manual: find both attachments, open the viewers, keep the raw PDFs.

Owner 2026-09-15: 「好 接下來做疾管署採檢手冊」. The official page links each PDF to an HTML viewer
that points at /Uploads/<uuid>.pdf (SDD 10.3). Fixtures are synthetic; the page and viewer shapes
follow the 2026-09-15 pages.
"""

import hashlib
import json
from datetime import datetime, timezone

import pytest

LANDING = "https://www.cdc.gov.tw/Category/Page/WV_GRwCIYrWQsEVa8ctTWg"
MANUAL_LABEL = "衛生福利部疾病管制署傳染病檢體採檢手冊-1150826版.pdf"
REVISION_LABEL = "傳染病檢體採檢手冊修訂對照表-1150826.pdf"
MANUAL_VIEWER = "https://www.cdc.gov.tw/File/Get/co-Lw-KlHBdl-j84lxzbig"
REVISION_VIEWER = "https://www.cdc.gov.tw/File/Get/cBtNn3rYwlBFGthaclYfYg"
MANUAL_UUID = "11111111-2222-4333-8444-555555555555"
REVISION_UUID = "66666666-7777-4888-9999-aaaaaaaaaaaa"
SHARED_LINK = (
    '<a href="/File/Get/sqrAKrJg_Uq8Ki5B0HtO3g?path=abc&amp;name=def" '
    'title="傳染病檢驗機構品質保證作業要求.pdf(另開新視窗)">傳染病檢驗機構品質保證作業要求</a>'
)
METHODS_LINK = '<a href="/Category/Page/4pQgzB07prAqzxE_zUDOGw">傳染病標準檢驗方法手冊</a>'


def _link(token, label):
    return f'<a href="/File/Get/{token}" target="_blank" title="{label}(另開新視窗)">{label}</a>'


MANUAL_LINK = _link("co-Lw-KlHBdl-j84lxzbig", MANUAL_LABEL)
REVISION_LINK = _link("cBtNn3rYwlBFGthaclYfYg", REVISION_LABEL)


def _page(*attachments, updated="2026/5/11"):
    links = attachments if attachments else (MANUAL_LINK, REVISION_LINK)
    return (
        f"<html><body><nav><ul><li>{METHODS_LINK}</li><li>{SHARED_LINK}</li></ul></nav>"
        '<div class="download"><h3>附件</h3><p>'
        + "</p><p>".join(links)
        + f'</p></div><div class="date text-right"> 最後更新日期 {updated} </div></body></html>'
    ).encode("utf-8")


def _viewer(label, uuid, *, download=None, host=""):
    download = label if download is None else download
    return (
        f"<!DOCTYPE html><html><head><title>{label} - 衛生福利部疾病管制署</title></head><body>"
        f'<h1 style="display: none">{label}</h1><div class="viewer-text">{label}'
        f'<a class="nav-link viewer-button" href="{host}/Uploads/{uuid}.pdf" title="{label}" '
        f'download="{download}">下載</a></div>'
        f'<embed id="embedPdf" src="{host}/Uploads/{uuid}.pdf#toolbar=0" type="application/pdf">'
        "</body></html>"
    ).encode("utf-8")


def _pdf(marker):
    return b"%PDF-1.7\n% synthetic " + marker.encode("ascii") + b"\n1 0 obj\n<<>>\nendobj\n%%EOF\n"


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


def _pdf_response(body, content_type="application/pdf"):
    return _Response(200, body, {"Content-Type": content_type})


def _responses(
    *,
    page=None,
    manual=None,
    revision=None,
    manual_uuid=MANUAL_UUID,
    revision_uuid=REVISION_UUID,
):
    return (
        _html(page or _page()),
        _html(_viewer(MANUAL_LABEL, manual_uuid)),
        manual or _pdf_response(_pdf("manual")),
        _html(_viewer(REVISION_LABEL, revision_uuid)),
        revision or _pdf_response(_pdf("revision")),
    )


def _clock():
    return datetime(2026, 9, 15, 14, 0, tzinfo=timezone.utc)


def _sync(data_root, opener):
    from taiwan_lab_mcp.cdc_manual_source import run_cdc_manual_upstream_sync

    return run_cdc_manual_upstream_sync(data_root, opener=opener, clock=_clock)


def test_discover_finds_the_manual_and_its_revision_table():
    from taiwan_lab_mcp.cdc_manual_source import discover_cdc_manual_resources

    page = _page()
    discovery = discover_cdc_manual_resources(page, landing_url=LANDING)

    assert discovery == {
        "provider": "衛生福利部疾病管制署",
        "dataset_name": "傳染病檢體採檢手冊",
        "landing_url": LANDING,
        "landing_sha256": hashlib.sha256(page).hexdigest(),
        "landing_last_updated_raw": "2026/5/11",
        "manual_version_raw": "1150826",
        "documents": [
            {"role": "manual", "attachment_label": MANUAL_LABEL, "viewer_url": MANUAL_VIEWER},
            {
                "role": "revision_table",
                "attachment_label": REVISION_LABEL,
                "viewer_url": REVISION_VIEWER,
            },
        ],
        "license_name": "衛生福利部疾病管制署政府網站資料開放宣告",
        "license_url": "https://www.cdc.gov.tw/Category/FPage/TxkBIR9agw_IBRRmvn9TcQ",
    }


@pytest.mark.parametrize(
    ("links", "expected_code"),
    [
        ((REVISION_LINK,), "DISCOVERY_RESOURCE_MISSING"),
        ((MANUAL_LINK,), "DISCOVERY_RESOURCE_MISSING"),
        (
            (MANUAL_LINK, REVISION_LINK, _link("otherToken", MANUAL_LABEL.replace("0826", "0508"))),
            "DISCOVERY_RESOURCE_AMBIGUOUS",
        ),
        (
            (MANUAL_LINK, _link("cBtNn3rYwlBFGthaclYfYg", REVISION_LABEL.replace("0826", "0827"))),
            "DISCOVERY_VERSION_MISMATCH",
        ),
        (
            (MANUAL_LINK.replace('"/File/Get/', '"https://evil.example/File/Get/'), REVISION_LINK),
            "FETCH_HOST_NOT_ALLOWED",
        ),
        (
            (MANUAL_LINK.replace('"/File/Get/', '"/Uploads/'), REVISION_LINK),
            "DISCOVERY_RESOURCE_MISSING",
        ),
    ],
)
def test_discover_rejects_missing_ambiguous_mismatched_or_offsite_attachments(links, expected_code):
    from taiwan_lab_mcp.cdc_manual_source import discover_cdc_manual_resources
    from taiwan_lab_mcp.fetch import FetchError

    with pytest.raises(FetchError) as error:
        discover_cdc_manual_resources(_page(*links), landing_url=LANDING)
    assert error.value.code == expected_code


def test_viewer_resolves_the_uploaded_pdf():
    from taiwan_lab_mcp.cdc_manual_source import resolve_cdc_viewer_pdf

    url = resolve_cdc_viewer_pdf(
        _viewer(MANUAL_LABEL, MANUAL_UUID), viewer_url=MANUAL_VIEWER, attachment_label=MANUAL_LABEL
    )
    assert url == f"https://www.cdc.gov.tw/Uploads/{MANUAL_UUID}.pdf"


@pytest.mark.parametrize(
    ("viewer", "expected_code"),
    [
        (b"<html><body>no document</body></html>", "DISCOVERY_VIEWER_PDF_MISSING"),
        (
            _viewer(MANUAL_LABEL, MANUAL_UUID)
            + f'<embed src="/Uploads/{REVISION_UUID}.pdf">'.encode(),
            "DISCOVERY_VIEWER_PDF_AMBIGUOUS",
        ),
        (
            _viewer(MANUAL_LABEL, MANUAL_UUID, download=REVISION_LABEL),
            "DISCOVERY_ATTACHMENT_MISMATCH",
        ),
        (
            _viewer(MANUAL_LABEL, MANUAL_UUID, host="https://evil.example"),
            "FETCH_HOST_NOT_ALLOWED",
        ),
    ],
)
def test_viewer_rejects_missing_ambiguous_mislabelled_or_offsite_pdfs(viewer, expected_code):
    from taiwan_lab_mcp.cdc_manual_source import resolve_cdc_viewer_pdf
    from taiwan_lab_mcp.fetch import FetchError

    with pytest.raises(FetchError) as error:
        resolve_cdc_viewer_pdf(viewer, viewer_url=MANUAL_VIEWER, attachment_label=MANUAL_LABEL)
    assert error.value.code == expected_code


def test_upstream_sync_keeps_both_pdfs_and_writes_a_validation_report(tmp_path):
    page = _page()
    opener = _Opener(*_responses(page=page))

    report = _sync(tmp_path, opener)

    assert opener.urls == [
        LANDING,
        MANUAL_VIEWER,
        f"https://www.cdc.gov.tw/Uploads/{MANUAL_UUID}.pdf",
        REVISION_VIEWER,
        f"https://www.cdc.gov.tw/Uploads/{REVISION_UUID}.pdf",
    ]
    assert (report["source_id"], report["status"], report["stage"]) == (
        "cdc_specimen_manual",
        "passed",
        "validate",
    )
    assert report["candidate_status"] == "none"
    revision_id = report["raw_revision_id"]
    raw_dir = tmp_path / "raw" / "cdc_specimen_manual" / revision_id
    assert (raw_dir / "artifacts" / "manual.pdf").read_bytes() == _pdf("manual")
    assert (raw_dir / "artifacts" / "revision.pdf").read_bytes() == _pdf("revision")
    assert report["raw_artifact_data_root_relative_paths"] == {
        "manual": f"raw/cdc_specimen_manual/{revision_id}/artifacts/manual.pdf",
        "revision_table": f"raw/cdc_specimen_manual/{revision_id}/artifacts/revision.pdf",
    }
    fetch = json.loads((raw_dir / "fetch.json").read_bytes())
    assert fetch["source_id"] == "cdc_specimen_manual"
    assert fetch["discovery"]["manual_version_raw"] == "1150826"
    assert fetch["discovery"]["landing_sha256"] == hashlib.sha256(page).hexdigest()
    documents = {document["role"]: document for document in fetch["discovery"]["documents"]}
    assert documents["manual"]["pdf_url"] == f"https://www.cdc.gov.tw/Uploads/{MANUAL_UUID}.pdf"
    assert (
        documents["manual"]["viewer_sha256"]
        == hashlib.sha256(_viewer(MANUAL_LABEL, MANUAL_UUID)).hexdigest()
    )
    artifacts = {artifact["role"]: artifact for artifact in fetch["artifacts"]}
    assert artifacts["manual"]["artifact_id"] == "cdc-manual-pdf"
    assert artifacts["revision_table"]["artifact_id"] == "cdc-manual-revision-pdf"
    assert artifacts["manual"]["media_type_verified"] == "application/pdf"
    assert artifacts["revision_table"]["sha256"] == hashlib.sha256(_pdf("revision")).hexdigest()
    assert (tmp_path / report["report_data_root_relative_path"]).is_file()
    assert not (tmp_path / "curated").exists()
    assert not (tmp_path / "manifests").exists()


def test_same_bytes_reuse_the_raw_revision(tmp_path):
    first = _sync(tmp_path, _Opener(*_responses()))
    fetch_path = tmp_path / "raw" / "cdc_specimen_manual" / first["raw_revision_id"] / "fetch.json"
    fetch_before = fetch_path.read_bytes()
    # The page date and the upload names changed; the two PDFs did not.
    second = _sync(
        tmp_path,
        _Opener(
            *_responses(
                page=_page(updated="2026/9/16"),
                manual_uuid="aaaaaaaa-0000-4000-8000-000000000001",
                revision_uuid="aaaaaaaa-0000-4000-8000-000000000002",
            )
        ),
    )

    assert second["raw_revision_id"] == first["raw_revision_id"]
    assert fetch_path.read_bytes() == fetch_before


@pytest.mark.parametrize(
    ("responses", "expected_code"),
    [
        (
            _responses(manual=_pdf_response(b"<html>login</html>", "text/html")),
            "FETCH_CONTENT_TYPE",
        ),
        (_responses(revision=_Response(503)), "FETCH_HTTP_STATUS"),
    ],
)
def test_failed_download_of_either_pdf_keeps_no_raw(tmp_path, responses, expected_code):
    report = _sync(tmp_path, _Opener(*responses))

    assert (report["status"], report["stage"], report["error_code"]) == (
        "failed",
        "fetch",
        expected_code,
    )
    assert report["raw_revision_id"] is None
    assert not (tmp_path / "raw").exists()


@pytest.mark.parametrize(
    ("responses", "expected_code"),
    [
        (_responses(manual=_pdf_response(b"not a pdf at all")), "PDF_NOT_PDF"),
        (_responses(revision=_pdf_response(b"%PDF-1.7\n1 0 obj\n<<>>\n")), "PDF_TRUNCATED"),
    ],
)
def test_invalid_pdf_keeps_raw_and_fails_validation(tmp_path, responses, expected_code):
    report = _sync(tmp_path, _Opener(*responses))

    assert (report["status"], report["stage"], report["error_code"]) == (
        "failed",
        "validate",
        expected_code,
    )
    for relative in report["raw_artifact_data_root_relative_paths"].values():
        assert (tmp_path / relative).is_file()


def test_page_fetch_failure_keeps_no_raw(tmp_path):
    report = _sync(tmp_path, _Opener(_Response(503)))

    assert (report["status"], report["stage"], report["error_code"]) == (
        "failed",
        "discover",
        "FETCH_HTTP_STATUS",
    )
    assert not (tmp_path / "raw").exists()


def test_cli_sync_cdc_manual_requires_the_explicit_upstream_flag(tmp_path, monkeypatch, capsys):
    import taiwan_lab_mcp.cdc_manual_source as cdc_manual_source
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

    monkeypatch.setattr(cdc_manual_source, "run_cdc_manual_upstream_sync", fake)
    arguments = ["sync", "cdc_specimen_manual", "--data-dir", str(tmp_path)]
    assert [main([*arguments, "--upstream", "--json"]) for _ in reports] == [0, 3, 4]
    assert calls == [tmp_path] * 3
    capsys.readouterr()
    with pytest.raises(SystemExit) as error:
        main([*arguments, "--json"])
    assert error.value.code == 2
