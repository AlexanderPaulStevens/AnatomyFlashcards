"""Re-fetch Bassett legends + numbered diagrams for matched plates."""
from __future__ import annotations

import json
import re
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
UA = "AnatoViewer/1.0 (KU Leuven anatomy study; educational; CC BY-SA attribution)"
MATCHES = ROOT / "_ocr" / "bassett_matches.json"
CATALOG = ROOT / "_ocr" / "bassett_catalog.json"
ASSETS = ROOT / "assets" / "bassett"


def get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def parse_legend(html: str) -> list[dict]:
    ols = re.findall(r"<ol[^>]*>(.*?)</ol>", html, re.I | re.S)
    for ol in ols:
        items = re.findall(r"<li[^>]*>(.*?)</li>", ol, re.I | re.S)
        if not items or len(items) > 40:
            continue
        labels = []
        for i, it in enumerate(items, 1):
            t = re.sub(r"<[^>]+>", " ", it)
            t = re.sub(r"\s+", " ", t).strip()
            if t:
                labels.append({"n": i, "text": t})
        if labels:
            return labels
    return []


def find_label(term: str, labels: list[dict]) -> dict | None:
    phrase = term.lower().replace("**", "").strip()
    for pref in ("m. ", "n. ", "a. ", "v. ", "r. ", "mm. ", "nn. ", "aa. ", "vv. ", "rr. "):
        if phrase.startswith(pref):
            phrase = phrase[len(pref) :]
            break
    phrase = re.sub(r"\([^)]*\)", "", phrase)
    phrase = re.sub(r"\s*(/| en ).*$", "", phrase).strip()
    toks = re.findall(r"[a-z]{3,}", phrase)
    if not toks:
        return None
    pat = r"\b" + r"\s+".join(map(re.escape, toks)) + r"\b"
    for lab in labels:
        if re.search(pat, lab["text"].lower()):
            return lab
    return None


def download(url: str, dest: Path) -> bool:
    if dest.exists() and dest.stat().st_size > 2000:
        return True
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=90) as r:
            data = r.read()
        if len(data) < 2000:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return True
    except Exception as e:
        print("  dl fail", e)
        return False


def enrich_plate(bn: str, catalog: dict, *, want_diagram: bool) -> None:
    html = get(f"https://lane.stanford.edu/biomed-resources/bassett/bassettView.html?bn={bn}")
    labels = parse_legend(html)
    # Also accept numbered "1. Label" lines outside <ol> (some Bassett pages)
    if not labels:
        text = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
        text = re.sub(r"</li>", "\n", text, flags=re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        found = []
        for line in text.splitlines():
            line = line.strip()
            m = re.match(r"^(\d{1,3})\.\s+(.+)$", line)
            if not m:
                continue
            lab = m.group(2).strip()
            if 4 <= len(lab) <= 180 and not lab.lower().startswith("creative commons"):
                found.append({"n": int(m.group(1)), "text": lab})
        labels = found

    imgs = re.findall(r"(//lane\.stanford\.edu/elane/public/[^\"']+\.[LDT]\.jpg)", html, re.I)
    photo = draw = None
    for u in imgs:
        uu = ("https:" + u).replace("/medium/", "/large/")
        up = u.upper()
        if up.endswith(".L.JPG"):
            photo = uu
        elif up.endswith(".D.JPG"):
            draw = uu
    plate = catalog.setdefault(bn, {})
    plate["labels"] = labels
    plate["label_blob"] = " | ".join(f"{l['n']}. {l['text']}" for l in labels).lower()
    if photo:
        plate["photo"] = photo
    if draw:
        plate["diagram"] = draw
        if want_diagram:
            dest = ASSETS / f"{bn.replace('-', '_')}_D.jpg"
            if download(draw, dest):
                plate["diagram_local"] = f"assets/bassett/{dest.name}"


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--all-empty", action="store_true", help="Refetch legends for every plate missing labels")
    args = ap.parse_args()

    matches = json.loads(MATCHES.read_text(encoding="utf-8")) if MATCHES.exists() else {}
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))

    if args.all_empty:
        bns = sorted(bn for bn, p in catalog.items() if not p.get("labels"))
        print(f"refill empty legends: {len(bns)} plates", flush=True)
        for i, bn in enumerate(bns, 1):
            print(f"[{i}/{len(bns)}] {bn}", flush=True)
            try:
                enrich_plate(bn, catalog, want_diagram=False)
            except Exception as e:
                print("  err", e)
            if i % 15 == 0:
                CATALOG.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
            time.sleep(0.55)
        CATALOG.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
        print("catalog labels filled:", sum(1 for p in catalog.values() if p.get("labels")), "/", len(catalog))
        return

    bns = sorted({m["best"]["bn"] for m in matches.values()})
    print(f"enrich {len(bns)} matched plates", flush=True)

    for i, bn in enumerate(bns, 1):
        print(f"[{i}/{len(bns)}] {bn}", flush=True)
        try:
            enrich_plate(bn, catalog, want_diagram=True)
        except Exception as e:
            print("  err", e)
        time.sleep(0.55)

    for key, m in matches.items():
        best = m["best"]
        bn = best["bn"]
        plate = catalog[bn]
        lab = find_label(m["term"], plate.get("labels") or [])
        best["legend"] = lab
        if plate.get("diagram_local"):
            best["local"] = plate["diagram_local"]
            best["imageKind"] = "diagram"
        else:
            best["imageKind"] = "photo"
        print(m["term"], "=>", lab, "|", best.get("local"))

    CATALOG.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    MATCHES.write_text(json.dumps(matches, ensure_ascii=False, indent=2), encoding="utf-8")
    print("done")


if __name__ == "__main__":
    main()
