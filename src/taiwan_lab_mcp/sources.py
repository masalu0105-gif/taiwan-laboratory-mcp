from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from importlib.resources import files

from .models import ArtifactReference, Provenance

OFFICIAL_SOURCES = {
    "cdc_specimen": "https://www.cdc.gov.tw/Category/Page/WV_GRwCIYrWQsEVa8ctTWg",
    "cdc_labs": "https://www.cdc.gov.tw/Category/Page/02d-tR1nzB8QuflX-NmM_w",
    "tfda_devices": "https://data.gov.tw/dataset/9576",
    "nhi_fee": "https://data.gov.tw/dataset/174450",
}

SOURCE_IDS = ("cdc_manual", "cdc_recognized_labs", "nhi_fee", "tfda_device")

_SOURCE_INFO = {
    "cdc_manual": ("cdc_specimen", "cdc_specimen.sample.json", "衛生福利部疾病管制署"),
    "cdc_recognized_labs": ("cdc_labs", "cdc_labs.sample.json", "衛生福利部疾病管制署"),
    "nhi_fee": ("nhi_fee", "nhi_fee.sample.json", "衛生福利部中央健康保險署"),
    "tfda_device": ("tfda_devices", "tfda_devices.sample.json", "衛生福利部食品藥物管理署"),
}


def sample_provenance(name: str) -> Provenance:
    source_id, filename, provider = next(
        (source_id, filename, provider)
        for source_id, (legacy_name, filename, provider) in _SOURCE_INFO.items()
        if legacy_name == name
    )
    landing_url = OFFICIAL_SOURCES[name]
    resource = files("taiwan_lab_mcp").joinpath("data", filename)
    digest = hashlib.sha256(resource.read_bytes()).hexdigest()
    return Provenance(
        source_id=source_id,
        source_name=f"Taiwan Laboratory MCP 合成示範資料：{name}",
        provider=provider,
        landing_url=landing_url,
        resource_url=landing_url,
        snapshot_id=None,
        curated_build_id=None,
        official_version_raw=None,
        official_content_date=None,
        retrieved_at=datetime(2026, 9, 13, tzinfo=timezone.utc),
        artifacts=[
            ArtifactReference(
                artifact_id=filename,
                role="synthetic_fixture",
                storage_scope="package_resource",
                data_root_relative_path=None,
                official_url=landing_url,
                sha256=digest,
                local_artifact_available=True,
            )
        ],
        parser_version="sample-fixture-v1",
        schema_version="sample-fixture-v1",
        rule_bundle_version="sample-fixture-v1",
        license_name="MIT",
        license_url="https://github.com/masalu0105-gif/taiwan-laboratory-mcp/blob/main/LICENSE",
        attribution="合成示範資料；不代表官方資料內容。",
        coverage_status="review_incomplete" if source_id == "nhi_fee" else "unknown",
        stale=False,
        stale_reason_codes=[],
        last_check_at=None,
        serving_review_status="not_applicable",
    )


CDC_SPECIMEN = sample_provenance("cdc_specimen")
CDC_LABS = sample_provenance("cdc_labs")
TFDA_DEVICE = sample_provenance("tfda_devices")
NHI_FEE = sample_provenance("nhi_fee")
