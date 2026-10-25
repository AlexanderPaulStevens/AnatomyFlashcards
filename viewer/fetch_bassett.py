"""
Fetch Stanford Bassett Collection metadata for limb plates and match checklist terms.

License: CC BY-SA 4.0 (Stanford / Bassett Collection)
Only keeps a plate for a term when the structure name appears in the plate legend.
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INDEX = ROOT / "_ocr" / "bassett_plates_index.json"
CATALOG = ROOT / "_ocr" / "bassett_catalog.json"
MATCHES = ROOT / "_ocr" / "bassett_matches.json"
ROWS = ROOT / "_ocr" / "rows.json"
ASSETS = ROOT / "assets" / "bassett"
UA = "AnatoViewer/1.0 (KU Leuven anatomy study; educational; CC BY-SA attribution)"


def norm(s: str) -> str:
    s = (s or "").replace("**", "").strip().lower()
    s = s.replace("mm.", "m.").replace("nn.", "n.").replace("aa.", "a.").replace("rr.", "r.")
    s = s.replace("peroneus", "fibularis").replace("peroneal", "fibular")
    s = re.sub(r"\([^)]*\)", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"[^a-z0-9./ ]", "", s)
    return s


def core_tokens(term: str) -> list[str]:
    n = norm(term)
    n = re.sub(r"^(m|n|a|v|r|ligamentum|fascia|aponeurosis|tractus|retinaculum|arcus|rete|hiatus)\.?\s*", "", n)
    soft_stop = {
        "medialis", "lateralis", "anterior", "posterior", "superior", "inferior",
        "communis", "superficialis", "profundus", "caput", "pars", "proprius",
        "muscle", "nerve", "artery", "vein", "and",
    }
    size_words = {"longus", "brevis", "major", "minor"}
    generic = {"adductor", "abductor", "extensor", "flexor", "rotator", "pronator", "supinator"}
    all_toks = re.findall(r"[a-z]{4,}", n)
    # Drop soft stop words, but keep size words
    toks = [t for t in all_toks if t not in soft_stop]
    # Always keep size words when paired with a generic family name
    if any(t in generic for t in toks):
        for sw in size_words:
            if sw in all_toks and sw not in toks:
                toks.append(sw)
    return toks or [t for t in re.findall(r"[a-z]{5,}", n)]


def get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def parse_plate(bn: str, region: str) -> dict | None:
    url = f"https://lane.stanford.edu/biomed-resources/bassett/bassettView.html?bn={bn}"
    html = get(url)
    # photo (L = left stereo photograph; skip D drawings)
    imgs = re.findall(r'//lane\.stanford\.edu/elane/public/[^\"\']+\.L\.jpg', html, re.I)
    if not imgs:
        imgs = re.findall(r'https?://lane\.stanford\.edu/elane/public/[^\"\']+\.L\.jpg', html, re.I)
    if not imgs:
        return None
    photo = imgs[0]
    if photo.startswith("//"):
        photo = "https:" + photo
    # prefer larger if available
    photo_large = photo.replace("/medium/", "/large/")

    title = ""
    m = re.search(r"Image\s*#\s*" + re.escape(bn) + r".*?</h\d>\s*<.*?>(.*?)</", html, re.I | re.S)
    # subtitle often in h4/h3
    for pat in (
        r'<h4[^>]*>(.*?)</h4>',
        r'<h3[^>]*>(.*?)</h3>',
        r'<h2[^>]*>(.*?)</h2>',
    ):
        hm = re.search(pat, html, re.I | re.S)
        if hm:
            t = re.sub(r"<[^>]+>", " ", hm.group(1))
            t = re.sub(r"\s+", " ", t).strip()
            if t and "Bassett" not in t and "Creative Commons" not in t:
                title = t
                break

    # legend: prefer <ol><li>… then plain "1. Label" lines
    labels = []
    for ol in re.findall(r"<ol[^>]*>(.*?)</ol>", html, re.I | re.S):
        items = re.findall(r"<li[^>]*>(.*?)</li>", ol, re.I | re.S)
        if not items or len(items) > 50:
            continue
        for it in items:
            lab = re.sub(r"<[^>]+>", " ", it)
            lab = re.sub(r"\s+", " ", lab).strip()
            if 4 <= len(lab) <= 180 and not lab.lower().startswith("creative commons"):
                labels.append(lab)
        if labels:
            break
    if not labels:
        text = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
        text = re.sub(r"</li>", "\n", text, flags=re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"[ \t]+", " ", text)
        for line in text.splitlines():
            line = line.strip()
            m = re.match(r"^(\d{1,3})\.\s+(.+)$", line)
            if not m:
                continue
            lab = m.group(2).strip()
            if len(lab) < 4 or len(lab) > 180:
                continue
            if lab.lower().startswith("creative commons"):
                continue
            labels.append(lab)

    return {
        "bn": bn,
        "region": region,
        "title": title,
        "page": url,
        "photo": photo_large,
        "photo_medium": photo,
        "labels": labels,
        "label_blob": " | ".join(labels).lower(),
    }


def core_phrase(term: str) -> str:
    n = norm(term)
    n = re.sub(r"^(mm?|nn?|aa?|vv?|rr?)\. ", "", n)
    n = re.sub(r"^(ligamentum|fascia|aponeurosis|tractus|retinaculum|arcus|rete|hiatus) ", "", n)
    return n.strip()


def expand_hay(hay: str) -> str:
    """Bassett uses peroneus/peroneal; checklist uses fibularis/fibular (and vice versa)."""
    alts = [
        hay,
        hay.replace("peroneus", "fibularis").replace("peroneal", "fibular"),
        hay.replace("fibularis", "peroneus").replace("fibular ", "peroneal ").replace("fibular\n", "peroneal\n"),
        # English ↔ Latin plurals / common Bassett wording
        hay.replace("lumbricales", "lumbrical").replace("lumbrical muscles", "lumbricales"),
        hay.replace("sublimis", "superficialis"),
        hay.replace("superficialis", "sublimis"),
    ]
    return " | ".join(alts)


# Latin checklist core → English phrases that appear in Bassett legends/titles
ENGLISH_ALIASES = {
    "ulnaris": ["ulnar"],
    "radialis": ["radial"],
    "medianus": ["median"],
    "tibialis": ["tibial"],
    "femoralis": ["femoral"],
    "axillaris": ["axillary"],
    "musculocutaneus": ["musculocutaneous"],
    "ischiadicus": ["sciatic"],
    "obturatorius": ["obturator"],
    "suralis": ["sural"],
    "accessorius": ["accessory"],
    "suprascapularis": ["suprascapular"],
    "subscapularis": ["subscapular"],
    "vertebralis": ["vertebral"],
    "gluteus minimus": ["gluteus minimus"],
    "glutea inferior": ["inferior gluteal"],
    "glutea superior": ["superior gluteal"],
    "gluteus inferior": ["inferior gluteal"],
    "gluteus superior": ["superior gluteal"],
    "plantaris lateralis": ["lateral plantar"],
    "plantaris medialis": ["medial plantar"],
    "tibialis anterior": ["anterior tibial", "tibialis anterior"],
    "tibialis posterior": ["posterior tibial", "tibialis posterior"],
    "circumflexa humeri": ["circumflex humeral"],
    "circumflexa ilium": ["circumflex iliac"],
    "epigastrica inferior": ["inferior epigastric"],
    "profunda femoris": ["profunda femoris", "deep femoral"],
    "perforantes": ["perforating"],
    "pudendae externae": ["external pudendal"],
    "pudenda interna": ["internal pudendal"],
    "thoracicus longus": ["long thoracic"],
    "thoracodorsalis": ["thoracodorsal"],
    "thoracoepigastrica": ["thoracoepigastric", "thoraco-epigastric"],
    "thoraco-epigastrica": ["thoracoepigastric", "thoraco-epigastric"],
    "transversa colli": ["transverse cervical"],
    "dorsalis scapulae": ["dorsal scapular"],
    "auricularis magnus": ["great auricular", "greater auricular"],
    "cutaneus brachii lateralis inferior": [
        "inferior lateral cutaneous nerve of arm",
        "lower lateral cutaneous nerve of arm",
        "inferior lateral brachial cutaneous",
    ],
    "digitales plantares communes": ["common plantar digital"],
    "digitalis plantaris": ["plantar digital"],
    "metatarsales plantares": ["plantar metatarsal"],
    "saphenus": ["saphenous"],
    "hiatus saphenus": ["saphenous opening", "fossa ovalis"],
    "tractus iliotibialis": ["iliotibial"],
    "iliotibialis": ["iliotibial"],
    "fascia cruris": ["crural fascia", "fascia of leg"],
    "cruris": ["crural fascia"],
    "fascia thoracolumbalis": ["thoracolumbar fascia", "lumbodorsal fascia"],
    "thoracolumbalis": ["thoracolumbar fascia", "lumbodorsal fascia"],
    "aponeurosis plantaris": ["plantar aponeurosis"],
    "retinaculum mm. extensorum": ["extensor retinaculum", "retinaculum of extensors"],
    "extensorum superius": ["superior extensor retinaculum", "transverse crural"],
    "extensorum inferius": ["inferior extensor retinaculum", "cruciate crural"],
    "retinaculum": ["retinaculum"],
    "arcus palmaris profundus": ["deep palmar arch"],
    "palmaris profundus": ["deep palmar arch"],
    "subscapulares": ["subscapular nerve", "subscapular nerves"],
    "fibularis profundus": ["deep peroneal nerve", "deep fibular nerve"],
    "peroneus profundus": ["deep peroneal nerve", "deep fibular nerve"],
    "adductor pollicis": ["adductor pollicis"],
    "flexor digiti minimi brevis": ["flexor digiti minimi", "flexor digiti quinti"],
    "semispinalis thoracis": ["semispinalis thoracis"],
    "semispinalis cervicis": ["semispinalis cervicis", "semispinalis colli"],
    "gluteus superior": ["superior gluteal nerve"],
    "gluteus inferior": ["inferior gluteal nerve"],
    "glutea superior": ["superior gluteal artery", "superior gluteal"],
    "glutea inferior": ["inferior gluteal artery", "inferior gluteal"],
    "genu media": ["middle genicular", "medial genicular artery"],
    "genu superior lateralis": ["lateral superior genicular", "superior lateral genicular"],
    "genu superior medialis": ["medial superior genicular", "superior medial genicular"],
    "genu inferior lateralis": ["lateral inferior genicular", "inferior lateral genicular"],
    "genu inferior medialis": ["medial inferior genicular", "inferior medial genicular"],
    "genu superior": ["superior genicular"],
    "genu inferior": ["inferior genicular"],
    "rete venosum dorsale manus": ["dorsal venous rete", "dorsal venous network", "venous rete of the hand"],
    "venosum dorsale manus": ["dorsal venous rete", "dorsal venous network", "venous rete of the hand"],
    "venosum dorsale": ["dorsal venous rete", "dorsal venous"],
    "rr. dorsales": ["dorsal rami of spinal", "dorsal ramus", "dorsal rami"],
    "dorsales spinale": ["dorsal rami of spinal", "dorsal ramus", "dorsal rami"],
    "dorsalis n. ulnaris": ["dorsal hand branch of ulnar", "dorsal branch of ulnar", "dorsal ulnar"],
    "auricularis magnus": ["great auricular", "greater auricular"],
    "epigastrica inferior": ["inferior epigastric"],
    "dorsalis n. ulnaris": [
        "dorsal hand branch of ulnar",
        "dorsal branch of ulnar",
        "dorsal ulnar",
    ],
    "suboccipitalis": ["suboccipital nerve", "suboccipital"],
    "ulnaris r. palmaris": ["palmar branch of ulnar", "palmar cutaneous branch of ulnar"],
    "collateralis ulnaris": ["ulnar collateral"],
    "pudendae externae": ["external pudendal"],
    "digitales plantares communes": ["common plantar digital"],
    "transversa colli": ["transverse cervical"],
    "suboccipitalis": ["suboccipital"],
    "rete venosum dorsale": ["dorsal venous network", "dorsal venous arch"],
    "rete venosum dorsale manus": ["dorsal venous", "venous network"],
    "opponens digiti minimi": ["opponens digiti minimi", "opponens digiti quinti"],
    "flexor digiti minimi": ["flexor digiti minimi", "flexor digiti quinti"],
    "adductor hallucis": ["adductor hallucis"],
    "adductor pollicis": ["adductor pollicis"],
    "adductor brevis": ["adductor brevis"],
    "quadratus femoris": ["quadratus femoris"],
    "gemellus": ["gemellus"],
    "popliteus": ["popliteus"],
    "plantaris": ["plantaris"],
    "pronator teres": ["pronator teres"],
    "flexor digitorum superficialis": ["flexor digitorum superficialis", "flexor digitorum sublimis"],
    "flexor hallucis longus": ["flexor hallucis longus"],
    "flexor hallucis brevis": ["flexor hallucis brevis"],
    "flexor digitorum longus": ["flexor digitorum longus"],
    "extensor digiti minimi": ["extensor digiti minimi", "extensor digiti quinti"],
    "extensor carpi radialis": ["extensor carpi radialis"],
    "vastus intermedius": ["vastus intermedius"],
    "splenius cervicis": ["splenius cervicis", "splenius colli"],
    "semispinalis": ["semispinalis"],
    "suboccipitalis": ["suboccipital"],
    "sacrospinale": ["sacrospinous"],
    "interossei": ["interosseous", "interossei"],
    "lumbricales": ["lumbrical"],
    "mediana antebrachii": ["median antebrachial", "intermediate antebrachial"],
    "collateralis ulnaris": ["ulnar collateral"],
    "surales": ["sural"],
    "genu": ["genicular"],
}


def _normalize_line(t: str) -> str:
    t = re.sub(r"^\d+\.\s*", "", t).strip().lower()
    t = t.replace("peroneus", "fibularis").replace("peroneal", "fibular")
    t = t.replace("sublimis", "superficialis")
    t = t.replace("lumbrical muscles", "lumbricales").replace("lumbrical muscle", "lumbricales")
    return t


def plate_lines(plate: dict) -> list[str]:
    """Cached searchable legend lines (+ title), normalized to checklist spelling."""
    cached = plate.get("_lines")
    if cached is not None:
        return cached
    out: list[str] = []
    for lab in plate.get("labels") or []:
        if isinstance(lab, dict):
            t = lab.get("text") or ""
        else:
            t = str(lab)
        t = _normalize_line(t)
        if t:
            out.append(t)
    title = _normalize_line(plate.get("title") or "")
    if title:
        out.append(title)
    plate["_lines"] = out
    return out


_ALIAS_KEYS = tuple(sorted(ENGLISH_ALIASES, key=len, reverse=True))


def line_has_phrase(line: str, phrase: str) -> bool:
    """True if this single legend line names the structure (Latin or English alias)."""
    if len(phrase) < 4:
        return False
    toks = re.findall(r"[a-z]{3,}", phrase)
    if toks:
        pat = r"\b" + r"\s+".join(re.escape(t) for t in toks) + r"\b"
        if re.search(pat, line):
            return True
    for lat in _ALIAS_KEYS:
        if lat not in phrase:
            continue
        for en in ENGLISH_ALIASES[lat]:
            en_toks = [
                t
                for t in re.findall(r"[a-z]{3,}", en)
                if t not in {"the", "of", "and", "to"}
            ]
            if not en_toks or not all(re.search(rf"\b{re.escape(t)}\b", line) for t in en_toks):
                continue
            rest = phrase.replace(lat, " ")
            rest_toks = [
                t
                for t in re.findall(r"[a-z]{4,}", rest)
                if t not in {"muscle", "nerve", "artery", "vein", "zenuwen"}
            ]
            if all(re.search(rf"\b{re.escape(t)}\b", line) for t in rest_toks):
                return True
    # special: checklist "aponeurosis plantaris" → Bassett "plantar aponeurosis"
    if "aponeurosis" in line and "plantar" in line and "plantaris" in phrase:
        return True
    return False


def typed_line_ok(term: str, line: str) -> bool:
    """Require the structure type to appear on the SAME legend line."""
    n = norm(term)
    phrase = term_phrases(term)[0] if term_phrases(term) else core_phrase(term)

    # Skip unhelpful title-only fluff
    if line.startswith("nerve supply to") and not (n.startswith("n.") or n.startswith("r.")):
        # "Nerve supply to X muscle" is about the nerve, not a good muscle plate match alone
        # unless the muscle name is the subject — still allow muscle if "X muscle" clearly present
        if n.startswith("m.") and re.search(r"\bmuscle\b", line):
            pass
        else:
            return False

    if n.startswith("a.") or n.startswith("aa."):
        if not re.search(r"\b(artery|arteries|arteria|arch)\b", line):
            return False
        if re.search(r"\bcutaneous\b", line):
            return False
        # Main trunk names must appear as "<name> artery", not "… circumflex/… digital …"
        trunk = {
            "femoralis": r"\bfemoral artery\b",
            "radialis": r"\bradial artery\b",
            "ulnaris": r"\bulnar artery\b",
            "axillaris": r"\baxillary artery\b",
            "poplitea": r"\bpopliteal artery\b",
            "brachialis": r"\bbrachial artery\b",
        }
        for lat, pat in trunk.items():
            if lat in phrase and not re.search(pat, line):
                # allow English alias already in line via circumflex only for circumflexa terms
                if "circumflex" in phrase or "collateral" in phrase or "profunda" in phrase:
                    continue
                return False
    elif n.startswith("v.") or n.startswith("vv."):
        if not re.search(r"\b(vein|veins|vena)\b", line):
            return False
        if "femoralis" in phrase and not re.search(r"\bfemoral vein\b", line):
            return False
    elif n.startswith("n.") or n.startswith("nn.") or n.startswith("r.") or n.startswith("rr."):
        if not re.search(r"\b(nerve|nerves|nervus)\b", line):
            return False
        if "nerve supply to" in line:
            return False
        # "posterior femoral cutaneous nerve" must not satisfy N. femoralis
        trunk_n = {
            "femoralis": r"\bfemoral nerve\b",
            "radialis": r"\bradial nerve\b",
            "ulnaris": r"\bulnar nerve\b",
            "tibialis": r"\btibial nerve\b",
            "medianus": r"\bmedian nerve\b",
            "axillaris": r"\baxillary nerve\b",
            "obturatorius": r"\bobturator nerve\b",
            "ischiadicus": r"\bsciatic nerve\b",
            "suralis": r"\bsural nerve\b",
            "saphenus": r"\bsaphenous nerve\b",
        }
        for lat, pat in trunk_n.items():
            if lat in phrase and not re.search(pat, line):
                return False
    elif n.startswith("m.") or n.startswith("mm."):
        # Must look like a muscle label; reject pure vessel/nerve lines
        if not re.search(r"\b(muscle|muscles|musculus)\b", line):
            # titles like "Peroneus brevis muscle" already have it; some short titles omit it
            if not re.search(r"\b(peroneus|fibularis|tibialis|gluteus|flexor|extensor|adductor|abductor)\b", line):
                return False
        # Arm triceps ≠ triceps surae
        if re.search(r"\btriceps\b", phrase):
            if "surae" in line:
                return False
            if not re.search(r"\b(brachii|triceps brachii|lateral head|long head|medial head)\b", line):
                return False
    elif n.startswith("aponeurosis") or "aponeurosis" in n:
        if "aponeurosis" not in line and "aponeurotic" not in line:
            return False
    elif "arcus" in n:
        if "arcus" not in line and "arch" not in line:
            return False
    elif n.startswith("fascia") or n.startswith("tractus") or n.startswith("retinaculum"):
        if not re.search(r"\b(fascia|tract|retinaculum)\b", line):
            return False
    elif n.startswith("ligamentum"):
        if "ligament" not in line:
            return False
    elif n.startswith("hiatus"):
        if "hiatus" not in line and "opening" not in line and "fossa ovalis" not in line:
            return False

    return any(line_has_phrase(line, ph) for ph in term_phrases(term))


_WEAK_PHRASE = {
    "superior", "inferior", "anterior", "posterior", "medialis", "lateralis",
    "medial", "lateral", "longus", "brevis", "major", "minor", "superficialis",
    "profundus", "communis", "proprius",
}


def _usable_phrase(p: str) -> bool:
    p = p.strip(" .")
    if len(p) < 5:
        return False
    if p in _WEAK_PHRASE:
        return False
    toks = re.findall(r"[a-z]{3,}", p)
    if not toks:
        return False
    # must contain at least one non-qualifier token
    if all(t in _WEAK_PHRASE for t in toks):
        return False
    return True


def term_phrases(term: str) -> list[str]:
    """Core phrases to try, including / and 'en' splits and without branch/caput tails."""
    phrase = core_phrase(term)
    out = [phrase]
    # drop branch / head / pars tails: "… r. superficialis", "caput transversum"
    trimmed = re.sub(
        r"\b(r\.?\s*)?(superficialis|profundus|ascendens|descendens|transversa|transversum)\b.*$",
        "",
        phrase,
    ).strip()
    trimmed = re.sub(r"\b(caput|pars)\b.*$", "", trimmed).strip()
    out.append(trimmed)
    # split compounds — never keep polarity-only fragments
    for part in re.split(r"\s*(?:/| en )\s*", phrase):
        part = part.strip(" .")
        out.append(part)
        part2 = re.sub(
            r"\b(r\.?\s*)?(superficialis|profundus)\b.*$",
            "",
            part,
        ).strip()
        out.append(part2)
    seen = set()
    uniq = []
    for p in out:
        if not _usable_phrase(p):
            continue
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq or ([phrase] if _usable_phrase(phrase) else [])


def legend_matches(term: str, plate: dict) -> bool:
    phrases = term_phrases(term)
    if not phrases or len(phrases[0]) < 4:
        return False

    lines = plate_lines(plate)
    hits = [ln for ln in lines if typed_line_ok(term, ln)]
    if not hits:
        return False

    n = norm(term)
    phrase = phrases[0]
    hay = " | ".join(hits)

    # Reject opposite polarity when phrase includes one qualifier
    for a, b in (
        ("anterior", "posterior"),
        ("posterior", "anterior"),
        ("superior", "inferior"),
        ("inferior", "superior"),
        ("medialis", "lateralis"),
        ("lateralis", "medialis"),
        ("longus", "brevis"),
        ("brevis", "longus"),
        ("major", "minor"),
        ("minor", "major"),
    ):
        if a in phrase and b in phrase:
            continue
        if a in phrase:
            head = phrase.replace(a, "").strip()
            if head and re.search(rf"\b{re.escape(head)}\s+{b}\b", hay) and not re.search(
                rf"\b{re.escape(head)}\s+{a}\b", hay
            ):
                return False

    # Extra nerve English names
    if n.startswith("n.") or n.startswith("r."):
        eng = {
            "radialis": "radial nerve",
            "ulnaris": "ulnar nerve",
            "tibialis": "tibial nerve",
            "medianus": "median nerve",
            "ischiadicus": "sciatic nerve",
            "femoralis": "femoral nerve",
            "axillaris": "axillary nerve",
            "musculocutaneus": "musculocutaneous nerve",
        }
        for lat, en in eng.items():
            if lat in phrase and any(en in ln for ln in hits):
                return True
        # already have typed hits
    return True


def download(url: str, dest: Path) -> bool:
    if dest.exists() and dest.stat().st_size > 2000:
        return True
    for u in (url, url.replace("/large/", "/medium/")):
        try:
            req = urllib.request.Request(u, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=90) as r:
                data = r.read()
            if len(data) < 2000:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            return True
        except Exception as e:
            print("  dl fail", e)
            time.sleep(2)
    return False


def rematch_and_download(catalog: dict) -> dict:
    rows = json.loads(ROWS.read_text(encoding="utf-8"))
    terms = sorted({t.replace("**", "").strip() for r in rows for t in r["terms"]}, key=str.lower)

    # Precompute searchable lines once
    for plate in catalog.values():
        plate.pop("_lines", None)
        plate_lines(plate)

    matches = {}
    for term in terms:
        phrases = term_phrases(term)
        phrase = phrases[0]
        # cheap prefilter tokens from phrase + English aliases
        needles: list[str] = []
        for ph in phrases:
            needles.extend(t for t in re.findall(r"[a-z]{4,}", ph))
        for lat in _ALIAS_KEYS:
            if any(lat in ph or ph in lat for ph in phrases):
                for en in ENGLISH_ALIASES[lat]:
                    needles.extend(re.findall(r"[a-z]{4,}", en))
        needles = list(dict.fromkeys(needles))
        hits = []
        for bn, plate in catalog.items():
            lines = plate.get("_lines") or []
            if needles and not any(any(n in ln for n in needles) for ln in lines):
                continue
            if legend_matches(term, plate):
                hits.append({
                    "bn": bn,
                    "title": plate.get("title"),
                    "page": plate.get("page") or f"https://lane.stanford.edu/biomed-resources/bassett/bassettView.html?bn={bn}",
                    "photo": plate.get("photo"),
                    "region": plate.get("region"),
                    "labels_sample": [
                        (x.get("text") if isinstance(x, dict) else x)
                        for x in (plate.get("labels") or [])[:8]
                    ],
                })
        if hits:
            def region_rank(bn: str) -> int:
                reg = (catalog[bn].get("region") or "").lower()
                title = (catalog[bn].get("title") or "").lower()
                blob = reg + " " + title
                # Prefer limb / back plates for checklist; demote head/eye/abdomen noise
                if any(x in blob for x in ("retina", "optic", "eye", "orbit", "cochlea", "nasal")):
                    return 9
                if any(x in blob for x in ("extremity", "limb", "hand", "foot", "wrist")):
                    return 0
                if any(x in blob for x in ("shoulder", "axilla", "pectoral", "forearm", "upper arm", "brach")):
                    return 1
                if any(x in blob for x in ("thigh", "leg", "glute", "knee", "hip", "popliteal", "femoral")):
                    return 1
                if any(x in blob for x in ("back", "scapula", "spine", "thoracolumb", "erector")):
                    return 2
                if any(x in blob for x in ("head", "neck", "cervical", "occipital", "auricular")):
                    return 3
                if any(x in blob for x in ("abdomen", "inguinal", "pelvis")):
                    return 4
                return 5

            hits.sort(
                key=lambda h: (
                    region_rank(h["bn"]),
                    len(catalog[h["bn"]].get("labels") or []) or 99,
                    h["bn"],
                )
            )
            matches[norm(term)] = {"term": term, "best": hits[0], "alts": hits[1:4]}

    MATCHES.write_text(json.dumps(matches, ensure_ascii=False, indent=2), encoding="utf-8")
    print("matched terms", len(matches), "/", len(terms), flush=True)

    ASSETS.mkdir(parents=True, exist_ok=True)
    for key, m in matches.items():
        best = m["best"]
        bn = best["bn"]
        plate = catalog.get(bn) or {}
        if plate.get("diagram_local") and (ROOT / plate["diagram_local"]).exists():
            best["local"] = plate["diagram_local"]
            best["imageKind"] = "diagram"
            print("OK", m["term"], "←", bn, "(diagram)", best.get("title"), flush=True)
            continue
        if not best.get("photo"):
            best["local"] = None
            print("FAIL", m["term"], "←", bn, "no photo", flush=True)
            continue
        dest = ASSETS / f"{bn.replace('-', '_')}.jpg"
        existed = dest.exists() and dest.stat().st_size > 2000
        ok = download(best["photo"], dest)
        best["local"] = f"assets/bassett/{dest.name}" if ok else None
        best["imageKind"] = "photo"
        print(("OK" if ok else "FAIL"), m["term"], "←", bn, best.get("title"), flush=True)
        if ok and not existed:
            time.sleep(0.25)
    MATCHES.write_text(json.dumps(matches, ensure_ascii=False, indent=2), encoding="utf-8")
    return matches


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--rematch-only", action="store_true", help="Skip plate fetch; rematch + download from catalog")
    args = ap.parse_args()

    catalog = {}
    if CATALOG.exists():
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))

    if not args.rematch_only:
        index = json.loads(INDEX.read_text(encoding="utf-8"))
        bns = sorted(index.keys(), key=lambda x: [int(p) for p in x.split("-")])
        print(f"Fetching {len(bns)} Bassett plates…", flush=True)
        for i, bn in enumerate(bns, 1):
            if bn in catalog and catalog[bn].get("labels"):
                continue
            print(f"[{i}/{len(bns)}] {bn}", flush=True)
            try:
                plate = parse_plate(bn, index[bn])
            except Exception as e:
                print("  err", e)
                time.sleep(3)
                continue
            if not plate:
                print("  no photo")
                continue
            # preserve any previously enriched diagram fields
            prev = catalog.get(bn) or {}
            for k in ("diagram", "diagram_local"):
                if prev.get(k) and not plate.get(k):
                    plate[k] = prev[k]
            catalog[bn] = plate
            if i % 10 == 0:
                CATALOG.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
            time.sleep(0.7)
        CATALOG.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
        print("catalog", len(catalog))

    rematch_and_download(catalog)


if __name__ == "__main__":
    main()
