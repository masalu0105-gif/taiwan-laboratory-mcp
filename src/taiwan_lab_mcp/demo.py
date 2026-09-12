from __future__ import annotations

from .adapters.cdc import CDCAdapter
from .adapters.nhi import NHIAdapter
from .adapters.tfda import TFDAAdapter


def measles_demo() -> dict:
    cdc = CDCAdapter()
    specimen = cdc.get_specimen_requirement("measles").model_dump(mode="json")
    labs = cdc.find_authorized_lab("麻疹").model_dump(mode="json")
    return {
        "question": "我要送 Measles IgM，請告訴我要採什麼檢體、怎麼保存與運送、有哪些認可實驗室，並附官方來源",
        "specimen": specimen,
        "authorized_labs": labs,
        "warning": "Bundled data are demonstration fixtures. Production answers must be generated after syncing and validating the latest official source files.",
    }


if __name__ == "__main__":
    import json

    print(
        json.dumps(
            {
                "sample_only": True,
                "cdc": measles_demo(),
                "nhi": NHIAdapter().search_lab_code("HbA1c").model_dump(mode="json"),
                "tfda": TFDAAdapter().search_ivd("HbA1c").model_dump(mode="json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
