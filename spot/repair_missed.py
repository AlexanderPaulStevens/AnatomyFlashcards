"""Re-add labels that OCR found but build_data dropped (medialis/minor/brevis/…)."""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image
from rapidocr_onnxruntime import RapidOCR

ROOT = Path(__file__).resolve().parent
DATA_JSON = ROOT / "data.json"
DATA_JS = ROOT / "data.js"

# plate_id → list of (answer, list of OCR text fragments to merge for bbox)
REPAIRS = {
    # Parenthetical "fasciculusmedialis)" under lateralis was wrongly kept;
    # real Fasciculus medialis is bottom-right. Also restore N. ulnaris (OCR: uinanis).
    "p01_i1": [
        # Include parenthetical sublines so the mask covers the whole label block
        ("Fasciculus lateralis", ["Fasciculus lateralis", "+abberantezijtaknaar", "fasciculusmedialis)"]),
        ("N. musculocutaneus", ["N.musculooutaneus"]),
        ("N. medianus", ["N.medianus"]),
        ("N. ulnaris", ["uinanis"]),
        ("N. cutaneus brachii medialis", ["N.cutaneusbrachimedialis"]),
        ("Fasciculus medialis", ["Fasciculusmedialis"]),
    ],
    "p79_i1": [
        ("Fasciculus lateralis", ["Fasciculus lateralis", "+abberantezijtaknaar", "fasciculusmedialis)"]),
        ("N. musculocutaneus", ["N.musculooutaneus"]),
        ("N. medianus", ["N.medianus"]),
        ("N. ulnaris", ["uinanis"]),
        ("N. cutaneus brachii medialis", ["N.cutaneusbrachimedialis"]),
        ("Fasciculus medialis", ["Fasciculusmedialis"]),
    ],
    "p04_i0": [
        ("M. abductor digiti minimi", ["M.abductor", "digiti minimi"]),
        ("M. flexor digitorum brevis", ["M.flexor", "digitorum", "brevis"]),
        ("M. abductor hallucis", ["M.abductor", "hallucis"]),
        ("Aponeurose", ["Aponeurose"]),
    ],
    "p11_i2": [
        ("V. saphena parva", ["V.saphenaparva"]),
        ("N. cutaneus surae medialis", ["N.cutaneussurae", "medialis"]),
        ("N. cutaneus surae lateralis", ["N.cutaneus surae", "lateralis"]),
    ],
    "p52_i1": [
        ("M. splenius capitis", ["M. splenius capitis"]),
        ("M. levator scapulae", ["M.levator scapulae"]),
        ("M. rhomboideus minor", ["M.rhomboideus", "minor"]),
        ("M. trapezius", ["M.trapezius"]),
        ("M. rhomboideus major", ["M.rhomboideus", "major"]),
    ],
}


def norm(s: str) -> str:
    return "".join(ch.lower() for ch in s if ch.isalnum())


def box_aabb(box):
    xs = [p[0] for p in box]
    ys = [p[1] for p in box]
    return min(xs), min(ys), max(xs), max(ys)


def main():
    ocr = RapidOCR()
    data = json.loads(DATA_JSON.read_text(encoding="utf-8"))
    plates_by_id = {p["id"]: p for p in data["plates"]}

    for pid, specs in REPAIRS.items():
        plate = plates_by_id.get(pid)
        if not plate:
            print("missing plate", pid)
            continue
        raw = ROOT / "raw" / f"{pid}.jpg"
        img = Image.open(raw)
        w, h = img.size
        result, _ = ocr(str(raw))
        items = []
        for box, text, conf in result or []:
            items.append({"text": text, "n": norm(text), "box": box, "aabb": box_aabb(box)})

        new_labels = []
        used = set()
        for answer, frags in specs:
            matched = []
            for frag in frags:
                nf = norm(frag)
                candidates = []
                for i, it in enumerate(items):
                    if i in used:
                        continue
                    # Parenthetical OCR tails ("…)") only match frags that include ")"
                    if (")" in str(it["text"])) != (")" in frag):
                        continue
                    if it["n"] == nf or nf in it["n"] or it["n"] in nf:
                        candidates.append((i, it))
                if not candidates:
                    continue
                # Prefer exact norm match; otherwise lowest on the page (real label)
                candidates.sort(
                    key=lambda pair: (
                        0 if pair[1]["n"] == nf else 1,
                        -pair[1]["aabb"][1],
                    )
                )
                i, it = candidates[0]
                matched.append(it)
                used.add(i)
            if not matched:
                print(f"  {pid}: could not match {answer} ← {frags}")
                continue
            # For duplicate M.rhomboideus: prefer unused nearest to minor/major
            x0 = min(m["aabb"][0] for m in matched)
            y0 = min(m["aabb"][1] for m in matched)
            x1 = max(m["aabb"][2] for m in matched)
            y1 = max(m["aabb"][3] for m in matched)
            new_labels.append(
                {
                    "answer": answer,
                    "x": round(((x0 + x1) / 2) / w, 4),
                    "y": round(((y0 + y1) / 2) / h, 4),
                    "w": round((x1 - x0) / w, 4),
                    "h": round((y1 - y0) / h, 4),
                }
            )
        plate["labels"] = new_labels
        print(pid, "→", [L["answer"] for L in new_labels])

        from build_data import remask_plate

        remask_plate(plate, ocr=ocr)

    # rebuild questions + pool
    import hashlib

    all_answers = sorted({L["answer"] for p in data["plates"] for L in p["labels"]}, key=str.lower)
    questions = []
    for plate in data["plates"]:
        answers_here = [L["answer"] for L in plate["labels"]]
        for idx, lab in enumerate(plate["labels"]):
            distractors = [a for a in answers_here if a != lab["answer"]]
            for a in all_answers:
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

    data["questions"] = questions
    data["answerPool"] = all_answers
    data["questionCount"] = len(questions)
    data["plateCount"] = len(data["plates"])
    DATA_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    DATA_JS.write_text("window.SPOT_DATA = " + json.dumps(data, ensure_ascii=False) + ";\n", encoding="utf-8")
    print("questions", len(questions))


if __name__ == "__main__":
    main()
