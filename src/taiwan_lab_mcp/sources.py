from __future__ import annotations

from .models import Provenance

OFFICIAL_SOURCES = {
    "cdc_specimen": "https://www.cdc.gov.tw/Category/Page/WV_GRwCIYrWQsEVa8ctTWg",
    "cdc_labs": "https://www.cdc.gov.tw/Category/Page/02d-tR1nzB8QuflX-NmM_w",
    "tfda_devices": "https://data.gov.tw/dataset/9576",
    "nhi_fee": "https://data.gov.tw/dataset/174450",
}


def sample_provenance(name: str) -> Provenance:
    return Provenance(
        source_name=f"Taiwan Laboratory MCP 合成示範資料：{name}",
        source_url=(
            "https://github.com/masalu0105-gif/taiwan-laboratory-mcp/"
            f"blob/main/src/taiwan_lab_mcp/data/{name}.sample.json"
        ),
        version="sample-v0.1",
        updated_at=None,
        updated_at_note="合成 fixture，沒有官方資料更新日期；尚未匯入正式資料。",
        method="synthetic",
        locator=f"{name}.sample.json",
        license="MIT",
        license_url="https://github.com/masalu0105-gif/taiwan-laboratory-mcp/blob/main/LICENSE",
    )


CDC_SPECIMEN = sample_provenance("cdc_specimen")
CDC_LABS = sample_provenance("cdc_labs")
TFDA_DEVICE = sample_provenance("tfda_devices")
NHI_FEE = sample_provenance("nhi_fee")
