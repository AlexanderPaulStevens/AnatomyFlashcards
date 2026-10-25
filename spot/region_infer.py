"""
Infer body region from page title, label answers, and the red box on the
silhouette figure in the top-left of dissection photos.
"""
from __future__ import annotations

import re
from pathlib import Path

from PIL import Image

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None


def region_bucket(title: str) -> str:
    t = (title or "").lower()
    if any(k in t for k in ("pedis", "voet", "enkel", "plantaris", "dorsum pedis", "aponeurose")):
        return "Voet / enkel"
    if any(k in t for k in ("cruris", "onderbeen", "perone", "evertor", "extensoren van het onderbeen", "kuit", "surae")):
        return "Onderbeen"
    if any(k in t for k in ("poplit", "femoris", "adductor", "quadriceps", "femoral", "bovenbeen", "bb ")):
        return "Bovenbeen"
    if any(k in t for k in ("glute", "piriform", "heup", "clunium", "ischiad", "sacrotuber")):
        return "Heup / gluteaal"
    if any(k in t for k in ("rug", "occipital", "capitis", "autochtone", "spin", "trapezius", "splenius", "semispinalis", "rhomboide")):
        return "Rug / nek"
    if any(k in t for k in ("manus", "hand", "vinger", "handpalm", "dorsum manus", "palmaris")):
        return "Hand"
    if any(k in t for k in ("voorarm", "onderarm", "cubiti", "extensor compartiment van de voorarm", "flexor compartiment van de voorarm", "antebrachi")):
        return "Voorarm"
    if any(k in t for k in ("bovenarm", "brachialis", "flexor compartiment van de bovenarm", "extensor compartiment van de bovenarm", "brachii")):
        return "Bovenarm"
    if any(k in t for k in ("plexus", "axilla", "schouder", "grenzen", "deltopectoraal", "pectoralis", "thoraco")):
        return "Schouder / plexus"
    if "cutane" in t:
        return "Cutaan"
    if "incisie" in t:
        return "Incisies"
    return "Overig"


# (region, keyword patterns) — scored by hits across answers
_LABEL_RULES: list[tuple[str, tuple[str, ...]]] = [
    (
        "Voet / enkel",
        (
            "plantaris",
            "pedis",
            "hallucis",
            "digiti minimi",
            "aponeurose",
            "binnen enkel",
            "buiten enkel",
            "dorsalis pedis",
            "dorsalis medialis",
            "dorsalis intermedius",
            "abductor hallucis",
            "flexor digitorum brevis",
            "quadratus plantaris",
        ),
    ),
    (
        "Onderbeen",
        (
            "tibialis",
            "peroneus",
            "fibularis",
            "gastrocnemius",
            "soleus",
            "surae",
            "cruris",
            "extensor digitorum longus",
            "extensor hallucis longus",
            "flexor hallucis longus",
            "flexor digitorum longus",
        ),
    ),
    (
        "Bovenbeen",
        (
            "femoral",
            "femoris",
            "vastus",
            "sartorius",
            "gracilis",
            "adductor",
            "quadriceps",
            "poplit",
            "saphena magna",
            "saphenus",
            "patella",
            "circumflexa femoris",
            "pudendae externae",
            "epigastrica superficialis",
            "circumflexa ilium",
        ),
    ),
    (
        "Heup / gluteaal",
        (
            "gluteus",
            "piriform",
            "trochanter",
            "tuber ischiadicum",
            "ischiadicus",
            "clunium",
            "sacrotuberale",
            "pudenda interna",
            "pudendus",
        ),
    ),
    (
        "Rug / nek",
        (
            "occipital",
            "semispinalis",
            "splenius",
            "longissimus",
            "trapezius",
            "rhomboideus",
            "levator scapulae",
        ),
    ),
    (
        "Hand",
        (
            "palmaris brevis",
            "aponeurosis palmaris",
            "arcus palmaris",
            "digitales palmares",
            "dorsum manus",
            "interossei",
            "lumbricales",
            "thenar",
            "hypothenar",
        ),
    ),
    (
        "Voorarm",
        (
            "antebrachi",
            "pronator",
            "supinator",
            "brachioradialis",
            "flexor carpi",
            "extensor carpi",
            "radialis profundus",
            "radialis superficialis",
            "flexor digitorum profundus",
            "flexor pollicis longus",
            "pronator quadratus",
        ),
    ),
    (
        "Bovenarm",
        (
            "brachialis",
            "biceps brachii",
            "triceps",
            "brachii",
            "profunda brachii",
            "a. brachialis",
            "vv. brachiales",
            "pees m. biceps",
        ),
    ),
    (
        "Schouder / plexus",
        (
            "axillar",
            "thoracodorsal",
            "thoracoacromial",
            "thoracica lateralis",
            "circumflexa humeri",
            "circumflexa scapulae",
            "pectoralis",
            "deltopectoraal",
            "cephalica",
            "supraclavicular",
            "plexus",
        ),
    ),
    (
        "Cutaan",
        (
            "cutaneus",
            "cutanei",
            "saphena",
        ),
    ),
]


def region_from_labels(answers: list[str]) -> str | None:
    """Score anatomical keywords across answers; return best region or None."""
    blob = " | ".join(answers or []).lower()
    if not blob.strip():
        return None
    scores: dict[str, int] = {}
    for region, keys in _LABEL_RULES:
        score = 0
        for k in keys:
            if k in blob:
                score += 1 + blob.count(k)
        if score:
            scores[region] = score
    if not scores:
        return None
    # Prefer more specific regions over Cutaan when tied-ish
    best = max(scores.items(), key=lambda kv: (kv[1], 0 if kv[0] == "Cutaan" else 1))
    if best[1] < 1:
        return None
    return best[0]


def _red_mask(arr) -> "np.ndarray":
    r = arr[:, :, 0].astype(int)
    g = arr[:, :, 1].astype(int)
    b = arr[:, :, 2].astype(int)
    return (r > 150) & (g < 100) & (b < 100) & (r > g + 40) & (r > b + 40)


def region_from_silhouette(image_path: str | Path) -> str | None:
    """
    Map the red highlight on the top-left body silhouette to a region.
    Works for standing (vertical) and lying (horizontal) figures.
    """
    if np is None:
        return None
    path = Path(image_path)
    if not path.exists():
        return None
    try:
        im = Image.open(path).convert("RGB")
    except Exception:
        return None

    w, h = im.size
    # Silhouette lives in the corner; scale crop with image size
    cw = max(120, min(int(w * 0.28), 420))
    ch = max(120, min(int(h * 0.42), 480))
    crop = np.array(im.crop((0, 0, cw, ch)))
    red = _red_mask(crop)
    ys, xs = np.where(red)
    if len(ys) < 10:
        return None

    # Keep densest red cluster (silhouette box), drop sparse tissue noise
    # Bin into a coarse grid and pick the fullest cell's neighborhood
    gy, gx = max(1, ch // 12), max(1, cw // 12)
    bins: dict[tuple[int, int], list[int]] = {}
    for i, (y, x) in enumerate(zip(ys, xs)):
        key = (int(y) // gy, int(x) // gx)
        bins.setdefault(key, []).append(i)
    best_idxs = max(bins.values(), key=len)
    if len(best_idxs) < 8:
        return None
    ys = ys[best_idxs]
    xs = xs[best_idxs]
    y0, y1 = int(ys.min()), int(ys.max())
    x0, x1 = int(xs.min()), int(xs.max())
    box_h, box_w = max(1, y1 - y0), max(1, x1 - x0)

    # Body = bright line-art near the red box
    gray = crop.mean(axis=2)
    white = (gray > 155) & ~red
    # Dilate search around red box
    pad = max(box_h, box_w) * 3
    y_a, y_b = max(0, y0 - pad), min(ch, y1 + pad)
    x_a, x_b = max(0, x0 - pad), min(cw, x1 + pad)
    region_white = white[y_a:y_b, x_a:x_b]
    wy, wx = np.where(region_white)
    if len(wy) < 30:
        # fall back to whole crop whites
        wy, wx = np.where(white)
    if len(wy) < 30:
        body_y0, body_y1, body_x0, body_x1 = 0, ch - 1, 0, cw - 1
    else:
        body_y0, body_y1 = int(wy.min()) + y_a, int(wy.max()) + y_a
        body_x0, body_x1 = int(wx.min()) + x_a, int(wx.max()) + x_a

    body_h = max(1, body_y1 - body_y0)
    body_w = max(1, body_x1 - body_x0)
    lying = body_w > body_h * 1.15

    if lying:
        # Head typically left or right; use relative x of red box center
        t = ((x0 + x1) / 2 - body_x0) / body_w
        # Also use relative height of box (feet/lower leg often narrower distal)
        span = box_w / body_w
    else:
        t = ((y0 + y1) / 2 - body_y0) / body_h
        span = box_h / body_h

    t = float(max(0.0, min(1.0, t)))
    span = float(span)

    # Standing/lying body axis: head(0) → feet(1)
    # Large span covering multiple segments → prefer broader region
    if t < 0.14:
        return "Rug / nek"
    if t < 0.28:
        return "Schouder / plexus" if span < 0.22 else "Bovenarm"
    if t < 0.40:
        return "Bovenarm"
    if t < 0.52:
        return "Voorarm" if span < 0.18 else "Bovenbeen"
    if t < 0.62:
        return "Heup / gluteaal" if t < 0.58 else "Bovenbeen"
    if t < 0.78:
        return "Bovenbeen" if t < 0.70 else "Onderbeen"
    if t < 0.90:
        return "Onderbeen"
    return "Voet / enkel"


_WEAK_TITLES = {
    "pagina",
    "spieren",
    "eerste laag",
    "tweede laag",
    "overige spieren",
    "oppervlakkige structuren",
}


def refine_region(
    title: str,
    answers: list[str] | None = None,
    image_path: str | Path | None = None,
) -> str:
    """
    Prefer a concrete title bucket; if Overig/weak, use labels then silhouette.
    """
    title = title or ""
    base = region_bucket(title)
    if title.lower().strip() in _WEAK_TITLES:
        base = "Overig"
    answers = answers or []
    from_labels = region_from_labels(answers)
    from_sil = region_from_silhouette(image_path) if image_path else None

    if base != "Overig":
        return base
    if from_labels:
        return from_labels
    if from_sil:
        return from_sil
    return "Overig"
