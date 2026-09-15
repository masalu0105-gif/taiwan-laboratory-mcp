"""CDC recognized laboratory roster: curated build, AI-delegated official build, MCP queries.

Owner 2026-09-15 delegated CDC reviews to AI (「Ai全程代審 不用特別備注未經人工審核」) and
started the CDC source (「A 開始做疾管署」). Fixtures are synthetic rosters.
"""

import hashlib
import io
import json
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import pytest

import taiwan_lab_mcp.importers.nhi as nhi_importer
from taiwan_lab_mcp.adapters.cdc import CDCAdapter
from taiwan_lab_mcp.canonical import canonical_json_bytes, sha256_bytes
from taiwan_lab_mcp.config import DataContext

REVIEWER = "ai-reviewer:claude-opus-5"
ROLE = "ai_reviewer_delegated_by_owner"
REVIEWED_AT = "2026-09-15T21:30:00+08:00"
SHEET = "1150914名冊"
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
ROWS = [
    (
        "097036",
        "高雄市",
        "合成總醫院",
        "檢驗科",
        "002",
        "傷寒",
        "確認",
        "病原體分離、鑑定(A1)",
        "高雄市合成區1號",
        "(07)000-0001",
        "2028/12/31",
        "2026/09/08",
    ),
    (
        "097036",
        "高雄市",
        "合成總醫院",
        "檢驗科",
        "002",
        "傷寒",
        "確認",
        "血清型別鑑定(B2)",
        "高雄市合成區1號",
        "(07)000-0001",
        "2028/12/31",
        "2026/09/08",
    ),
    (
        "098029",
        "臺北市",
        "合成檢驗所",
        "醫檢部",
        "090",
        "梅毒",
        "篩檢",
        "抗體檢測-非特異性梅毒螺旋體試驗(RPR)(B16)",
        "臺北市合成區2號",
        "(02)0000-0002",
        "2027/06/30",
        "無需能力試驗",
    ),
    (
        "19SC0001",
        "臺南市",
        "合成醫院",
        "檢驗醫學部",
        "19SC",
        "合成疾病",
        "確認",
        "核酸檢測(C1)",
        "臺南市合成區3號",
        "(06)000-0003",
        "2029/01/01",
        "",
    ),
] + [
    (
        f"1000{number:02d}",
        "新北市",
        f"合成診所{number}",
        "檢驗科",
        "0705",
        "C型肝炎",
        "確認",
        "抗體檢測(Anti-HCV)(B24)",
        f"新北市合成路{number}號",
        "(02)1111-0000",
        "2030/01/31",
        "2026/08/01",
    )
    for number in range(1, 9)
]
LANDING = "https://www.cdc.gov.tw/Category/Page/02d-tR1nzB8QuflX-NmM_w"
LABEL = "傳染病認可檢驗機構名冊1150914.ods"


def _ods(rows=ROWS):
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
        f'<office:body><office:spreadsheet><table:table table:name="{SHEET}">'
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


def _page():
    return (
        '<html><body><div class="download"><a href="/File/Get/35jzmDYRqYO_xsXgEqAivA">'
        f"{LABEL}</a></div></body></html>"
    ).encode("utf-8")


@pytest.fixture
def distribution(monkeypatch):
    monkeypatch.setattr(
        nhi_importer, "_application_build_identity", lambda: ("distribution", "d" * 64)
    )


def _offline(data_root, rows=ROWS):
    from taiwan_lab_mcp.importers.cdc_labs import build_cdc_labs_snapshot

    return build_cdc_labs_snapshot(_ods(rows), data_root)


def _adapter(data_root, clock=None):
    return CDCAdapter(DataContext(mode="official_snapshot", data_root=data_root, clock=clock))


def _certificates(result):
    return [item.record.certificate_no for item in result.items]


def test_lab_01_02_official_search_returns_method_rows_with_ods_locators(tmp_path):
    _offline(tmp_path)

    result = _adapter(tmp_path).find_authorized_lab("傷寒")

    assert (result.result_status, result.data_mode, result.sample_only) == (
        "ok",
        "official_snapshot",
        False,
    )
    assert result.total_matches == 2
    assert [item.record.method for item in result.items] == [
        "病原體分離、鑑定(A1)",
        "血清型別鑑定(B2)",
    ]
    first = result.items[0]
    assert first.record.model_dump() == {
        "record_type": "cdc_recognized_lab",
        "certificate_no": "097036",
        "city": "高雄市",
        "institution": "合成總醫院",
        "department": "檢驗科",
        "disease_code": "002",
        "disease_name": "傷寒",
        "purpose": "確認",
        "method": "病原體分離、鑑定(A1)",
        "address": "高雄市合成區1號",
        "phone": "(07)000-0001",
        "end_time": "2028/12/31",
        "latest_annual_pt_review_raw": "2026/09/08",
    }
    evidence = first.evidence[0]
    assert evidence.artifact_id == "cdc-labs-primary-ods"
    assert evidence.locator.model_dump() == {
        "locator_type": "ods_row",
        "sheet_name": SHEET,
        "expanded_row_number": 3,
    }
    assert result.items[1].evidence[0].locator.expanded_row_number == 4
    assert evidence.source_row_sha256 == sha256_bytes(canonical_json_bytes(list(ROWS[0])))
    assert first.safety["does_not_confirm_current_acceptance"] is True
    provenance = result.provenance
    assert (provenance.source_id, provenance.official_version_raw, provenance.coverage_status) == (
        "cdc_recognized_labs",
        "1150914",
        "complete",
    )
    assert provenance.attribution.startswith("衛生福利部疾病管制署")
    assert "非疾管署官方服務，內容以疾管署公告為準。" in result.notes
    assert any("不保證當次收件" in note for note in result.notes)

    alias = _adapter(tmp_path).get_lab_scope("傷寒")
    assert (alias.operation, alias.total_matches) == ("get_lab_scope", 2)


@pytest.mark.parametrize(
    ("query", "city", "expected"),
    [
        ("090", None, ["098029"]),
        ("098029", None, ["098029"]),
        # An exact disease code comes before a certificate number that merely contains it.
        ("002", None, ["097036", "097036", "100002"]),
        ("合成醫院", None, ["19SC0001"]),
        ("合成", "台北市", ["098029"]),
        ("C型肝炎", "新北市", [f"1000{number:02d}" for number in range(1, 9)]),
    ],
)
def test_find_authorized_lab_matching_order_and_city_filter(tmp_path, query, city, expected):
    _offline(tmp_path)
    adapter = _adapter(tmp_path)
    certificates, offset = [], 0
    while True:
        result = adapter.find_authorized_lab(query, city, 5, offset)
        assert result.total_matches == len(expected)
        certificates += _certificates(result)
        if not result.truncated:
            break
        offset += 5
    assert certificates == expected


def test_find_authorized_lab_pages_through_every_match(tmp_path):
    # Owner 2026-09-15: 「A 加翻頁」, then 「一次 20 筆」 because one hospital fills several rows.
    _offline(tmp_path)
    adapter = _adapter(tmp_path)

    default = adapter.find_authorized_lab("C型肝炎", "新北市")
    assert (default.total_matches, default.returned_count, default.limit) == (8, 8, 20)
    assert default.truncated is False
    assert default.query == {"query": "C型肝炎", "city": "新北市", "limit": 20, "offset": 0}
    first = adapter.find_authorized_lab("C型肝炎", "新北市", 5, 0)
    assert (first.total_matches, first.returned_count, first.limit, first.offset) == (8, 5, 5, 0)
    assert first.truncated is True
    last = adapter.find_authorized_lab("C型肝炎", "新北市", 5, 5)
    assert (last.returned_count, last.offset, last.truncated) == (3, 5, False)
    assert _certificates(first) + _certificates(last) == [
        f"1000{number:02d}" for number in range(1, 9)
    ]
    beyond = adapter.find_authorized_lab("C型肝炎", "新北市", 5, 8)
    assert (beyond.total_matches, beyond.items) == (8, [])

    alias = adapter.get_lab_scope("C型肝炎")
    assert (alias.operation, alias.query) == ("get_lab_scope", {"query": "C型肝炎"})
    assert (alias.total_matches, alias.returned_count, alias.truncated) == (8, 8, False)
    assert adapter.find_authorized_lab("C型肝炎", "新北市", 20, 0).returned_count == 8


@pytest.mark.parametrize(
    ("limit", "offset"), [(0, 0), (21, 0), ("5", 0), (True, 0), (5, -1), (5, "1"), (5, None)]
)
def test_find_authorized_lab_rejects_invalid_paging(tmp_path, limit, offset):
    _offline(tmp_path)
    result = _adapter(tmp_path).find_authorized_lab("傷寒", None, limit, offset)
    assert (result.result_status, result.items) == ("invalid_request", [])
    assert any("limit 為 1–20" in note for note in result.notes)


@pytest.mark.parametrize(
    ("query", "city", "expected"),
    [
        ("新北市 C型肝炎", None, [f"1000{number:02d}" for number in range(1, 9)]),
        ("C型肝炎 新北", None, [f"1000{number:02d}" for number in range(1, 9)]),
        ("台北 合成", None, ["098029"]),
        ("臺北市　合成", None, ["098029"]),
        ("097036 血清", None, ["097036"]),
        ("高雄 傷寒 血清", None, ["097036"]),
        ("合成 醫院", None, ["097036", "097036", "19SC0001"]),
        ("台北 合成", "新北市", []),
        ("台南 梅毒", None, []),
    ],
)
def test_words_separated_by_spaces_each_must_match(tmp_path, query, city, expected):
    # Owner 2026-09-15 chose A: 「台南 傷寒」 used to find nothing although 40 rows exist.
    # A county or city word filters by 縣市別; every other word must match a searched column.
    _offline(tmp_path)
    result = _adapter(tmp_path).find_authorized_lab(query, city)
    assert _certificates(result) == expected
    assert result.result_status == ("ok" if expected else "not_found")


def test_search_without_a_match_is_not_found_within_the_snapshot(tmp_path):
    _offline(tmp_path)
    result = _adapter(tmp_path).find_authorized_lab("狂犬病")
    assert (result.result_status, result.items) == ("not_found", [])


def test_lab_04_pt_review_values_round_trip_through_mcp(tmp_path):
    _offline(tmp_path)
    adapter = _adapter(tmp_path)
    values = {
        query: adapter.find_authorized_lab(query).items[0].record.latest_annual_pt_review_raw
        for query in ("097036", "098029", "19SC0001")
    }
    assert values == {"097036": "2026/09/08", "098029": "無需能力試驗", "19SC0001": ""}


def test_official_mode_without_a_roster_is_unavailable_without_sample_fallback(tmp_path):
    from taiwan_lab_mcp.stores import read_source_status

    adapter = _adapter(tmp_path)
    labs = adapter.find_authorized_lab("傷寒")
    assert (labs.result_status, labs.availability_reason_code, labs.items) == (
        "data_unavailable",
        "no_serving_snapshot",
        [],
    )
    assert adapter.search_disease("麻疹").result_status == "data_unavailable"
    assert read_source_status(tmp_path, "cdc_recognized_labs").availability == "data_unavailable"


def test_data_status_reports_the_served_roster_and_turns_overdue_after_two_days(tmp_path):
    from taiwan_lab_mcp.stores import read_source_status

    built = _offline(tmp_path)
    descriptor = json.loads(
        (tmp_path / "manifests" / "current" / "cdc_authorized_labs.json").read_bytes()
    )
    checked = datetime.fromisoformat(descriptor["last_successful_check_at"].replace("Z", "+00:00"))

    status = read_source_status(tmp_path, "cdc_recognized_labs", clock=lambda: checked)
    assert (status.availability, status.serving_curated_build_id, status.coverage_status) == (
        "available",
        built["snapshot_id"],
        "complete",
    )
    assert (status.stale, status.freshness_policy_version) == (False, "cdc-labs-v1")
    later = checked + timedelta(days=2, seconds=1)
    overdue = read_source_status(tmp_path, "cdc_recognized_labs", clock=lambda: later)
    assert (overdue.stale, overdue.stale_reason_codes) == (True, ["upstream_check_overdue"])


def test_tampered_roster_database_is_not_served(tmp_path):
    from taiwan_lab_mcp.stores import read_source_status

    built = _offline(tmp_path)
    db_path = tmp_path / "curated" / "cdc_authorized_labs" / built["snapshot_id"] / "data.sqlite3"
    payload = bytearray(db_path.read_bytes())
    payload[-1] ^= 0xFF
    db_path.write_bytes(bytes(payload))

    assert read_source_status(tmp_path, "cdc_recognized_labs").availability_reason_code == (
        "serving_integrity_failure"
    )
    assert _adapter(tmp_path).find_authorized_lab("傷寒").result_status == "data_unavailable"


def _fetch(data_root, payload):
    from taiwan_lab_mcp.cdc_source import run_cdc_labs_upstream_sync

    headers = {
        "Content-Type": "application/octet-stream",
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(LABEL)}",
    }
    report = run_cdc_labs_upstream_sync(
        data_root,
        opener=_Opener(
            _Response(200, _page(), {"Content-Type": "text/html; charset=utf-8"}),
            _Response(200, payload, headers),
        ),
    )
    assert report["status"] == "passed"
    return report["raw_revision_id"], report["raw_artifact_data_root_relative_path"]


def _cases(payload, artifact_relative, count=10):
    from taiwan_lab_mcp.importers.cdc_labs import active_cdc_labs_transform

    return [
        {
            "golden_case_schema_version": 1,
            "case_id": f"LAB-G-{number:03d}",
            "source_id": "cdc_authorized_labs",
            "acceptance_id": "LAB-02",
            "source_title": "傳染病認可檢驗機構名冊",
            "official_landing_url": LANDING,
            "official_version_or_modified_at": "1150914",
            "official_source": True,
            "artifact_id": "cdc-labs-primary-ods",
            "raw_artifact_sha256": hashlib.sha256(payload).hexdigest(),
            "evidence_data_root_relative_path": artifact_relative,
            "fixture_file": None,
            "fixture_sha256": None,
            "transform": active_cdc_labs_transform(),
            "input": {"certificate_no": row[0]},
            "source_locator": {
                "locator_type": "ods_row",
                "sheet_name": SHEET,
                "expanded_row_number": number,
            },
            "source_row_sha256": sha256_bytes(canonical_json_bytes(list(row))),
            "expected_status": "ok",
            "expected_fields": {"certificate_no": row[0], "method": row[7], "end_time": row[10]},
            "expected_warnings": [],
            "reviewer_id": REVIEWER,
            "reviewer_role": ROLE,
            "identity_assurance": "local_asserted",
            "reviewed_at": REVIEWED_AT,
            "review_status": "approved",
        }
        for number, row in enumerate(ROWS[:count], start=3)
    ]


def _reviews(**changes):
    from taiwan_lab_mcp.importers.cdc_labs import CDC_LABS_SERVING_GATES

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
        for gate_id in CDC_LABS_SERVING_GATES
    ]


def _official(data_root, **overrides):
    from taiwan_lab_mcp.importers.cdc_labs import build_official_cdc_labs_snapshot

    payload = _ods()
    raw_revision_id, artifact_relative = _fetch(data_root, payload)
    arguments = {
        "raw_revision_id": raw_revision_id,
        "approved_golden_cases": _cases(payload, artifact_relative),
        "owner_reviews": _reviews(),
        "publisher_actor_id": "unit-test-publisher",
    }
    arguments.update({key: value(payload, artifact_relative) for key, value in overrides.items()})
    return build_official_cdc_labs_snapshot(data_root, **arguments)


def test_official_build_uses_the_delegated_ai_review(tmp_path, distribution):
    built = _official(tmp_path)

    assert (built["rows"], built["generation"]) == (12, 1)
    build_dir = tmp_path / "curated" / "cdc_authorized_labs" / built["snapshot_id"]
    review = json.loads((build_dir / "audit" / "reviews" / "ODS-R1-CONTENT.json").read_bytes())
    assert (review["reviewer_id"], review["reviewer_role"]) == (REVIEWER, ROLE)
    # Version 2 adds the download bundle to the reviewed scope (OD-19).
    assert (review["protocol_id"], review["protocol_version"]) == ("cdc-labs-r1-ai-review", "2")
    certificate = json.loads((build_dir / "audit" / "golden-qualification.json").read_bytes())
    assert certificate["official_qualification_status"] == "approved"
    assert len(certificate["approved_distinct_case_ids"]) == 10
    result = _adapter(tmp_path).find_authorized_lab("傷寒")
    assert (result.result_status, result.provenance.curated_build_id) == (
        "ok",
        built["snapshot_id"],
    )


def _nine_cases(payload, artifact_relative):
    return _cases(payload, artifact_relative, count=9)


def _other_reviewer(payload, artifact_relative):
    return _reviews(reviewer_id="someone-else")


def _major_finding(payload, artifact_relative):
    return _reviews(finding_counts={"critical": 0, "major": 1, "minor": 0})


def _wrong_expected_value(payload, artifact_relative):
    cases = _cases(payload, artifact_relative)
    cases[0]["expected_fields"]["end_time"] = "2099/12/31"
    return cases


@pytest.mark.parametrize(
    ("argument", "factory", "expected_code"),
    [
        ("approved_golden_cases", _nine_cases, "GOLDEN_CASES_INSUFFICIENT"),
        ("approved_golden_cases", _wrong_expected_value, "GOLDEN_CASE_FAILED"),
        ("owner_reviews", _other_reviewer, "OWNER_REVIEW_REVIEWER_MISMATCH"),
        ("owner_reviews", _major_finding, "OWNER_REVIEW_REJECTED"),
    ],
)
def test_official_build_rejects_insufficient_evidence_before_writing(
    tmp_path, distribution, argument, factory, expected_code
):
    from taiwan_lab_mcp.importers.cdc_ods import CdcOdsImportError

    with pytest.raises(CdcOdsImportError) as error:
        _official(tmp_path, **{argument: factory})
    assert error.value.code == expected_code
    assert not (tmp_path / "curated").exists()
    assert not (tmp_path / "manifests").exists()


def test_official_build_requires_an_installed_distribution(tmp_path, monkeypatch):
    from taiwan_lab_mcp.importers.cdc_ods import CdcOdsImportError

    monkeypatch.setattr(
        nhi_importer, "_application_build_identity", lambda: ("development", "d" * 64)
    )
    with pytest.raises(CdcOdsImportError) as error:
        _official(tmp_path)
    assert error.value.code == "APPLICATION_BUILD_IDENTITY_MISSING"
    assert not Path(tmp_path / "curated").exists()
