"""
Extract labeled dissection photos from PDF → masked assets + data.js for the quiz app.
"""
from __future__ import annotations

import json
import re
import hashlib
from pathlib import Path

import pymupdf as fitz
from PIL import Image, ImageDraw, ImageFilter
from rapidocr_onnxruntime import RapidOCR

from region_infer import refine_region

ROOT = Path(__file__).resolve().parent
PDF = ROOT.parent / "PDF" / "merged_version.pdf"
ASSETS = ROOT / "assets"
RAW = ROOT / "raw"
DATA_JS = ROOT / "data.js"

# Skip OCR junk / UI chrome
SKIP_RE = re.compile(
    r"^(?:"
    r"\d+|"
    r"[il|]"
    r")$",
    re.I,
)

# Prefer anatomical-looking labels
ANATO_HINT = re.compile(
    r"(?:"
    r"\b[mnav]\.?|"
    r"musculus|nervus|arteria|vena|ligament|tendo|fascia|"
    r"ramus|plexus|caput|truncus|communis|superficialis|profundus|"
    r"cutaneus|saphena|femoral|poplit|perone|tibial|ulnar|radial|"
    r"median|axillar|brach|glute|piriform|sciatic|ischiad|"
    r"insertio|origo|epicondyl|trochanter|tuberos|"
    r"digitorum|pollicis|hallucis|carpi|plantaris|palmaris"
    r")",
    re.I,
)


def page_title(page) -> str:
    text = (page.get_text() or "").strip()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return " ".join(lines) if lines else f"Pagina"


def normalize_label(s: str) -> str:
    s = s.strip()
    s = re.sub(r"\s+", " ", s)
    # Fix common OCR glues: A.poplitea → A. poplitea
    s = re.sub(r"([A-Za-z])\.([A-Za-z])", r"\1. \2", s)
    s = re.sub(r"([mvnaMVNA])\.(\S)", r"\1. \2", s)
    # Vmediana → V. mediana
    s = re.sub(r"^([VvAaNnMm])(?=[A-Z])", r"\1. ", s)
    return s.strip(" .,;:")


def box_center(box):
    xs = [p[0] for p in box]
    ys = [p[1] for p in box]
    return (sum(xs) / 4, sum(ys) / 4)


def box_aabb(box, pad=4):
    xs = [p[0] for p in box]
    ys = [p[1] for p in box]
    return [
        max(0, min(xs) - pad),
        max(0, min(ys) - pad),
        max(xs) + pad,
        max(ys) + pad,
    ]


def merge_nearby(items, y_tol=16, x_gap=32, stack_y=28):
    """Merge horizontally adjacent OR vertically stacked OCR fragments into one label."""
    if not items:
        return []
    items = sorted(items, key=lambda it: (it["cy"], it["cx"]))
    used = [False] * len(items)
    merged = []
    for i, a in enumerate(items):
        if used[i]:
            continue
        group = [a]
        used[i] = True
        changed = True
        while changed:
            changed = False
            for j, b in enumerate(items):
                if used[j]:
                    continue
                # horizontal: same line, to the right
                if abs(b["cy"] - group[-1]["cy"]) <= y_tol:
                    gap = b["x0"] - group[-1]["x1"]
                    if -8 <= gap <= x_gap:
                        group.append(b)
                        used[j] = True
                        changed = True
                        continue
                # vertical stack: overlapping x-range, just below
                # allow slight y-overlap (OCR pads often make stacked lines touch)
                gx0 = min(g["x0"] for g in group)
                gx1 = max(g["x1"] for g in group)
                gy1 = max(g["y1"] for g in group)
                x_overlap = min(gx1, b["x1"]) - max(gx0, b["x0"])
                y_gap = b["y0"] - gy1
                if x_overlap > 8 and -14 <= y_gap <= stack_y:
                    group.append(b)
                    used[j] = True
                    changed = True
        group.sort(key=lambda g: (g["cy"], g["cx"]))
        text = " ".join(g["text"] for g in group)
        text = normalize_label(text)
        x0 = min(g["x0"] for g in group)
        y0 = min(g["y0"] for g in group)
        x1 = max(g["x1"] for g in group)
        y1 = max(g["y1"] for g in group)
        conf = sum(g["conf"] for g in group) / len(group)
        merged.append(
            {
                "text": text,
                "x0": x0,
                "y0": y0,
                "x1": x1,
                "y1": y1,
                "cx": (x0 + x1) / 2,
                "cy": (y0 + y1) / 2,
                "conf": conf,
            }
        )
    return merged


JUNK = re.compile(
    r"(?:"
    r"terdemonstratie|spierenalleen|doorgesneden|port-?a-?cath|"
    r"abberante|zijtaknaar|segmentairebezenuwing|"
    r"^insertiom\.?$|^insertio$|^pees insertio$|"
    r"^medialis$|^lateralis$|^communis$|^minor$|^major$|"
    r"^plantaris$|^digitorum$|^hallucis$|^aponeurose$|"
    # Parenthetical note under Fasciculus lateralis — not a separate structure
    r"fasciculus\s*medialis\)|^\+|"
    r"ineanuchae|postenormajor|posterniorminor"
    r")",
    re.I,
)

# Only expand glued prefixes like Mbiceps / Ncutaneus (not plain "medianus")
GLUED_PREFIX = re.compile(
    r"^([MNAV])(?=(?:"
    r"biceps|brachialis|brachioradialis|coracobrachialis|deltoideus|"
    r"flexor|extensor|abductor|adductor|pronator|supinator|"
    r"pectoralis|piriformis|gluteus|trapezius|latissimus|infraspinatus|"
    r"semispinalis|splenius|obliquus|rectus|vastus|sartorius|gracilis|"
    r"tibialis|peroneus|palmaris|triceps|teres|rhomboideus|"
    r"cutaneus|medianus|ulnaris|radialis|axillaris|femoralis|"
    r"poplitea|saphena|cephalica|basilica|musculocutaneus|"
    r"occipitalis|ischiadicus|pudendus|thoracodorsalis|"
    r"circumflex|profunda|digitalis"
    r"))",
    re.I,
)

FIXES = [
    (re.compile(r"uinaris", re.I), "ulnaris"),
    (re.compile(r"uinanis", re.I), "ulnaris"),
    (re.compile(r"^ulnaris$", re.I), "N. ulnaris"),
    (re.compile(r"outaneus", re.I), "cutaneus"),
    (re.compile(r"musculooutaneus", re.I), "musculocutaneus"),
    (re.compile(r"femonis", re.I), "femoris"),
    (re.compile(r"obfiquus", re.I), "obliquus"),
    (re.compile(r"\bindices\b", re.I), "indicis"),
    (re.compile(r"semitendinosis", re.I), "semitendinosus"),
    (re.compile(r"saphenaparva", re.I), "saphena parva"),
    (re.compile(r"saphenamagna", re.I), "saphena magna"),
    (re.compile(r"latissimusdorsi", re.I), "latissimus dorsi"),
    # Insert spaces before common Latin endings — but NOT inside known compounds
    # (antebrachii, thoracodorsalis, musculocutaneus, …).
    (re.compile(
        r"(?<=[a-z])(?=(?:"
        r"longus|brevis|magnus|parva|major|minor|medialis|lateralis|"
        r"anterior|posterior|communis|superficialis|profundus|"
        r"capitis|femoris|pedis|venosus|"
        r"intermedius|plantaris|palmaris"
        r")\b)",
        re.I,
    ), " "),
    # brachii / dorsalis / cutaneus only when not part of a compound stem
    (re.compile(r"(?<!ante)(?<=[a-z])(?=brachii\b)", re.I), " "),
    (re.compile(r"(?<!thoraco)(?<=[a-z])(?=dorsalis\b)", re.I), " "),
    (re.compile(r"(?<!musculo)(?<=[a-z])(?=cutaneus\b)", re.I), " "),
    (re.compile(r"(?<=[a-z])(?=[A-Z])"), " "),
]

# Rejoin accidental splits of canonical compounds
COMPOUND_REPAIR = [
    (re.compile(r"\bthoraco\s+dorsalis\b", re.I), "thoracodorsalis"),
    (re.compile(r"\bthoraco\s+acromialis\b", re.I), "thoracoacromialis"),
    (re.compile(r"\bmusculo\s+cutaneus\b", re.I), "musculocutaneus"),
    (re.compile(r"\bante\s+brachii\b", re.I), "antebrachii"),
    (re.compile(r"\bvasto\s*adductoria\b", re.I), "vastoadductoria"),
]


def polish_label(text: str) -> str:
    t = normalize_label(text)
    t = GLUED_PREFIX.sub(r"\1. ", t)
    for rx, rep in FIXES:
        t = rx.sub(rep, t)
    for rx, rep in COMPOUND_REPAIR:
        t = rx.sub(rep, t)
    t = re.sub(r"\s+", " ", t).strip(" .,;:")
    t = re.sub(r"\.\s*\.", ".", t)
    return t


def keep_label(text: str, conf: float) -> bool:
    if conf < 0.45:
        return False
    if len(text) < 3:
        return False
    if SKIP_RE.match(text):
        return False
    if JUNK.search(text):
        return False
    # Drop pure punctuation / symbols
    if not re.search(r"[A-Za-z]", text):
        return False
    # Prefer anatomical; still keep longer title-like labels on plates
    if ANATO_HINT.search(text):
        return True
    # Keep if looks like Latin binomial fragment with capital
    if re.search(r"[A-Z][a-z]{3,}", text) and len(text) >= 6:
        return True
    return len(text) >= 10 and conf >= 0.7


def mask_labels(img: Image.Image, labels: list) -> Image.Image:
    out = img.copy().convert("RGB")
    draw = ImageDraw.Draw(out)
    w, h = out.size
    for lab in labels:
        x0, y0, x1, y1 = lab["x0"], lab["y0"], lab["x1"], lab["y1"]
        # Generous cover: OCR boxes hug glyphs tightly and JPEG softens edges
        pad_x = max(12, int((x1 - x0) * 0.06) + 10)
        pad_y = max(10, int((y1 - y0) * 0.25) + 8)
        box = [
            max(0, x0 - pad_x),
            max(0, y0 - pad_y),
            min(w - 1, x1 + pad_x),
            min(h - 1, y1 + pad_y),
        ]
        draw.rectangle(box, fill=(0, 0, 0))
    return out


def ocr_mask_boxes(img: Image.Image, ocr: RapidOCR) -> list[dict]:
    """Run OCR and return every text blob as a mask box (pixel coords)."""
    import tempfile

    # RapidOCR wants a path; write a short-lived JPEG
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        img.save(tmp_path, quality=95)
        result, _ = ocr(str(tmp_path))
    finally:
        tmp_path.unlink(missing_ok=True)

    boxes = []
    for line in result or []:
        box, text, conf = line
        try:
            conf_f = float(conf)
        except Exception:
            conf_f = 0.0
        text = str(text).strip()
        if conf_f < 0.35 or len(text) < 2 or not re.search(r"[A-Za-z]", text):
            continue
        if SKIP_RE.match(text):
            continue
        aabb = box_aabb(box, pad=2)
        boxes.append(
            {
                "text": text,
                "x0": aabb[0],
                "y0": aabb[1],
                "x1": aabb[2],
                "y1": aabb[3],
                "conf": conf_f,
            }
        )
    return boxes


def remask_plate(plate: dict, ocr: RapidOCR | None = None) -> None:
    """
    Rebuild quiz mask from the reveal image.
    Covers *all* OCR text (landmarks, leftovers, stacked lines) plus stored
    quiz label boxes so answers never stay readable.
    """
    reveal = ROOT / plate["imageReveal"]
    if not reveal.exists():
        return
    img = Image.open(reveal).convert("RGB")
    w, h = img.size

    boxes: list[dict] = []
    if ocr is not None:
        boxes.extend(ocr_mask_boxes(img, ocr))

    # Always paint stored quiz boxes too (belt + suspenders)
    for lab in plate.get("labels") or []:
        x0 = (lab["x"] - lab["w"] / 2) * w
        y0 = (lab["y"] - lab["h"] / 2) * h
        x1 = (lab["x"] + lab["w"] / 2) * w
        y1 = (lab["y"] + lab["h"] / 2) * h
        boxes.append({"x0": x0, "y0": y0, "x1": x1, "y1": y1})

    masked = mask_labels(img, boxes)
    out = ROOT / plate["image"]
    masked.save(out, quality=90, optimize=True)


def topic_slug(title: str) -> str:
    s = title.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:48] or "pagina"


def main():
    ASSETS.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)

    print("Loading OCR…")
    ocr = RapidOCR()
    doc = fitz.open(str(PDF))
    print(f"PDF pages: {len(doc)}")

    plates = []
    all_answers = set()

    for pi in range(len(doc)):
        page = doc[pi]
        title = page_title(page)
        imgs = page.get_images(full=True)
        if not imgs:
            continue

        for ii, imginfo in enumerate(imgs):
            xref = imginfo[0]
            try:
                pix = fitz.Pixmap(doc, xref)
            except Exception as e:
                print(f"  skip p{pi+1} img{ii}: {e}")
                continue
            if pix.width < 200 or pix.height < 200:
                continue
            if pix.n - pix.alpha > 3:
                pix = fitz.Pixmap(fitz.csRGB, pix)

            stem = f"p{pi+1:02d}_i{ii}"
            raw_path = RAW / f"{stem}.jpg"
            pix.save(str(raw_path))

            result, _ = ocr(str(raw_path))
            raw_items = []
            for line in result or []:
                box, text, conf = line
                try:
                    conf_f = float(conf)
                except Exception:
                    conf_f = 0.0
                text = normalize_label(str(text))
                aabb = box_aabb(box, pad=2)
                cx, cy = box_center(box)
                raw_items.append(
                    {
                        "text": text,
                        "x0": aabb[0],
                        "y0": aabb[1],
                        "x1": aabb[2],
                        "y1": aabb[3],
                        "cx": cx,
                        "cy": cy,
                        "conf": conf_f,
                    }
                )

            labels = merge_nearby(raw_items)
            for L in labels:
                L["text"] = polish_label(L["text"])

            img = Image.open(raw_path).convert("RGB")
            w, h = img.size

            # Cover every OCR blob (incl. junk fragments) so leftover
            # suffixes like "medialis" never stay readable on the quiz image.
            mask_boxes = [
                L
                for L in labels
                if L["conf"] >= 0.4
                and len(L["text"]) >= 2
                and re.search(r"[A-Za-z]", L["text"])
                and not SKIP_RE.match(L["text"])
            ]

            labels = [L for L in labels if keep_label(L["text"], L["conf"])]

            # Deduplicate nearly identical text on same plate, but keep
            # duplicates that sit far apart (same name, two real structures).
            uniq = []
            for L in labels:
                key = re.sub(r"[^a-z0-9]", "", L["text"].lower())
                if len(key) < 3:
                    continue
                dup = False
                for prev in uniq:
                    pkey = re.sub(r"[^a-z0-9]", "", prev["text"].lower())
                    if pkey != key:
                        continue
                    # same name nearby → drop; far apart → keep both
                    if abs(prev["cy"] - L["cy"]) < h * 0.12 and abs(prev["cx"] - L["cx"]) < w * 0.2:
                        dup = True
                        break
                if not dup:
                    uniq.append(L)
            labels = uniq

            if len(labels) < 1:
                continue
            masked = mask_labels(img, mask_boxes)
            # light compress for web
            asset_name = f"{stem}.jpg"
            masked_name = f"{stem}_mask.jpg"
            img.save(ASSETS / asset_name, quality=82, optimize=True)
            masked.save(ASSETS / masked_name, quality=82, optimize=True)

            plate_labels = []
            for L in labels:
                ans = L["text"]
                all_answers.add(ans)
                plate_labels.append(
                    {
                        "answer": ans,
                        "x": round(L["cx"] / w, 4),
                        "y": round(L["cy"] / h, 4),
                        # keep bbox for pin / highlight sizing
                        "w": round((L["x1"] - L["x0"]) / w, 4),
                        "h": round((L["y1"] - L["y0"]) / h, 4),
                    }
                )

            answers = [L["answer"] for L in plate_labels]
            region = refine_region(title, answers, ASSETS / asset_name)
            plates.append(
                {
                    "id": stem,
                    "page": pi + 1,
                    "topic": title,
                    "topicId": topic_slug(title),
                    "region": region,
                    "image": f"assets/{masked_name}",
                    "imageReveal": f"assets/{asset_name}",
                    "labels": plate_labels,
                }
            )
            print(f"p{pi+1} [{title}] → {region} img{ii}: {len(plate_labels)} labels → {answers}")

    # Build flat questions
    pool = sorted(all_answers)
    questions = []
    for plate in plates:
        answers_here = [L["answer"] for L in plate["labels"]]
        for idx, lab in enumerate(plate["labels"]):
            distractors = [a for a in answers_here if a != lab["answer"]]
            # pad from global pool
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

    regions = sorted({p["region"] for p in plates})
    topics = sorted({(p["topicId"], p["topic"], p["region"]) for p in plates}, key=lambda t: t[1])

    payload = {
        "generatedFrom": str(PDF.name),
        "plateCount": len(plates),
        "questionCount": len(questions),
        "regions": regions,
        "topics": [{"id": t[0], "label": t[1], "region": t[2]} for t in topics],
        "plates": plates,
        "questions": questions,
        "answerPool": pool,
    }

    meta_path = ROOT / "data.json"
    meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # JS module for browser
    DATA_JS.write_text(
        "window.SPOT_DATA = "
        + json.dumps(payload, ensure_ascii=False)
        + ";\n",
        encoding="utf-8",
    )

    print()
    print(f"Done: {len(plates)} plates, {len(questions)} questions, {len(pool)} unique answers")
    print(f"Wrote {DATA_JS} and {meta_path}")


if __name__ == "__main__":
    main()
