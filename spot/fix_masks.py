"""
Rebuild label bounding boxes from full-plate OCR (union of all fragments)
and remask assets so multi-line labels don't leak.

Usage:
  python fix_masks.py              # all plates
  python fix_masks.py p03_i0 p07_i1 …
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from PIL import Image, ImageDraw
from rapidocr_onnxruntime import RapidOCR

from corrections import PLATE_ANSWERS
from verify_anatomy import OCR_ALIASES, rebuild_questions, remask

ROOT = Path(__file__).resolve().parent
DATA_JSON = ROOT / "data.json"
DATA_JS = ROOT / "data.js"
RAW = ROOT / "raw"
ASSETS = ROOT / "assets"

# Extra pad (fraction of image) so tall glyphs / slight OCR miss don't leak
PAD_X = 0.012
PAD_Y = 0.010
MIN_H = 0.028  # never thinner than ~2 text lines on typical plates


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z]{3,}", norm(s)))


def box_aabb(box):
    xs = [p[0] for p in box]
    ys = [p[1] for p in box]
    return min(xs), min(ys), max(xs), max(ys)


def ocr_items(ocr: RapidOCR, path: Path) -> list[dict]:
    result, _ = ocr(str(path))
    items = []
    for line in result or []:
        box, text, conf = line
        try:
            conf_f = float(conf)
        except Exception:
            conf_f = 0.0
        x0, y0, x1, y1 = box_aabb(box)
        items.append(
            {
                "text": str(text),
                "n": norm(str(text)),
                "tok": tokens(str(text)),
                "conf": conf_f,
                "x0": x0,
                "y0": y0,
                "x1": x1,
                "y1": y1,
                "cx": (x0 + x1) / 2,
                "cy": (y0 + y1) / 2,
            }
        )
    return items


def score_fragment(ans: str, it: dict) -> float:
    na = norm(ans)
    nt = it["n"]
    if not nt or len(nt) < 2:
        return 0.0
    # skip watermarks
    if "roosen" in nt or "jorg" in nt:
        return 0.0
    if ")" in it["text"] and ")" not in ans:
        return 0.0

    ta, tt = tokens(ans), it["tok"]
    if not ta:
        return 0.0

    ov = len(ta & tt)
    score = 0.0
    if na in nt or nt in na:
        score += 8.0
    score += ov * 3.0
    # aliases
    for al in OCR_ALIASES.get(ans.lower(), ()):
        nal = norm(al)
        if nal and (nal in nt or nt in nal):
            score += 6.0
    # distinctive endings
    for end in ("longus", "longum", "brevis", "breve", "medialis", "lateralis",
                "posterior", "anterior", "communis", "plantaris", "proprius",
                "superficialis", "intermedius", "parva", "magna", "digitorum",
                "hallucis", "femoris", "capitis", "cervicis"):
        if end in na and end in nt:
            score += 2.0
        if end in na and end not in nt and end[:5] in nt:
            score += 1.0
    # fragment is mostly stopword-ish alone
    if ov == 0 and score < 6:
        return 0.0
    return score + it["conf"] * 0.5


def cluster_for_answer(ans: str, items: list[dict], w: int, h: int) -> list[dict] | None:
    """Pick OCR fragments that belong to this answer and return their union group."""
    scored = []
    for i, it in enumerate(items):
        s = score_fragment(ans, it)
        if s >= 3.0:
            scored.append((s, i, it))
    if not scored:
        return None
    scored.sort(reverse=True, key=lambda t: t[0])

    # Seed with best fragment; grow with nearby fragments that also score
    seed = scored[0][2]
    group = [seed]
    used = {scored[0][1]}
    changed = True
    while changed:
        changed = False
        gx0 = min(g["x0"] for g in group)
        gy0 = min(g["y0"] for g in group)
        gx1 = max(g["x1"] for g in group)
        gy1 = max(g["y1"] for g in group)
        gcx = (gx0 + gx1) / 2
        gcy = (gy0 + gy1) / 2
        for s, i, it in scored:
            if i in used:
                continue
            # near the growing cluster (stacked lines or same label block)
            close_y = abs(it["cy"] - gcy) < h * 0.12 or (
                it["y0"] <= gy1 + h * 0.04 and it["y1"] >= gy0 - h * 0.04
            )
            close_x = abs(it["cx"] - gcx) < w * 0.22 or (
                it["x0"] <= gx1 + w * 0.08 and it["x1"] >= gx0 - w * 0.08
            )
            if not (close_y and close_x):
                continue
            # don't absorb a competing antonym sibling fragment
            na = norm(ans)
            for a, b in (
                ("lateralis", "medialis"),
                ("longus", "brevis"),
                ("major", "minor"),
                ("anterior", "posterior"),
            ):
                if a in na and b in it["n"] and a not in it["n"]:
                    break
                if b in na and a in it["n"] and b not in it["n"]:
                    break
            else:
                # also require some token overlap OR it's a glued prefix of same label
                if len(tokens(ans) & it["tok"]) == 0 and score_fragment(ans, it) < 5:
                    continue
                group.append(it)
                used.add(i)
                changed = True
    return group


def union_label(ans: str, group: list[dict], w: int, h: int) -> dict:
    x0 = min(g["x0"] for g in group)
    y0 = min(g["y0"] for g in group)
    x1 = max(g["x1"] for g in group)
    y1 = max(g["y1"] for g in group)
    # pad in pixels then clamp
    px, py = PAD_X * w, PAD_Y * h
    x0 = max(0, x0 - px)
    y0 = max(0, y0 - py)
    x1 = min(w, x1 + px)
    y1 = min(h, y1 + py)
    bw = (x1 - x0) / w
    bh = (y1 - y0) / h
    if bh < MIN_H:
        # expand vertically around center to cover a second line
        cy = (y0 + y1) / 2
        half = (MIN_H * h) / 2
        y0 = max(0, cy - half)
        y1 = min(h, cy + half)
        bh = (y1 - y0) / h
    return {
        "answer": ans,
        "x": round(((x0 + x1) / 2) / w, 4),
        "y": round(((y0 + y1) / 2) / h, 4),
        "w": round(bw, 4),
        "h": round(bh, 4),
    }


def expand_existing(lab: dict, items: list[dict], w: int, h: int) -> dict:
    """Grow an existing label box by absorbing nearby OCR that matches its answer."""
    group = cluster_for_answer(lab["answer"], items, w, h)
    if not group:
        # keep old box but enforce min height + pad
        x, y, bw, bh = lab["x"], lab["y"], lab["w"], lab["h"]
        bh = max(bh, MIN_H)
        bw = bw + 2 * PAD_X
        bh = bh + 2 * PAD_Y
        return {**lab, "w": round(min(bw, 0.95), 4), "h": round(min(bh, 0.4), 4)}
    return union_label(lab["answer"], group, w, h)


def fix_plate(plate: dict, ocr: RapidOCR, items_cache: dict) -> tuple[dict, bool]:
    pid = plate["id"]
    reveal = ROOT / plate["imageReveal"]
    raw = RAW / f"{pid}.jpg"
    src = raw if raw.exists() else reveal
    if not src.exists():
        return plate, False

    if pid not in items_cache:
        items_cache[pid] = ocr_items(ocr, src)
    items = items_cache[pid]
    img = Image.open(src)
    w, h = img.size

    expected = PLATE_ANSWERS.get(pid)
    new_labels = []
    changed = False

    if expected:
        used_centers = []
        for ans in expected:
            group = cluster_for_answer(ans, items, w, h)
            if not group:
                # fall back to previous label with same answer if any
                prev = next((L for L in plate["labels"] if norm(L["answer"]) == norm(ans)), None)
                if prev:
                    lab = expand_existing(prev, items, w, h)
                    new_labels.append(lab)
                continue
            lab = union_label(ans, group, w, h)
            # avoid two answers claiming nearly the same box
            clash = False
            for ux, uy in used_centers:
                if abs(ux - lab["x"]) < 0.04 and abs(uy - lab["y"]) < 0.04:
                    clash = True
                    break
            if clash:
                continue
            used_centers.append((lab["x"], lab["y"]))
            new_labels.append(lab)
    else:
        for L in plate["labels"]:
            new_labels.append(expand_existing(L, items, w, h))

    if not new_labels:
        return plate, False

    # detect change
    old = [(L["answer"], round(L["x"], 3), round(L["y"], 3), round(L["w"], 3), round(L["h"], 3)) for L in plate["labels"]]
    new = [(L["answer"], round(L["x"], 3), round(L["y"], 3), round(L["w"], 3), round(L["h"], 3)) for L in new_labels]
    if old != new:
        changed = True

    plate = {**plate, "labels": new_labels}
    remask(plate)
    return plate, changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plates", nargs="*", help="optional plate ids; default = all")
    args = ap.parse_args()

    data = json.loads(DATA_JSON.read_text(encoding="utf-8"))
    want = set(args.plates) if args.plates else None

    print("Loading OCR…")
    ocr = RapidOCR()
    cache = {}
    plates = []
    n_changed = 0
    for plate in data["plates"]:
        if want and plate["id"] not in want:
            plates.append(plate)
            continue
        updated, changed = fix_plate(plate, ocr, cache)
        plates.append(updated)
        if changed:
            n_changed += 1
            print(f"{plate['id']}: {[L['answer'] for L in updated['labels']]}")
            for L in updated["labels"]:
                print(f"  wh=({L['w']:.3f},{L['h']:.3f}) {L['answer']}")

    pool = sorted({L["answer"] for p in plates for L in p["labels"]}, key=str.lower)
    questions = rebuild_questions(plates, pool)
    data = {
        **{k: v for k, v in data.items() if k not in ("plates", "questions", "answerPool", "plateCount", "questionCount")},
        "plateCount": len(plates),
        "questionCount": len(questions),
        "plates": plates,
        "questions": questions,
        "answerPool": pool,
        "masksFixed": True,
    }
    DATA_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    DATA_JS.write_text("window.SPOT_DATA = " + json.dumps(data, ensure_ascii=False) + ";\n", encoding="utf-8")
    print(f"\nDone: {n_changed} plates remasked, {len(questions)} questions")


if __name__ == "__main__":
    main()
