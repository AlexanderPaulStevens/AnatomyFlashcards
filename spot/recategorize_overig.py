"""
Re-assign region for plates with weak titles (Pagina / Overig leftovers)
using label keywords + silhouette red-box detection. Updates data.json + data.js.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from region_infer import refine_region

ROOT = Path(__file__).resolve().parent
DATA_JSON = ROOT / "data.json"
DATA_JS = ROOT / "data.js"

WEAK_TITLES = {
    "pagina",
    "spieren",
    "eerste laag",
    "tweede laag",
    "overige spieren",
    "oppervlakkige structuren",
}


def main() -> None:
    data = json.loads(DATA_JSON.read_text(encoding="utf-8"))
    changes = []

    for plate in data["plates"]:
        answers = [L["answer"] for L in plate.get("labels", [])]
        reveal = ROOT / plate["imageReveal"]
        title = plate.get("topic", "")
        old = plate["region"]

        if old == "Overig" or title.lower().strip() in WEAK_TITLES:
            new_region = refine_region("Pagina", answers, reveal)
        else:
            new_region = refine_region(title, answers, reveal)

        if new_region != old:
            changes.append((plate["id"], old, new_region, answers[:4]))
            plate["region"] = new_region

    plate_region = {p["id"]: p["region"] for p in data["plates"]}
    for q in data["questions"]:
        pid = q.get("plateId")
        if pid in plate_region:
            q["region"] = plate_region[pid]

    data["regions"] = sorted({p["region"] for p in data["plates"]})
    topics = sorted(
        {(p["topicId"], p["topic"], p["region"]) for p in data["plates"]},
        key=lambda t: t[1],
    )
    data["topics"] = [{"id": t[0], "label": t[1], "region": t[2]} for t in topics]

    DATA_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    DATA_JS.write_text(
        "window.SPOT_DATA = " + json.dumps(data, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )

    print(f"Updated {len(changes)} plates:")
    for pid, old, new, sample in changes:
        print(f"  {pid}: {old} → {new}  ({', '.join(sample)})")
    print()
    print("Region counts:", Counter(p["region"] for p in data["plates"]).most_common())
    print(f"Wrote {DATA_JSON.name} and {DATA_JS.name}")


if __name__ == "__main__":
    main()
