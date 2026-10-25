"""
Verify & auto-correct spot quiz labels against OCR + anatomy priors.

- Re-OCR each plate; ground answers to text under pins
- Fix OCR typos / malformed prefixes
- Split obvious merged multi-labels when PLATE_ANSWERS known
- Spatial antonym checks (lateralis/medialis, major/minor, …)
- Topic inventory hints
- Auto-apply high-confidence fixes; write flags for the rest

Usage:
  python verify_anatomy.py           # fix + report
  python verify_anatomy.py --check   # report only
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from collections import defaultdict
from pathlib import Path

from PIL import Image
from rapidocr_onnxruntime import RapidOCR

from build_data import polish_label
from corrections import DROP, PLATE_ANSWERS, TEXT_FIX

ROOT = Path(__file__).resolve().parent
DATA_JSON = ROOT / "data.json"
DATA_JS = ROOT / "data.js"
REPORT_JSON = ROOT / "verification_report.json"
REPORT_MD = ROOT / "verification_report.md"
ASSETS = ROOT / "assets"
RAW = ROOT / "raw"

# --- OCR typo / punctuation repairs (applied to answers) ---
TYPO_FIXES = [
    (re.compile(r"\bpostenor\b", re.I), "posterior"),
    (re.compile(r"\bposternior\b", re.I), "posterior"),
    (re.compile(r"\bposterniorminor\b", re.I), "posterior minor"),
    (re.compile(r"capitisinferior", re.I), "capitis inferior"),
    (re.compile(r"propriusvan\s*", re.I), "proprius van "),
    (re.compile(r"^M[,:]\s*", re.I), "M. "),
    (re.compile(r"^N[,:]\s*", re.I), "N. "),
    (re.compile(r"^A[,:]\s*", re.I), "A. "),
    (re.compile(r"\bM[,:]", re.I), "M. "),
    (re.compile(r"\bN[,:]", re.I), "N. "),
    (re.compile(r"^medianus$", re.I), "N. medianus"),
    (re.compile(r"^ulnaris$", re.I), "N. ulnaris"),
    (re.compile(r"^semispinalis\s+", re.I), "M. semispinalis "),
    (re.compile(r"\bN\.?\s*femoris\b", re.I), "N. femoralis"),
    (re.compile(r"extensorpollicis", re.I), "extensor pollicis"),
    (re.compile(r"\buinanis\b", re.I), "ulnaris"),
    (re.compile(r"\s+", re.I), " "),
]

# Antonym pairs used for crop-OCR flip detection and spatial flags
ANTONYMS = [
    ("lateralis", "medialis"),
    ("longus", "brevis"),
    ("longum", "breve"),
    ("major", "minor"),
    ("capitis", "cervicis"),
    ("magna", "parva"),
    ("magnus", "parva"),
    ("superficialis", "profundus"),
    ("anterior", "posterior"),
    ("superior", "inferior"),
]

# Spatial priors: (a_token, b_token, axis, expect_a_less_than_b)
# axis 'y' → smaller y is higher on image; 'x' → smaller x is lefter
# Only flag large violations (photo orientation can vary).
SPATIAL_PRIORS = [
    # Fasciculus lateralis is superior to medialis in axillary dissection photos
    ("fasciculus lateralis", "fasciculus medialis", "y", True),
    # Teres minor sits superior to teres major
    ("teres minor", "teres major", "y", True),
    # Occipitalis major typically more medial/central than minor (weak — flag only)
]

# Topic → expected substrings (case-insensitive). Missing → flag.
TOPIC_EXPECT: dict[str, list[str]] = {
    "plexus-brachialis": [
        "fasciculus lateralis",
        "fasciculus medialis",
        "n. medianus",
        "n. musculocutaneus",
        "n. ulnaris",
    ],
    "fossa-poplitea": ["poplitea"],
    "suboccipitale-regio": [
        "obliquus capitis",
        "rectus capitis posterior",
        "semispinalis cervicis",
        "semispinalis capitis",
        "splenius capitis",
    ],
}

# OCR junk / notes that must never be quiz answers
JUNK_ANSWER = re.compile(
    r"(?:"
    r"^\+"
    r"|abberante"
    r"|zijtak"
    r"|terdemonstratie"
    r"|fasciculus\s*medialis\)"
    r"|^C[IVili]{1,4}\b.*\bM\."  # vertebra glued to muscle names
    r"|\)\s*$"
    r")",
    re.I,
)

# Capitalized structure prefixes only (ignore mid-label "n. femoralis")
PREFIX_COUNT = re.compile(r"(?:^|\s)(?:Nn|Aa|Vv|Rr|[MNAV])\s*\.")
WATERMARK = re.compile(r"roosen|jorg\b|joro\b", re.I)


def is_merged_label(answer: str) -> bool:
    """True only if multiple anatomical prefixes appear (two structures glued)."""
    n = len(PREFIX_COUNT.findall(answer))
    if re.search(r"\b[AV]\.\s*en\s*[AV]\.", answer):
        return n >= 3
    return n >= 2


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def soft_fix_text(answer: str) -> tuple[str, list[str]]:
    """Apply TEXT_FIX + typo regexes. Returns (new, list of change notes)."""
    notes = []
    a = answer.strip()
    if WATERMARK.search(a):
        return "", [f"DROP watermark {answer!r}"]
    if a in TEXT_FIX:
        notes.append(f"TEXT_FIX: {a!r}→{TEXT_FIX[a]!r}")
        a = TEXT_FIX[a]
    if a in DROP:
        return "", notes + [f"DROP {answer!r}"]
    # Exact-norm drop only when DROP entry has no distinguishing punctuation left in norm
    # (avoid dropping "Fasciculus medialis" because DROP has "fasciculus medialis)")
    for d in DROP:
        if ")" in d or d.endswith("+"):
            if a.lower().rstrip() == d.lower().rstrip():
                return "", notes + [f"DROP {answer!r}"]
        elif norm(a) == norm(d) and len(norm(d)) >= 6:
            return "", notes + [f"DROP {answer!r}"]
    before = a
    for rx, rep in TYPO_FIXES:
        a2 = rx.sub(rep, a)
        if a2 != a:
            a = a2
    for rx, rep in (
        (re.compile(r"\bante\s+brachii\b", re.I), "antebrachii"),
        (re.compile(r"\bthoraco\s+dorsalis\b", re.I), "thoracodorsalis"),
        (re.compile(r"\bmusculo\s+cutaneus\b", re.I), "musculocutaneus"),
    ):
        a = rx.sub(rep, a)
    # Only polish when text still looks like raw OCR (glued / missing dots)
    needs_polish = bool(
        re.search(r"[a-z]{8,}[A-Z]|[MNAV][a-z]{4,}|propriusvan|postenor", a)
        or (re.match(r"^[MNAV][,:]", a))
        or ("." not in a and re.match(r"^[MNAV]", a, re.I) and len(a) > 3)
    )
    if needs_polish:
        a = polish_label(a)
    a = re.sub(r"\s+", " ", a).strip(" .,;:")
    if a != before and not notes:
        notes.append(f"typo: {before!r}→{a!r}")
    elif a != before:
        notes.append(f"polish: {before!r}→{a!r}")
    return a, notes


def box_aabb(box):
    xs = [p[0] for p in box]
    ys = [p[1] for p in box]
    return min(xs), min(ys), max(xs), max(ys)


def ocr_image(ocr: RapidOCR, path: Path) -> list[dict]:
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
                "polished": polish_label(str(text)),
                "n": norm(str(text)),
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


def crop_ocr_text(ocr: RapidOCR, img: Image.Image, lab: dict, tmp: Path) -> str:
    W, H = img.size
    pad = 14
    x0 = max(0, int((lab["x"] - lab["w"] / 2) * W) - pad)
    y0 = max(0, int((lab["y"] - lab["h"] / 2) * H) - pad)
    x1 = min(W, int((lab["x"] + lab["w"] / 2) * W) + pad)
    y1 = min(H, int((lab["y"] + lab["h"] / 2) * H) + pad)
    if x1 - x0 < 48:
        x0, x1 = max(0, x0 - 24), min(W, x1 + 24)
    if y1 - y0 < 20:
        y0, y1 = max(0, y0 - 10), min(H, y1 + 10)
    crop = img.crop((x0, y0, x1, y1))
    crop.save(tmp, quality=95)
    result, _ = ocr(str(tmp))
    return " ".join(str(line[1]) for line in (result or []))


def antonym_flips(answer: str, crop: str) -> list[tuple[str, str]]:
    na, nc = norm(answer), norm(crop)
    flips = []
    for a, b in ANTONYMS:
        if a in na and b in nc and a not in nc:
            flips.append((a, b))
        if b in na and a in nc and b not in nc:
            flips.append((b, a))
    return flips


def apply_flip(answer: str, flips: list[tuple[str, str]]) -> str:
    out = answer
    for a, b in flips:
        # replace whole-word-ish token
        out = re.sub(rf"\b{re.escape(a)}\b", b, out, flags=re.I)
    return polish_label(out)


def token_overlap(a: str, b: str) -> int:
    ta = set(re.findall(r"[a-z]{4,}", norm(a)))
    tb = set(re.findall(r"[a-z]{4,}", norm(b)))
    return len(ta & tb)


# Distinctive OCR aliases → help match glued fragments to expected answers
OCR_ALIASES: dict[str, tuple[str, ...]] = {
    "m. biceps brachii caput breve": ("bicepsbrachicaputbrevis", "caputbrevis", "caput breve"),
    "m. biceps brachii caput longum": ("bicepsbrachili", "caputlongum", "caput longum"),
    "n. ulnaris": ("uinaris", "uinanis", "ulnaris"),
    "n. femoralis": ("femoris", "femoralis"),
    "n. musculocutaneus": ("musculooutaneus", "musculocutaneus"),
}


def match_expected_to_ocr(
    expected: list[str], items: list[dict], w: int, h: int
) -> list[dict]:
    """Greedy match each expected answer to best unused OCR fragment(s)."""
    used = set()
    labels = []
    for ans in expected:
        na = norm(ans)
        tokens = set(re.findall(r"[a-z]{4,}", na))
        aliases = OCR_ALIASES.get(ans.lower(), ())
        scored = []
        for i, it in enumerate(items):
            if i in used:
                continue
            # skip pure parentheticals unless answer itself has )
            if ")" in it["text"] and ")" not in ans:
                continue
            nt = it["n"]
            ov = len(tokens & set(re.findall(r"[a-z]{4,}", nt)))
            exact = 3 if (na and (na in nt or nt in na)) else 0
            alias_hit = 2 if any(norm(al) in nt or nt in norm(al) for al in aliases) else 0
            # prefer fragments that share distinctive tokens
            if ov == 0 and exact == 0 and alias_hit == 0:
                continue
            # Prefer more specific matches (caput longum vs breve)
            bonus = 0
            if "longum" in na and "longum" in nt:
                bonus += 2
            if "breve" in na or "brevis" in na:
                if "brevis" in nt or "breve" in nt:
                    bonus += 2
            scored.append((-(exact * 10 + ov * 3 + alias_hit * 5 + bonus + it["conf"]), it["cy"], i, it))
        if not scored:
            continue
        scored.sort()
        # take best; optionally merge nearby fragments that also match leftover tokens
        best_i = scored[0][2]
        best = scored[0][3]
        group = [best]
        used.add(best_i)
        covered = set(re.findall(r"[a-z]{4,}", best["n"]))
        for _, _, i, it in scored[1:]:
            if i in used:
                continue
            # same vertical band / close
            if abs(it["cy"] - best["cy"]) > h * 0.08:
                continue
            if abs(it["cx"] - best["cx"]) > w * 0.25:
                continue
            extra = set(re.findall(r"[a-z]{4,}", it["n"])) - covered
            if not (extra & tokens):
                continue
            # don't absorb a different antonym sibling
            bad = False
            for a, b in ANTONYMS:
                if a in na and b in it["n"] and a not in it["n"]:
                    bad = True
                if b in na and a in it["n"] and b not in it["n"]:
                    bad = True
            if bad:
                continue
            group.append(it)
            used.add(i)
            covered |= extra
        x0 = min(g["x0"] for g in group)
        y0 = min(g["y0"] for g in group)
        x1 = max(g["x1"] for g in group)
        y1 = max(g["y1"] for g in group)
        labels.append(
            {
                "answer": ans,
                "x": round(((x0 + x1) / 2) / w, 4),
                "y": round(((y0 + y1) / 2) / h, 4),
                "w": round((x1 - x0) / w, 4),
                "h": round((y1 - y0) / h, 4),
            }
        )
    return labels


def remask(plate: dict, ocr: RapidOCR | None = None) -> None:
    from build_data import remask_plate

    remask_plate(plate, ocr=ocr)


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


def plate_is_broken(labels: list[dict]) -> bool:
    for L in labels:
        a = L["answer"]
        if WATERMARK.search(a):
            return True
        if JUNK_ANSWER.search(a):
            return True
        if is_merged_label(a):
            return True
        if re.search(r"postenor|posternior|propriusvan|capitisinferior", a, re.I):
            return True
        if re.match(r"^[MNAV][,:]", a) or re.match(r"^semispinalis\b", a, re.I):
            return True
        if a.lower() in ("medianus", "ulnaris"):
            return True
        # Glued OCR dump without spaces between words
        if re.search(r"[a-z]{3,}[A-Z][a-z]{3,}", a) and " " not in a[2:]:
            return True
        if len(a) > 40 and a.count(" ") < 2:
            return True
        # Two muscle/nerve names jammed: "…brevis Mbiceps…" / "brachicaput"
        if re.search(r"\bM[a-z]{4,}", a) and a.lower().startswith("m."):
            return True
        if re.search(r"brachicaput|caputlongum|caputbrevis|bicepsbrach", a, re.I):
            return True
    return False


def verify_plate(
    plate: dict,
    ocr: RapidOCR,
    check_only: bool,
) -> tuple[dict, list[dict]]:
    """Returns (updated plate, list of issue dicts)."""
    issues: list[dict] = []
    pid = plate["id"]
    reveal = ROOT / plate["imageReveal"]
    raw = RAW / f"{pid}.jpg"
    src = raw if raw.exists() else reveal
    if not src.exists():
        issues.append({"plateId": pid, "severity": "error", "msg": "missing image"})
        return plate, issues

    img = Image.open(src).convert("RGB")
    w, h = img.size
    items = ocr_image(ocr, src)
    expected = PLATE_ANSWERS.get(pid)
    labels = list(plate["labels"])
    changed = False

    # 1) Rebuild badly broken plates from OCR + expected answers
    have_n = {norm(L["answer"]) for L in labels}
    want_n = {norm(a) for a in expected} if expected else set()
    overlap = len(have_n & want_n) if want_n else 0
    # Rebuild only when labels are structurally broken, or almost none match expected.
    needs_rebuild = bool(expected) and (
        plate_is_broken(labels)
        or (want_n and overlap == 0)
        or (want_n and overlap < max(1, len(want_n) // 3) and any(is_merged_label(L["answer"]) for L in labels))
    )
    if needs_rebuild:
        rebuilt = match_expected_to_ocr(expected, items, w, h)
        if len(rebuilt) >= max(1, len(expected) - 1):
            missing = [a for a in expected if norm(a) not in {norm(L["answer"]) for L in rebuilt}]
            issues.append(
                {
                    "plateId": pid,
                    "severity": "auto_rebuild",
                    "msg": f"rebuilt {len(rebuilt)}/{len(expected)} from OCR",
                    "missing": missing,
                    "was": [L["answer"] for L in labels],
                    "now": [L["answer"] for L in rebuilt],
                }
            )
            if not check_only:
                labels = rebuilt
                changed = True
            for m in missing:
                issues.append(
                    {
                        "plateId": pid,
                        "severity": "flag",
                        "msg": f"expected label not found in OCR: {m}",
                    }
                )
        else:
            issues.append(
                {
                    "plateId": pid,
                    "severity": "flag",
                    "msg": f"rebuild weak ({len(rebuilt)}/{len(expected)}); left unchanged",
                    "got": [L["answer"] for L in rebuilt],
                }
            )

    # 2) Soft text fixes on remaining labels
    cleaned = []
    for L in labels:
        new_a, notes = soft_fix_text(L["answer"])
        if not new_a:
            issues.append(
                {
                    "plateId": pid,
                    "severity": "auto_drop",
                    "msg": f"dropped junk/fragment: {L['answer']!r}",
                }
            )
            changed = True
            continue
        if new_a != L["answer"]:
            issues.append(
                {
                    "plateId": pid,
                    "severity": "auto_text",
                    "msg": "; ".join(notes) or f"{L['answer']!r}→{new_a!r}",
                    "x": L["x"],
                    "y": L["y"],
                }
            )
            L = {**L, "answer": new_a}
            changed = True
        if JUNK_ANSWER.search(L["answer"]) or is_merged_label(L["answer"]):
            issues.append(
                {
                    "plateId": pid,
                    "severity": "flag",
                    "msg": f"still looks merged/junk: {L['answer']!r}",
                    "x": L["x"],
                    "y": L["y"],
                }
            )
        cleaned.append(L)
    labels = cleaned

    # 3) Crop OCR antonym flips — flag only if sibling already has the flip target;
    # auto-fix only when the flipped name is absent from siblings (mislabel, not swap).
    tmp = RAW / "_verify_crop.jpg"
    RAW.mkdir(parents=True, exist_ok=True)
    sibling_norms = {norm(L["answer"]) for L in labels}
    for i, L in enumerate(labels):
        crop = crop_ocr_text(ocr, img, L, tmp)
        if not crop.strip():
            issues.append(
                {
                    "plateId": pid,
                    "severity": "flag",
                    "msg": f"empty crop OCR for {L['answer']!r}",
                    "x": L["x"],
                    "y": L["y"],
                }
            )
            continue
        flips = antonym_flips(L["answer"], crop)
        if not flips:
            continue
        fixed = apply_flip(L["answer"], flips)
        if norm(fixed) in sibling_norms:
            # Both antonyms already on plate → crop likely overlapped neighbor; flag only
            issues.append(
                {
                    "plateId": pid,
                    "severity": "flag",
                    "msg": (
                        f"crop suggests {fixed!r} but sibling already has it; "
                        f"kept {L['answer']!r} (crop={crop!r})"
                    ),
                    "x": L["x"],
                    "y": L["y"],
                }
            )
            continue
        # Auto-fix only with strong evidence from full-plate OCR at this pin
        if any(norm(fixed) in it["n"] or it["n"] in norm(fixed) for it in items):
            issues.append(
                {
                    "plateId": pid,
                    "severity": "auto_flip",
                    "msg": f"{L['answer']!r}→{fixed!r} (crop={crop!r}, flips={flips})",
                    "x": L["x"],
                    "y": L["y"],
                }
            )
            if not check_only:
                labels[i] = {**L, "answer": fixed}
                sibling_norms.discard(norm(L["answer"]))
                sibling_norms.add(norm(fixed))
                changed = True
        else:
            issues.append(
                {
                    "plateId": pid,
                    "severity": "flag",
                    "msg": f"possible flip {L['answer']!r} vs crop {crop!r} {flips}",
                    "x": L["x"],
                    "y": L["y"],
                }
            )

    # 4) Spatial priors
    by_key = {L["answer"].lower(): L for L in labels}
    for a_name, b_name, axis, a_less in SPATIAL_PRIORS:
        La = by_key.get(a_name)
        Lb = by_key.get(b_name)
        if not La or not Lb:
            # partial match
            La = La or next((L for L in labels if a_name in L["answer"].lower()), None)
            Lb = Lb or next((L for L in labels if b_name in L["answer"].lower()), None)
        if not La or not Lb:
            continue
        va, vb = (La["y"], Lb["y"]) if axis == "y" else (La["x"], Lb["x"])
        ok = va < vb if a_less else va > vb
        if not ok and abs(va - vb) > 0.08:
            issues.append(
                {
                    "plateId": pid,
                    "severity": "flag",
                    "msg": (
                        f"spatial: expected {a_name} {'above/left of' if a_less else 'below/right of'} "
                        f"{b_name} on {axis}, got {a_name}={va:.2f} {b_name}={vb:.2f}"
                    ),
                }
            )

    # Generic lateralis vs medialis same stem: lateralis should not share near-identical coords with a note
    lat = [L for L in labels if re.search(r"\blateralis\b", L["answer"], re.I)]
    med = [L for L in labels if re.search(r"\bmedialis\b", L["answer"], re.I)]
    for La in lat:
        for Lb in med:
            stem_a = re.sub(r"lateralis", "*", La["answer"].lower())
            stem_b = re.sub(r"medialis", "*", Lb["answer"].lower())
            if norm(stem_a) != norm(stem_b):
                continue
            if abs(La["y"] - Lb["y"]) < 0.06 and abs(La["x"] - Lb["x"]) < 0.08:
                issues.append(
                    {
                        "plateId": pid,
                        "severity": "flag",
                        "msg": f"antonym pair almost overlapping: {La['answer']!r} & {Lb['answer']!r}",
                    }
                )

    # 5) Topic inventory (only when plate already looks like that topic)
    tid = plate.get("topicId") or ""
    expect = TOPIC_EXPECT.get(tid)
    if expect:
        have = " | ".join(L["answer"].lower() for L in labels)
        # Skip inventory if this photo clearly belongs to a sibling topic page
        # (e.g. p01_i0 shares topicId plexus but shows biceps, not cords)
        topic_anchor = expect[0]
        if topic_anchor.split()[0] in have or any(
            e.split()[-1] in have for e in expect[:2]
        ):
            for exp in expect:
                if exp not in have:
                    issues.append(
                        {
                            "plateId": pid,
                            "severity": "flag",
                            "msg": f"topic {tid} missing expected: {exp}",
                        }
                    )

    # Deduplicate answers after fixes
    seen = set()
    deduped = []
    for L in labels:
        k = norm(L["answer"])
        if k in seen:
            issues.append(
                {
                    "plateId": pid,
                    "severity": "auto_drop",
                    "msg": f"duplicate after fix: {L['answer']!r}",
                }
            )
            changed = True
            continue
        seen.add(k)
        deduped.append(L)
    labels = deduped

    if changed and not check_only:
        plate = {**plate, "labels": labels}
        remask(plate, ocr=ocr)

    return plate, issues


def write_report(all_issues: list[dict], plates: list[dict]) -> None:
    by_sev = defaultdict(list)
    for it in all_issues:
        by_sev[it["severity"]].append(it)

    payload = {
        "issueCount": len(all_issues),
        "bySeverity": {k: len(v) for k, v in by_sev.items()},
        "issues": all_issues,
        "plateCount": len(plates),
    }
    REPORT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Spot verification report",
        "",
        f"- Plates: {len(plates)}",
        f"- Issues: {len(all_issues)}",
        "",
    ]
    for sev in ("auto_rebuild", "auto_flip", "auto_text", "auto_drop", "flag", "error"):
        items = by_sev.get(sev) or []
        if not items:
            continue
        lines.append(f"## {sev} ({len(items)})")
        lines.append("")
        for it in items:
            extra = ""
            if it.get("now"):
                extra = f" → {it['now']}"
            lines.append(f"- **{it['plateId']}**: {it['msg']}{extra}")
        lines.append("")
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="report only, do not write data")
    args = ap.parse_args()

    data = json.loads(DATA_JSON.read_text(encoding="utf-8"))
    print("Loading OCR…")
    ocr = RapidOCR()

    plates = []
    all_issues: list[dict] = []
    for plate in data["plates"]:
        updated, issues = verify_plate(plate, ocr, check_only=args.check)
        plates.append(updated)
        all_issues.extend(issues)
        autos = [i for i in issues if i["severity"].startswith("auto")]
        flags = [i for i in issues if i["severity"] == "flag"]
        if autos or flags:
            print(
                f"{plate['id']}: {len(autos)} auto, {len(flags)} flags"
                + (f" — {[i['msg'][:60] for i in (autos+flags)[:3]]}" if autos or flags else "")
            )

    write_report(all_issues, plates)

    if not args.check:
        all_answers = sorted(
            {L["answer"] for p in plates for L in p["labels"]}, key=str.lower
        )
        questions = rebuild_questions(plates, all_answers)
        regions = sorted({p["region"] for p in plates})
        topics = sorted(
            {(p["topicId"], p["topic"], p["region"]) for p in plates}, key=lambda t: t[1]
        )
        payload = {
            **{
                k: v
                for k, v in data.items()
                if k
                not in (
                    "plates",
                    "questions",
                    "answerPool",
                    "regions",
                    "topics",
                    "plateCount",
                    "questionCount",
                )
            },
            "plateCount": len(plates),
            "questionCount": len(questions),
            "regions": regions,
            "topics": [{"id": t[0], "label": t[1], "region": t[2]} for t in topics],
            "plates": plates,
            "questions": questions,
            "answerPool": all_answers,
            "anatomyVerified": True,
            "assetVersion": time.strftime("%Y%m%d%H%M"),
        }
        DATA_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        DATA_JS.write_text(
            "window.SPOT_DATA = " + json.dumps(payload, ensure_ascii=False) + ";\n",
            encoding="utf-8",
        )
        print(f"\nWrote data ({len(questions)} questions)")

    print(
        f"Report: {REPORT_MD.name} — "
        f"{sum(1 for i in all_issues if i['severity'].startswith('auto'))} auto-fixes, "
        f"{sum(1 for i in all_issues if i['severity']=='flag')} flags"
    )


if __name__ == "__main__":
    main()
