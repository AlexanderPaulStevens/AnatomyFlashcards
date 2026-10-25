"""
Build viewer/data.js from the 11 checklist rows.

Image policy (strict):
  1. Spot course photo with pin highlight (when exact type-safe match)
  2. Verified internet cadaver photo:
       - Stanford Bassett (CC BY-SA; structure named in plate legend)
       - Wikimedia Commons (curated Anatomist90 / clear title)
  3. Michigan BlueLink regional atlas link (educational use; open in browser)
  4. Otherwise: no image (better empty than wrong)

Usage: python viewer/build_data.py
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ROWS_PATH = ROOT / "_ocr" / "rows.json"
SPOT_JS = ROOT.parent / "spot" / "data.js"
ASSETS = ROOT / "assets"
CACHE = ROOT / "_ocr" / "commons_cache.json"
BASSETT_MATCHES = ROOT / "_ocr" / "bassett_matches.json"
BLUELINK = ROOT / "_ocr" / "bluelink_regions.json"
OUT_JS = ROOT / "data.js"

UA = "AnatoViewer/1.0 (KU Leuven anatomy study; educational; contact via GitHub AnatomyFlashcards)"

# Only map when type stays the same (A→A, N→N, …)
# Keys must match norm() output (aa./nn./mm./rr. collapse to a./n./m./r.).
ALIASES = {
    "a. profunda femoris": "a. femoralis profunda",
    "m. triceps": "m. triceps caput longum",
    "m. flexor digiti minimi": "m. flexor digiti minimi brevis",
    "m. quadratus plantae": "m. quadratus plantaris",
    "m. trapezius pars descendens": "m. trapezius",
    "m. trapezius pars ascendens / pars transversa": "m. trapezius",
    "m. rectus capitis posterior major en minor": "m. rectus capitis posterior major",
    "m. obliquus capitis superior en inferior": "m. obliquus capitis superior",
    "a. digitales palmares communes iiiv": "a. digitales palmares communes",
    "m. adductor pollicis caput transversum": "m. adductor pollicis",
    "m. longissimus": "m. longissimus cervicis",
    "a. circumflexa humeri anterior en posterior": "a. circumflexa humeri posterior",
    "r. superficialis n. radialis": "n. radialis superficialis",
    "r. profundus n. radialis": "n. radialis profundus",
    "m. biceps brachii": "m. biceps brachii caput longum",
    "m. teres major / minor": "m. teres major",
    "a. thoracodorsalis": "a. en v. thoracodorsalis",
    "v. thoracodorsalis": "a. en v. thoracodorsalis",
    "a. thoracica lateralis": "a. en v. thoracica lateralis",
    "a. pudenda interna": "a. en v. pudenda interna",
    "r. cutanei anteriores n. intercostalis": "r. cutanei anteriores",
    "r. cutanei laterales n. intercostalis": "r. cutanei laterales",
    "m. fibularis longus / brevis": "m. fibularis longus",
    "n. digitalis plantaris proprius": "n. digitalis plantaris proprius van i",
}

ILLUSTRATION_RE = re.compile(
    r"\b(gray|grey|diagram|drawing|illustration|sketch|cartoon|scheme|"
    r"schematic|vector|svg|painted|painting|lithograph|engraving|"
    r"woodcut|plate\s+\d+|wellcome|horse|equine|3d\s*model|animation|"
    r"bodybuilder|bodybuilding|gym|workout|exercise)\b",
    re.I,
)
PHOTO_HINT_RE = re.compile(
    r"\b(dissection|cadaver|cadaveric|prosection|anatomist90|human\s+body|"
    r"slide\d+|muscles?\s+of|nerve\s+of|artery|vein)\b",
    re.I,
)
MIME_OK = {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/tiff"}


def norm(s: str) -> str:
    s = (s or "").replace("**", "").strip().lower()
    s = s.replace("mm.", "m.").replace("nn.", "n.").replace("aa.", "a.").replace("rr.", "r.")
    s = s.replace("peroneus", "fibularis")
    s = re.sub(r"\([^)]*\)", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"[^a-z0-9./ ]", "", s)
    return s


def structure_type(s: str) -> str | None:
    n = norm(s)
    for p, t in (
        ("nn. ", "n"),
        ("aa. ", "a"),
        ("vv. ", "v"),
        ("rr. ", "r"),
        ("mm. ", "m"),
        ("n. ", "n"),
        ("a. ", "a"),
        ("v. ", "v"),
        ("r. ", "r"),
        ("m. ", "m"),
        ("ligamentum ", "lig"),
        ("fascia ", "fas"),
        ("aponeurosis ", "apo"),
        ("tractus ", "fas"),
        ("retinaculum ", "fas"),
        ("arcus ", "a"),
        ("rete ", "v"),
        ("hiatus ", "fas"),
    ):
        if n.startswith(p):
            return t
    return None


def core_name(s: str) -> str:
    n = norm(s)
    n = re.sub(r"^(mm?|nn?|aa?|vv?|rr?)\. ", "", n)
    n = re.sub(r"^(ligamentum|fascia|aponeurosis|tractus|retinaculum|arcus|rete|hiatus) ", "", n)
    return n.strip()


def variants(s: str) -> set[str]:
    n = norm(s)
    out = {n}
    out.add(n.replace("fibularis", "peroneus"))
    out.add(n.replace("peroneus", "fibularis"))
    # split "en" / "/" compounds
    prefix = ""
    body = n
    for p in ("m. ", "n. ", "a. ", "v. ", "nn. ", "aa. ", "rr. ", "r. ", "vv. ", "mm. "):
        if n.startswith(p):
            prefix = p
            body = n[len(p) :]
            break
    for part in re.split(r"\s*(?:/| en )\s*", body):
        part = part.strip()
        if part:
            out.add(norm(prefix + part))
            out.add(norm(part))
    return {x for x in out if x}


def english_query(term: str) -> str:
    """Latin TA name → Commons-friendly search (keep Latin; add dissection)."""
    c = core_name(term)
    # Drop trailing branch noise for search
    c = re.sub(r"\b(r\.?\s*)?(superficialis|profundus|ascendens|descendens|transversa)\b", "", c)
    c = re.sub(r"\s+", " ", c).strip()
    t = structure_type(term)
    kind = {
        "m": "muscle",
        "n": "nerve",
        "a": "artery",
        "v": "vein",
        "r": "nerve",
        "lig": "ligament",
        "fas": "fascia",
        "apo": "aponeurosis",
    }.get(t or "", "")
    bits = [f'"{c}"' if " " in c else c]
    if kind:
        bits.append(kind)
    bits.append("dissection")
    bits.append("filetype:bitmap")
    return " ".join(bits)


def load_spot():
    text = SPOT_JS.read_text(encoding="utf-8")
    m = re.search(r"window\.SPOT_DATA\s*=\s*(\{.*\})\s*;?\s*$", text, re.S)
    return json.loads(m.group(1))


def build_spot_index(spot):
    by_ans: dict[str, list] = defaultdict(list)
    for q in spot["questions"]:
        for v in variants(q["answer"]):
            by_ans[v].append(q)
        by_ans[norm(q["answer"])].append(q)
    for k, qs in list(by_ans.items()):
        seen = set()
        uniq = []
        for q in qs:
            if q["id"] in seen:
                continue
            seen.add(q["id"])
            uniq.append(q)
        by_ans[k] = uniq
    return by_ans


def types_compatible(term: str, answer: str) -> bool:
    tt, at = structure_type(term), structure_type(answer)
    if tt is None or at is None:
        # allow non-typed pairs only if cores equal
        return core_name(term) == core_name(answer)
    # nerves: n and r both nerves
    if {tt, at} <= {"n", "r"}:
        return True
    # arteries: a
    if tt == at:
        return True
    # "A. en V. x" answers can serve A. or V. of same core
    an = norm(answer)
    if an.startswith("a. en v.") or an.startswith("a. en v "):
        if tt in ("a", "v") and core_name(term) in core_name(answer):
            return True
    return False


def find_spot(term: str, by_ans) -> tuple | None:
    candidates: list[tuple] = []

    def consider(q, score, kind):
        if not types_compatible(term, q["answer"]):
            return
        candidates.append((score, kind, q))

    for v in variants(term):
        if v in ALIASES:
            av = norm(ALIASES[v])
            for q in by_ans.get(av, []):
                consider(q, 95, "alias")
        for q in by_ans.get(v, []):
            consider(q, 100, "exact")

    # core equality with type check
    tc = core_name(term)
    if tc:
        for ans_key, qs in by_ans.items():
            if core_name(ans_key) == tc:
                for q in qs:
                    consider(q, 90, "core")

    if not candidates:
        return None
    candidates.sort(key=lambda x: (-x[0], x[1]))
    score, kind, q = candidates[0]
    if score < 90:
        return None
    return q, score, kind


# Hand-checked Commons cadaver photos: structure name in FILE TITLE + Anatomist90 (or equivalent).
# Opaque Slide*.JPG names are intentionally excluded — not verifiable from metadata alone.
CURATED_COMMONS = {
    "m. gastrocnemius": "File:Gastrocnemius muscle 3.jpg",
    "m. semitendinosus": "File:Semitendinosus muscle.jpg",
    "m. serratus anterior": "File:Serratus anterior muscle.jpg",
    "m. soleus": "File:Soleus muscle.jpg",
    "m. plantaris": "File:Plantaris muscle 2.jpg",
    "m. obturator internus": "File:Obturator internus muscle.jpg",
    "m. quadratus femoris": "File:Quadratus femoris muscle.jpg",
    "m. extensor carpi ulnaris": "File:Extensor carpi ulnaris muscle.jpg",
    "m. extensor indicis": "File:Extensor indicis muscle.jpg",
    "m. infraspinatus": "File:Infraspinatus muscle 1.JPG",
    "m. trapezius": "File:Trapezius muscle.JPG",
    "m. trapezius pars descendens": "File:Trapezius muscle.JPG",
    "m. trapezius pars ascendens / pars transversa": "File:Trapezius muscle.JPG",
    "m. gluteus maximus": "File:Gluteus maximus muscle dissection.jpg",
    "m. gluteus medius": "File:Gluteus medius muscle.jpg",
    "m. teres major": "File:Teres major muscle.JPG",
    "m. teres major / minor": "File:Teres major muscle.JPG",
    "m. teres minor": "File:Teres minor muscle.JPG",
    "m. deltoideus": "File:Deltoid muscle.JPG",
    "m. rhomboideus major": "File:Rhomboideus major muscle.jpg",
    "m. biceps brachii": "File:Biceps brachialis muscle.jpg",
    "m. triceps": "File:Triceps muscle.jpg",
    "m. biceps femoris": "File:Femoral biceps muscle.jpg",
    "m. extensor digitorum": "File:Extensor digitorum muscle.jpg",
    "m. abductor hallucis": "File:Abductor hallucis muscle.jpg",
    "m. lumbricales": "File:Lumbricals muscles.jpg",
    "m. serratus posterior superior": "File:Posterior superior serratus muscle.jpg",
}


def http_get_json(params: dict, retries: int = 5) -> dict:
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({**params, "format": "json"})
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode("utf-8", errors="replace"))
        except Exception as e:
            last = e
            wait = 8 * (attempt + 1)
            if "429" in str(e) or "503" in str(e):
                wait = 25 * (attempt + 1)
            print(f"  http retry {attempt+1}/{retries} wait {wait}s ({e})")
            time.sleep(wait)
    raise last  # type: ignore


def load_cache() -> dict:
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    return {}


def save_cache(cache: dict) -> None:
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def distinctive_tokens(term: str) -> list[str]:
    stop = {
        "longus", "brevis", "major", "minor", "medialis", "lateralis",
        "anterior", "posterior", "superior", "inferior", "communis",
        "superficialis", "profundus", "caput", "pars", "proprius",
        "muscle", "nerve", "artery", "vein",
    }
    tokens = [t for t in re.findall(r"[a-z]{4,}", core_name(term)) if t not in stop]
    if not tokens:
        tokens = [t for t in re.findall(r"[a-z]{5,}", core_name(term))]
    return tokens


def commons_title_ok(term: str, title: str, artist: str, description: str) -> bool:
    """Strict: distinctive tokens must appear in the FILE TITLE (verifiable)."""
    title_l = title.lower()
    blob = f"{title} {description} {artist}".lower()
    if ILLUSTRATION_RE.search(blob):
        return False
    if ILLUSTRATION_RE.search(title_l):
        return False
    tokens = distinctive_tokens(term)
    if not tokens:
        return False
    # All distinctive tokens must be in the title
    if not all(t in title_l for t in tokens):
        return False
    # Must look like a real dissection photo
    if "anatomist90" in blob:
        return True
    if PHOTO_HINT_RE.search(blob) and ("dissection" in blob or "cadaver" in blob or "prosection" in blob):
        return True
    return False


def fetch_file_meta(file_title: str) -> dict | None:
    try:
        data = http_get_json({
            "action": "query",
            "titles": file_title,
            "prop": "imageinfo",
            "iiprop": "url|mime|size|extmetadata|user",
            "iiurlwidth": 1200,
        })
    except Exception as e:
        print("  file meta fail", file_title, e)
        return None
    pages = (data.get("query") or {}).get("pages") or {}
    for page in pages.values():
        if page.get("missing") is not None:
            return None
        infos = page.get("imageinfo") or []
        if not infos:
            return None
        info = infos[0]
        mime = (info.get("mime") or "").lower()
        if mime not in MIME_OK:
            return None
        meta = info.get("extmetadata") or {}
        desc = re.sub(r"<[^>]+>", " ", (meta.get("ImageDescription") or {}).get("value") or "")
        artist = re.sub(r"<[^>]+>", " ", (meta.get("Artist") or {}).get("value") or info.get("user") or "")
        license_ = (meta.get("LicenseShortName") or {}).get("value") or ""
        title = page.get("title") or file_title
        thumb = info.get("thumburl") or info.get("url")
        if not thumb:
            return None
        return {
            "title": title,
            "thumburl": thumb,
            "url": info.get("url"),
            "pageurl": f"https://commons.wikimedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}",
            "mime": mime,
            "artist": artist.strip()[:120],
            "license": license_,
            "description": re.sub(r"\s+", " ", desc)[:240],
            "_score": 10,
        }
    return None


def search_commons(term: str, cache: dict) -> dict | None:
    key = norm(term)

    # 1) curated exact file (highest trust) — always preferred over cache misses
    curated = CURATED_COMMONS.get(key)
    if curated:
        cached = cache.get(key)
        if cached and cached.get("title") == curated:
            return cached
        meta = fetch_file_meta(curated)
        if meta:
            blob = f"{meta.get('title','')} {meta.get('artist','')} {meta.get('description','')}".lower()
            # Curated map is hand-checked; only reject obvious illustrations.
            if not ILLUSTRATION_RE.search(blob):
                cache[key] = meta
                time.sleep(1.2)
                return meta
        print("  curated miss/reject", curated)

    cached = cache.get(key)
    if cached:
        if commons_title_ok(term, cached.get("title", ""), cached.get("artist", ""), cached.get("description", "")):
            return cached
        print("  cache reject", cached.get("title"))
        cache[key] = None

    # No blind search: opaque Slide*.JPG hits are not verifiable enough.
    cache[key] = None
    return None


def existing_asset_for(term: str) -> str | None:
    """Reuse any already-downloaded asset for this term (avoids Commons 429)."""
    ASSETS.mkdir(exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "_", norm(term))[:80].strip("_")
    hits = sorted(ASSETS.glob(f"{slug}_*"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in hits:
        if p.stat().st_size > 1000:
            return p.name
    return None


def download_commons(term: str, meta: dict) -> str | None:
    ASSETS.mkdir(exist_ok=True)
    existing = existing_asset_for(term)
    if existing:
        return existing
    slug = re.sub(r"[^a-z0-9]+", "_", norm(term))[:80].strip("_")
    h = hashlib.sha1((meta["title"] + term).encode()).hexdigest()[:8]
    ext = ".jpg"
    mime = meta.get("mime") or ""
    if "png" in mime:
        ext = ".png"
    elif "webp" in mime:
        ext = ".webp"
    elif "tif" in mime:
        ext = ".jpg"  # still fetch thumb which is jpeg
    dest = ASSETS / f"{slug}_{h}{ext}"
    if dest.exists() and dest.stat().st_size > 1000:
        return dest.name
    url = meta.get("thumburl") or meta.get("url")
    # Prefer Commons thumbnail host to avoid original-file rate limits
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            if len(data) < 800:
                return None
            dest.write_bytes(data)
            return dest.name
        except Exception as e:
            wait = 15 * (attempt + 1)
            print(f"  download retry {attempt+1}/4 wait {wait}s ({e})")
            time.sleep(wait)
    print("  download fail", term)
    return None


def spot_src(q) -> str:
    rel = q.get("imageReveal") or q.get("image") or ""
    return "../spot/" + rel


def main():
    rows = json.loads(ROWS_PATH.read_text(encoding="utf-8"))
    spot = load_spot()
    by_ans = build_spot_index(spot)
    cache = load_cache()
    stats = Counter()

    # Prefer verified Commons over Spot: resolve Commons for every unique term first.
    all_terms = []
    for row in rows:
        for term in row["terms"]:
            all_terms.append(term.replace("**", "").strip())
    unique_terms = sorted({norm(t): t for t in all_terms}.values(), key=str.lower)

    print(f"Resolving Commons for curated/cached terms among {len(unique_terms)}…", flush=True)
    commons_map = {}
    for i, term in enumerate(unique_terms, 1):
        key = norm(term)
        curated = CURATED_COMMONS.get(key)
        cached = cache.get(key)
        if not curated and not cached:
            continue

        # Offline-first: if asset already on disk, skip network
        existing = existing_asset_for(term)
        if existing and (cached or curated):
            title = (cached or {}).get("title") or curated or existing
            commons_map[key] = {
                "image": f"assets/{existing}",
                "credit": (
                    f"Wikimedia Commons · {(cached or {}).get('artist') or 'Anatomist90'} · "
                    f"{(cached or {}).get('license') or ''}"
                ).strip(" ·"),
                "sourceUrl": (cached or {}).get("pageurl") or (
                    f"https://commons.wikimedia.org/wiki/{urllib.parse.quote(str(title).replace(' ', '_'))}"
                    if str(title).startswith("File:") else None
                ),
                "matchedAs": str(title).replace("File:", ""),
                "title": title,
            }
            stats["commons-local"] += 1
            print(f"[{i}] local {term} → {existing}", flush=True)
            continue

        # Network fetches are optional (Commons rate-limits aggressively).
        # Default: skip fetch unless VIEWER_FETCH=1
        if os.environ.get("VIEWER_FETCH") != "1":
            stats["commons-skip-fetch"] += 1
            continue

        print(f"[{i}/{len(unique_terms)}] fetch {term}", flush=True)
        meta = search_commons(term, cache)
        save_cache(cache)
        if not meta:
            stats["commons-miss"] += 1
            continue
        fname = download_commons(term, meta)
        if not fname:
            stats["download-fail"] += 1
            continue
        commons_map[key] = {
            "image": f"assets/{fname}",
            "credit": f"Wikimedia Commons · {meta.get('artist') or 'unknown'} · {meta.get('license') or ''}".strip(" ·"),
            "sourceUrl": meta["pageurl"],
            "matchedAs": meta["title"].replace("File:", ""),
            "title": meta["title"],
        }
        stats["commons"] += 1
        print("  →", meta["title"], flush=True)

    bassett_map = {}
    if BASSETT_MATCHES.exists():
        raw = json.loads(BASSETT_MATCHES.read_text(encoding="utf-8"))
        for key, m in raw.items():
            best = m.get("best") or {}
            local = best.get("local")
            if not local:
                continue
            local_path = ROOT / local
            if not local_path.exists():
                continue
            legend = best.get("legend") or {}
            callout = None
            if legend.get("n") and legend.get("text"):
                callout = f"#{legend['n']} · {legend['text']}"
            elif legend.get("text"):
                callout = legend["text"]
            bassett_map[key] = {
                "image": local,
                "matchedAs": best.get("title") or best.get("bn"),
                "credit": "Stanford Bassett Collection · CC BY-SA 4.0",
                "sourceUrl": best.get("page"),
                "confidence": "bassett",
                "bn": best.get("bn"),
                "imageKind": best.get("imageKind") or "photo",
                "callout": callout,
                "legendNum": legend.get("n"),
            }

    bluelink = {}
    if BLUELINK.exists():
        bluelink = json.loads(BLUELINK.read_text(encoding="utf-8"))
    bl_meta = bluelink.get("_meta") or {}
    bl_by_row = bluelink.get("byRowHint") or {}

    out_rows = []
    for row in rows:
        items = []
        bl_row = bl_by_row.get(row["id"])
        for term in row["terms"]:
            optional = "**" in term
            display = term.replace("**", "").strip()
            key = norm(display)
            cm = commons_map.get(key)
            bm = bassett_map.get(key)
            hit = find_spot(term, by_ans)

            spot_block = None
            if hit:
                q, score, kind = hit
                spot_block = {
                    "image": spot_src(q),
                    "pin": {"x": q["x"], "y": q["y"]},
                    "matchedAs": q["answer"],
                    "credit": "Cursus dissectiefoto (gelabeld)",
                    "confidence": kind,
                    "callout": display,
                }
                stats[f"spot-{kind}"] += 1

            # Prefer Bassett (legend-verified) then Commons for internet photo
            internet_block = None
            if bm:
                internet_block = {
                    "image": bm["image"],
                    "matchedAs": bm["matchedAs"],
                    "credit": bm["credit"],
                    "sourceUrl": bm["sourceUrl"],
                    "confidence": "bassett",
                    "provider": "bassett",
                    "callout": bm.get("callout"),
                    "legendNum": bm.get("legendNum"),
                    "imageKind": bm.get("imageKind"),
                }
                stats["used-bassett"] += 1
            elif cm:
                internet_block = {
                    "image": cm["image"],
                    "matchedAs": cm["matchedAs"],
                    "credit": cm["credit"],
                    "sourceUrl": cm["sourceUrl"],
                    "confidence": "commons",
                    "provider": "commons",
                    "callout": display,
                    "imageKind": "photo",
                }
                stats["used-commons"] += 1

            bluelink_block = None
            if bl_row:
                bluelink_block = {
                    "label": bl_row.get("label"),
                    "url": bl_row.get("url"),
                    "credit": bl_meta.get("credit") or "Michigan BlueLink",
                    "provider": "bluelink",
                }

            if not spot_block and not internet_block:
                stats["missing"] += 1

            items.append({
                "name": display,
                "optional": optional,
                "spot": spot_block,
                "commons": internet_block,  # UI key kept; may be Bassett or Commons
                "internet": internet_block,
                "bluelink": bluelink_block,
                "image": (internet_block or spot_block or {}).get("image"),
                "pin": (spot_block or {}).get("pin"),
                "source": (
                    "both" if spot_block and internet_block else
                    "internet" if internet_block else
                    "spot" if spot_block else
                    "missing"
                ),
                "matchedAs": (spot_block or internet_block or {}).get("matchedAs"),
                "credit": (internet_block or spot_block or {}).get("credit"),
                "sourceUrl": (internet_block or {}).get("sourceUrl"),
            })
        out_rows.append({
            "id": row["id"],
            "side": row["side"],
            "label": row["label"],
            "short": row["short"],
            "bluelink": bl_row,
            "items": items,
        })

    payload = {
        "title": "Anato Viewer",
        "subtitle": "Checklist te disseceren structuren",
        "rows": out_rows,
        "bluelinkMeta": {
            "home": bl_meta.get("home"),
            "credit": bl_meta.get("credit"),
            "terms": bl_meta.get("terms"),
        },
        "policy": (
            "Spot-cursusfoto met markering + geverifieerde internetdissectie "
            "(Bassett CC BY-SA of Commons). BlueLink-atlas per regio als extra naslag."
        ),
    }
    OUT_JS.write_text(
        "window.VIEWER_DATA = " + json.dumps(payload, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8",
    )
    print("stats", dict(stats))
    print("wrote", OUT_JS)


if __name__ == "__main__":
    main()
