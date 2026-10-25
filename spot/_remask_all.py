"""Remask every plate via full OCR cover + bump assetVersion."""
from __future__ import annotations

import json
import time
from pathlib import Path

from rapidocr_onnxruntime import RapidOCR

from build_data import remask_plate

ROOT = Path(__file__).resolve().parent


def main() -> None:
    data = json.loads((ROOT / "data.json").read_text(encoding="utf-8"))
    print("Loading OCR…")
    ocr = RapidOCR()
    plates = data["plates"]
    for i, plate in enumerate(plates, 1):
        remask_plate(plate, ocr=ocr)
        print(f"[{i}/{len(plates)}] {plate['id']}")

    ver = time.strftime("%Y%m%d%H%M")
    data["assetVersion"] = ver
    (ROOT / "data.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ROOT / "data.js").write_text(
        "window.SPOT_DATA = " + json.dumps(data, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )
    print("assetVersion", ver)


if __name__ == "__main__":
    main()
