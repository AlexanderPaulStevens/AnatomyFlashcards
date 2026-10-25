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

    # legend: numbered lines like "1. Gluteus maximus muscle"
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    text = re.sub(r"</li>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    labels = []
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


def legend_matches(term: str, plate: dict) -> bool:
    blob = plate.get("label_blob") or ""
    title = (plate.get("title") or "").lower()
    hay = blob + " | " + title
    phrase = core_phrase(term)
    if len(phrase) < 4:
        return False

    # Require contiguous core phrase (avoids "adductor … brevis" across a long title)
    if phrase not in hay:
        # allow optional "muscle/nerve/artery/vein" inserted after the Latin name
        toks = [t for t in re.findall(r"[a-z]{3,}", phrase)]
        if len(toks) < 1:
            return False
        pat = r"\b" + r"\s+".join(re.escape(t) for t in toks) + r"\b"
        if not re.search(pat, hay):
            return False

    n = norm(term)
    # Reject opposite polarity qualifiers when phrase itself includes one
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
            # if legend only has the opposite form of the head noun, reject
            # e.g. phrase "serratus anterior" must not match only "serratus posterior"
            head = phrase.replace(a, "").strip()
            if head and re.search(rf"\b{re.escape(head)}\s+{b}\b", hay) and not re.search(
                rf"\b{re.escape(head)}\s+{a}\b", hay
            ):
                return False

    if n.startswith("a."):
        if not re.search(r"\b(artery|arteries|arteria)\b", hay):
            return False
    if n.startswith("n.") or n.startswith("r."):
        # Need an explicit nerve label containing the phrase (not "nerve supply to X muscle")
        nerve_line = False
        for line in hay.split("|"):
            if not re.search(r"\b(nerve|nerves|nervus)\b", line):
                continue
            if "nerve supply to" in line or "nerves and blood" in line:
                continue
            if all(re.search(rf"\b{re.escape(t)}\b", line) for t in re.findall(r"[a-z]{3,}", phrase)):
                nerve_line = True
                break
        if not nerve_line and not re.search(
            rf"\b(radial|ulnar|tibial|median|sciatic|femoral|axillary|musculocutaneous)\s+nerve\b",
            hay,
        ):
            return False
        # Map Latin → English nerve names for common checklist items
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
            if lat in phrase and en in hay:
                return True
        if not nerve_line:
            return False
    if n.startswith("v."):
        if not re.search(r"\b(vein|veins|vena)\b", hay):
            return False
    if n.startswith("aponeurosis") or phrase.startswith("aponeurosis") or "aponeurosis" in n:
        if "aponeurosis" not in hay and "aponeurotic" not in hay:
            return False
    if "arcus" in n and "arcus" not in hay and "arch" not in hay:
        return False
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


def main():
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    catalog = {}
    if CATALOG.exists():
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))

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
        catalog[bn] = plate
        if i % 10 == 0:
            CATALOG.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
        time.sleep(0.7)
    CATALOG.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    print("catalog", len(catalog))

    rows = json.loads(ROWS.read_text(encoding="utf-8"))
    terms = sorted({t.replace("**", "").strip() for r in rows for t in r["terms"]}, key=str.lower)

    matches = {}
    for term in terms:
        hits = []
        for bn, plate in catalog.items():
            if legend_matches(term, plate):
                hits.append({
                    "bn": bn,
                    "title": plate.get("title"),
                    "page": plate["page"],
                    "photo": plate["photo"],
                    "region": plate.get("region"),
                    "labels_sample": plate.get("labels", [])[:8],
                })
        if hits:
            # prefer fewer labels (more focused) then by bn
            hits.sort(key=lambda h: (len(catalog[h["bn"]].get("labels") or []), h["bn"]))
            matches[norm(term)] = {"term": term, "best": hits[0], "alts": hits[1:4]}

    MATCHES.write_text(json.dumps(matches, ensure_ascii=False, indent=2), encoding="utf-8")
    print("matched terms", len(matches), "/", len(terms))

    # download best photos
    ASSETS.mkdir(parents=True, exist_ok=True)
    for key, m in matches.items():
        best = m["best"]
        dest = ASSETS / f"{best['bn'].replace('-', '_')}.jpg"
        ok = download(best["photo"], dest)
        best["local"] = f"assets/bassett/{dest.name}" if ok else None
        print(("OK" if ok else "FAIL"), m["term"], "←", best["bn"], best.get("title"))
        time.sleep(0.5)
    MATCHES.write_text(json.dumps(matches, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
