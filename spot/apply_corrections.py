"""
Apply hand-checked label corrections to spot/data.json → rewrite data.js + remask assets.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from PIL import Image, ImageDraw

from corrections import DROP, PLATE_ANSWERS, TEXT_FIX

ROOT = Path(__file__).resolve().parent
DATA_JSON = ROOT / "data.json"
DATA_JS = ROOT / "data.js"
ASSETS = ROOT / "assets"

# Explicit OCR-index groups per plate when fragment count ≠ corrected count.
# Each inner list = OCR label indices to merge into one answer (same order as PLATE_ANSWERS).
PLATE_GROUPS: dict[str, list[list[int]]] = {
    "p03_i0": [[0], [1, 2], [3, 4]],  # quadratus(+plantaris missing), FHL pees, FDL pezen
    "p04_i0": [[0, 1], [2]],  # abductor digiti minimi; flexor digitorum brevis
    "p07_i1": [[0, 1], [0, 2]],  # digitalis + proprius V / I
    "p16_i0": [[0], [1], [2]],  # add communis onto peroneus via answers only
    "p19_i0": [[0], [1], [2]],
    "p21_i1": [[0], [1, 2], [3], [4]],  # tibialis, extensor+hallucis, peroneus, digitorum
    "p22_i0": [[0, 1], [2], [3], [4]],
    "p23_i0": [[0], [1, 2], [3], [4], [5]],
    "p24_i0": [[0], [1], [2], [3], [4, 5]],
    "p27_i0": [[0], [1, 2], [1, 3]],
    "p32_i0": [[0], [1, 2], [3], [4], [5], [6]],
    "p32_i1": [[0, 1], [2, 3]],
    "p34_i0": [[0, 1], [2], [3], [4]],
    "p39_i0": [[0], [1], [2], [3], [4, 5]],
    "p43_i0": [[0], [1], [2, 3]],
    "p46_i0": [[0, 1], [2, 3], [4], [5], [7], [8]],
    "p52_i1": [[0], [1], [2], [3]],
    "p71_i0": [[0], [1], [2], [3, 4]],
}


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def merge_labels(labels: list[dict], indices: list[int]) -> dict:
    picked = [labels[i] for i in indices if 0 <= i < len(labels)]
    if not picked:
        raise ValueError(f"empty merge {indices}")
    # bbox union in normalized space → rebuild center
    # labels store x,y as centers and w,h
    xs0, ys0, xs1, ys1 = [], [], [], []
    for L in picked:
        xs0.append(L["x"] - L["w"] / 2)
        ys0.append(L["y"] - L["h"] / 2)
        xs1.append(L["x"] + L["w"] / 2)
        ys1.append(L["y"] + L["h"] / 2)
    x0, y0, x1, y1 = min(xs0), min(ys0), max(xs1), max(ys1)
    return {
        "answer": picked[0]["answer"],
        "x": round((x0 + x1) / 2, 4),
        "y": round((y0 + y1) / 2, 4),
        "w": round(x1 - x0, 4),
        "h": round(y1 - y0, 4),
        "_raw_indices": indices,
    }


def remask(plate: dict) -> None:
    """Rebuild masked image covering all label boxes."""
    reveal = ROOT / plate["imageReveal"]
    if not reveal.exists():
        return
    img = Image.open(reveal).convert("RGB")
    w, h = img.size
    draw = ImageDraw.Draw(img)
    for lab in plate["labels"]:
        x0 = (lab["x"] - lab["w"] / 2) * w - 4
        y0 = (lab["y"] - lab["h"] / 2) * h - 4
        x1 = (lab["x"] + lab["w"] / 2) * w + 4
        y1 = (lab["y"] + lab["h"] / 2) * h + 4
        draw.rectangle([x0, y0, x1, y1], fill=(8, 8, 8))
    out = ROOT / plate["image"]
    img.save(out, quality=82, optimize=True)


def fix_plate(plate: dict) -> dict:
    pid = plate["id"]
    labels = plate["labels"]

    # 1) text fix + drop
    cleaned = []
    for L in labels:
        ans = TEXT_FIX.get(L["answer"], L["answer"])
        if ans in DROP or L["answer"] in DROP:
            continue
        cleaned.append({**L, "answer": ans})

    corrected = PLATE_ANSWERS.get(pid)

    if corrected is None and pid not in PLATE_ANSWERS:
        # only text fixes
        plate["labels"] = cleaned
        return plate

    if corrected is None:
        plate["labels"] = cleaned
        return plate

    groups = PLATE_GROUPS.get(pid)

    if groups and len(groups) == len(corrected):
        # merge from ORIGINAL labels (before drop) so indices match OCR dump
        new_labels = []
        for group, answer in zip(groups, corrected):
            try:
                merged = merge_labels(labels, group)
            except ValueError:
                continue
            merged["answer"] = answer
            merged.pop("_raw_indices", None)
            new_labels.append(merged)
        plate["labels"] = new_labels
        return plate

    if len(cleaned) == len(corrected):
        for L, ans in zip(cleaned, corrected):
            L["answer"] = ans
        plate["labels"] = cleaned
        return plate

    if len(labels) == len(corrected):
        new_labels = []
        for L, ans in zip(labels, corrected):
            new_labels.append({**L, "answer": ans})
        plate["labels"] = new_labels
        return plate

    # Fallback: take min length, map in order from cleaned
    n = min(len(cleaned), len(corrected))
    new_labels = []
    for i in range(n):
        new_labels.append({**cleaned[i], "answer": corrected[i]})
    plate["labels"] = new_labels
    print(f"  warn {pid}: OCR={len(labels)} cleaned={len(cleaned)} corrected={len(corrected)} → kept {n}")
    return plate


def rebuild_questions(plates: list[dict], pool: list[str]) -> list[dict]:
    questions = []
    for plate in plates:
        answers_here = [L["answer"] for L in plate["labels"]]
        for idx, lab in enumerate(plate["labels"]):
            distractors = [a for a in answers_here if a != lab["answer"]]
            for a in pool:
                if len(distractors) >= 8:
                    break
                if a != lab["answer"] and a not in distractors:
                    distractors.append(a)
            qid = hashlib.md5(f"{plate['id']}:{lab['answer']}:{idx}".encode()).hexdigest()[:10]
            questions.append(
                {
                    "id": qid,
                    "plateId": plate["id"],
                    "page": plate["page"],
                    "topic": plate["topic"],
                    "topicId": plate["topicId"],
                    "region": plate["region"],
                    "image": plate["image"],
                    "imageReveal": plate["imageReveal"],
                    "answer": lab["answer"],
                    "x": lab["x"],
                    "y": lab["y"],
                    "pinW": lab["w"],
                    "pinH": lab["h"],
                    "siblings": answers_here,
                    "distractors": distractors[:12],
                }
            )
    return questions


def main():
    data = json.loads(DATA_JSON.read_text(encoding="utf-8"))
    plates = []
    for plate in data["plates"]:
        before = [L["answer"] for L in plate["labels"]]
        plate = fix_plate(plate)
        after = [L["answer"] for L in plate["labels"]]
        if before != after:
            print(f"{plate['id']}:")
            print(f"  was: {before}")
            print(f"  now: {after}")
        remask(plate)
        plates.append(plate)

    all_answers = sorted({L["answer"] for p in plates for L in p["labels"]}, key=str.lower)
    questions = rebuild_questions(plates, all_answers)
    regions = sorted({p["region"] for p in plates})
    topics = sorted({(p["topicId"], p["topic"], p["region"]) for p in plates}, key=lambda t: t[1])

    payload = {
        **{k: v for k, v in data.items() if k not in ("plates", "questions", "answerPool", "regions", "topics", "plateCount", "questionCount")},
        "plateCount": len(plates),
        "questionCount": len(questions),
        "regions": regions,
        "topics": [{"id": t[0], "label": t[1], "region": t[2]} for t in topics],
        "plates": plates,
        "questions": questions,
        "answerPool": all_answers,
        "correctionsApplied": True,
    }

    DATA_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    DATA_JS.write_text(
        "window.SPOT_DATA = " + json.dumps(payload, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )
    print(f"\nDone: {len(plates)} plates, {len(questions)} questions, {len(all_answers)} answers")


if __name__ == "__main__":
    main()
