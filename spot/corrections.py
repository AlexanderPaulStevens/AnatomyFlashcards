"""
Hand-checked anatomical label corrections for OCR output.
Applied by apply_corrections.py onto data.json / data.js.
"""

# Exact OCR string → corrected display name (after polish)
TEXT_FIX = {
    # vessels / nerves
    "A. en Vthoracodorsalis": "A. en V. thoracodorsalis",
    "A.circumflexahumeri posterior": "A. circumflexa humeri posterior",
    "A. circumflexascapulae": "A. circumflexa scapulae",
    "A. femoralisprofunda": "A. femoralis profunda",
    "A. en v. femoralis": "A. en V. femoralis",
    "Vmediana cubiti": "V. mediana cubiti",
    "V. circumflexa ilium": "V. circumflexa ilium superficialis",
    "N. cutaneussurae": "N. cutaneus surae",
    "N. cutaneusbrachi medialis": "N. cutaneus brachii medialis",
    "N. cutaneusantebrachi lateralis": "N. cutaneus antebrachii lateralis",
    "N. cutaneusantebrachi medialis": "N. cutaneus antebrachii medialis",
    "N. cutaneus antebrachi lateralis": "N. cutaneus antebrachii lateralis",
    "N. cutaneus antebrachi medialis": "N. cutaneus antebrachii medialis",
    "N. cutaneus ante brachii posterior": "N. cutaneus antebrachii posterior",
    "N:occipitalistertius": "N. occipitalis tertius",
    "Nn clunium medi": "Nn. clunium medii",
    "Nn. cluniuminferiores": "Nn. clunium inferiores",
    "Nn. cluniumsuperiores": "Nn. clunium superiores",
    "Rr. cutaneus anteriores": "Rr. cutanei anteriores",
    "n. femoralis": "N. femoralis",
    "N. femoris": "N. femoralis",
    "medianus": "N. medianus",
    "uinanis": "N. ulnaris",
    "ulnaris": "N. ulnaris",
    "M. rectus capitis postenor major": "M. rectus capitis posterior major",
    "M. rectus capitis posternior minor": "M. rectus capitis posterior minor",
    "M. obliquus capitisinferior": "M. obliquus capitis inferior",
    "semispinalis capitis": "M. semispinalis capitis",
    "M, longissimus cervicis": "M. longissimus cervicis",
    "M: splenius capitis": "M. splenius capitis",
    "M,extensorpollicis longus": "M. extensor pollicis longus",
    "N. digitalis plantaris propriusvan V": "N. digitalis plantaris proprius van V",
    "N. digitalis plantaris propriusvan I": "N. digitalis plantaris proprius van I",
    # muscles often glued
    "M. bicepsbrachicaput brevis": "M. biceps brachii caput breve",
    "M. bicepsbrachili caputlongum": "M. biceps brachii caput longum",
    "M. abductorpollicis longus": "M. abductor pollicis longus",
    "M. extensorpollicis longus": "M. extensor pollicis longus",
    "M. extensordigitorum": "M. extensor digitorum",
    "M. extensorindices": "M. extensor indicis",
    "M,extensorpollicis longus": "M. extensor pollicis longus",
    "M. flexor carpiradialis": "M. flexor carpi radialis",
    "M. flexor carpiulnaris": "M. flexor carpi ulnaris",
    "M. flexordigitorum": "M. flexor digitorum",
    "M. pronatorquadratus": "M. pronator quadratus",
    "M, longissimus": "M. longissimus",
    "M: semispinalis": "M. semispinalis",
    "M: splenius capitis": "M. splenius capitis",
    "Musculustensor": "M. tensor fasciae latae",
    "fasciaelatae": "M. tensor fasciae latae",
    "Ligamentumsacrotuberale": "Ligamentum sacrotuberale",
    "Tuberischiadicum": "Tuber ischiadicum",
    "Aponeurosispalmaris": "Aponeurosis palmaris",
    "Arcuspalmaris superficialis": "Arcus palmaris superficialis",
    "Arcusvenosus": "Arcus venosus dorsalis pedis",
    "dorsalis pedis": "Arcus venosus dorsalis pedis",
    "Aa. digitalespalmarescommunes": "Aa. digitales palmares communes",
    "Aa. digitalespalmarescommunes Il-IV": "Aa. digitales palmares communes II–IV",
    "Nn. digitalespalmarespropriae": "Nn. digitales palmares propriae",
    "Binnenenkel": "Binnen enkel",
    "Musculus pectoralis major": "M. pectoralis major",
}

# Drop these as standalone quiz answers (fragments / junk)
DROP = {
    "superficialis",
    "profundus",
    "intermedius",
    "medius",
    "Membrana",
    "vasto-adductoria",
    "semispinalis",
    "capitis superior",
    "capitisinferior",
    "postenor major",
    "posternior minor",
    "hallucis longus",
    "digitorum longus",
    "digitorumlangus",
    "digiti minimi",
    "Eindpeesm,flexo",
    "Eindpezenmflexor",
    "propriusvan V",
    "propriusvan I",
    "biceps femoris",  # incomplete without Insertio m. …
    "femoris lateralis",
    "femoris medialis",
    "femoris posterior",
    "N. cutaneus",  # incomplete halves
    # Parenthetical under Fasciculus lateralis (OCR fragment)
    "fasciculus medialis)",
    # Watermark / logo OCR
    "JORO ROOSEN",
    "JORG ROOSEN",
    "JOR G ROOSEN",
    "ROOSEN",
    "JOR G",
}

# Per-plate full corrected label lists (order matches current OCR labels left→right / as stored).
# When length differs, apply_corrections merges/drops using MATCH rules below.
PLATE_ANSWERS = {
    "p01_i0": [
        "M. coracobrachialis",
        "M. biceps brachii caput breve",
        "M. biceps brachii caput longum",
        "N. medianus",
        "N. ulnaris",
    ],
    "p01_i1": [
        "Fasciculus lateralis",
        "N. musculocutaneus",
        "N. medianus",
        "N. ulnaris",
        "N. cutaneus brachii medialis",
        "Fasciculus medialis",
    ],
    "p02_i0": [
        "A. en V. thoracica lateralis",
        "N. axillaris",
        "A. thoracoacromialis",
        "A. circumflexa humeri posterior",
        "A. circumflexa scapulae",
        "N. thoracodorsalis",
        "A. en V. thoracodorsalis",
    ],
    "p03_i0": [
        "M. quadratus plantaris",
        "Eindpees m. flexor hallucis longus",
        "Eindpezen m. flexor digitorum longus",
    ],
    "p04_i0": [
        "M. abductor digiti minimi",
        "M. flexor digitorum brevis",
        "M. abductor hallucis",
        "Aponeurose",
    ],
    "p07_i1": [
        "N. digitalis plantaris proprius van V",
        "N. digitalis plantaris proprius van I",
    ],
    "p11_i2": [
        "V. saphena parva",
        "N. cutaneus surae medialis",
    ],
    "p13_i1": [
        "A. poplitea",
        "V. poplitea",
    ],
    "p14_i1": [
        "M. semitendinosus",
        "N. cutaneus femoris posterior",
        "V. saphena parva",
        "M. biceps femoris",
    ],
    "p16_i0": [
        "N. tibialis",
        "N. ischiadicus",
        "N. peroneus communis",
    ],
    "p19_i0": [
        "M. peroneus longus",
        "Insertio m. biceps femoris",
        "N. peroneus communis",
    ],
    "p20_i0": [
        "M. pectineus",
        "M. adductor longus",
        "M. gracilis",
        "M. sartorius",
    ],
    "p21_i1": [
        "M. tibialis anterior",
        "M. extensor hallucis longus",
        "M. peroneus longus",
        "M. extensor digitorum longus",
    ],
    "p22_i0": [
        "Arcus venosus dorsalis pedis",
        "N. cutaneus dorsalis medialis",
        "N. peroneus superficialis",
        "N. cutaneus dorsalis intermedius",
    ],
    "p23_i0": [
        "M. vastus medialis",
        "Membrana vastoadductoria",
        "N. saphenus",
        "M. sartorius",
        "M. gracilis",
    ],
    "p23_i1": [
        "A. en V. femoralis",
        "Hiatus adductorius",
        "N. saphenus",
    ],
    "p24_i0": [
        "M. vastus medialis",
        "M. sartorius",
        "M. rectus femoris",
        "M. vastus lateralis",
        "M. tensor fasciae latae",
    ],
    "p25_i0": [
        "Ligamentum inguinale",
        "V. femoralis",
        "A. femoralis",
        "N. femoralis",
        "Tuberculum pubicum",
        "M. sartorius",
        "M. adductor longus",
    ],
    "p27_i0": [
        "A. femoralis profunda",
        "A. circumflexa femoris medialis",
        "A. circumflexa femoris lateralis",
    ],
    "p30_i0": [
        "Binnen enkel",
        "V. saphena magna",
    ],
    "p32_i0": [
        "V. circumflexa ilium superficialis",
        "V. epigastrica superficialis",
        "A. femoralis",
        "V. femoralis",
        "Vv. pudendae externae",
        "V. saphena magna",
    ],
    "p32_i1": [
        "Rr. cutanei anteriores n. femoralis",
        "N. cutaneus femoris lateralis",
    ],
    "p33_i1": [
        "Patella",
        "Binnen enkel",
        "N. saphenus",
        "V. saphena magna",
    ],
    "p34_i0": [
        "Arcus venosus dorsalis pedis",
        "N. cutaneus dorsalis medialis",
        "N. peroneus superficialis",
        "N. cutaneus dorsalis intermedius",
    ],
    "p39_i0": [
        "A. en V. pudenda interna",
        "M. piriformis",
        "N. pudendus",
        "Ligamentum sacrotuberale",
        "M. gluteus medius",
    ],
    "p40_i0": [
        "M. piriformis",
        "Tuber ischiadicum",
        "Trochanter major",
    ],
    "p43_i0": [
        "M. gluteus maximus",
        "N. ischiadicus",
        "N. cutaneus femoris posterior",
    ],
    "p44_i0": [
        "Nn. clunium medii",
        "Nn. clunium inferiores",
        "Nn. clunium superiores",
    ],
    "p46_i0": [
        "M. obliquus capitis superior",
        "M. rectus capitis posterior major",
        "M. rectus capitis posterior minor",
        "M. obliquus capitis inferior",
        "M. semispinalis cervicis",
        "M. semispinalis capitis",
        "M. splenius capitis",
    ],
    "p50_i0": [
        "M. semispinalis capitis",
        "M. longissimus cervicis",
    ],
    "p51_i0": [
        "M. splenius capitis",
        "M. infraspinatus",
        "M. teres minor",
        "M. trapezius",
        "M. teres major",
        "M. latissimus dorsi",
    ],
    "p52_i1": [
        "M. splenius capitis",
        "M. levator scapulae",
        "M. rhomboideus minor",
        "M. trapezius",
        "M. rhomboideus major",
    ],
    "p53_i0": [
        "M. semispinalis capitis",
        "M. splenius capitis",
    ],
    "p55_i0": [
        "N. occipitalis major",
        "A. occipitalis",
        "N. occipitalis tertius",
        "N. occipitalis minor",
    ],
    "p58_i0": [
        "R. superficialis n. radialis",
        "M. abductor pollicis longus",
        "M. extensor pollicis brevis",
        "A. radialis",
        "M. extensor pollicis longus",
    ],
    "p59_i0": [
        "Brachioradialisgroep",
        "V. cephalica",
        "M. extensor indicis",
        "Olecranon",
        "M. extensor digitorum",
        "M. extensor pollicis longus",
    ],
    "p60_i0": [
        "N. radialis profundus",
        "N. radialis superficialis",
        "M. supinator",
        "M. brachioradialis",
    ],
    "p61_i0": [
        "M. infraspinatus",
        "M. teres minor",
        "M. deltoideus",
        "M. teres major",
        "M. triceps caput longum",
        "M. triceps caput laterale",
    ],
    "p62_i0": [
        "N. radialis",
        "M. triceps caput mediale",
        "A. profunda brachii",
    ],
    "p63_i0": [
        "N. cutaneus brachii lateralis superior",
        "N. cutaneus antebrachii posterior",
    ],
    "p67_i0": [
        "Aa. digitales palmares communes",
        "M. palmaris brevis",
        "Aponeurosis palmaris",
    ],
    "p67_i1": [
        "Aa. digitales palmares communes II–IV",
        "Nn. digitales palmares propriae",
        "Arcus palmaris superficialis",
        "Aponeurosis palmaris",
    ],
    "p69_i1": [
        "M. flexor carpi radialis",
        "M. brachioradialis",
        "A. radialis",
        "M. palmaris longus",
        "M. flexor carpi ulnaris",
    ],
    "p71_i0": [
        "M. flexor pollicis longus",
        "N. medianus",
        "M. pronator quadratus",
        "M. flexor digitorum profundus",
    ],
    "p72_i1": [
        "N. cutaneus antebrachii lateralis",
        "V. mediana cubiti",
        "N. cutaneus antebrachii medialis",
    ],
    "p73_i0": [
        "Vv. brachiales",
        "N. medianus",
        "A. brachialis",
        "N. radialis",
        "Pees m. biceps brachii",
    ],
    "p74_i0": [
        "M. coracobrachialis",
        "M. biceps brachii caput breve",
        "M. biceps brachii caput longum",
        "N. medianus",
        "N. ulnaris",
        "M. brachialis",
    ],
    "p76_i0": [
        "V. cephalica",
        "N. cutaneus antebrachii lateralis",
        "N. cutaneus antebrachii medialis",
        "V. basilica",
    ],
    # duplicates of earlier plates
    "p79_i0": None,  # copy p01_i0
    "p79_i1": None,
    "p80_i0": None,
    "p82_i0": None,
    "p87_i0": None,
}

# Alias copies
PLATE_ANSWERS["p79_i0"] = PLATE_ANSWERS["p01_i0"]
PLATE_ANSWERS["p79_i1"] = PLATE_ANSWERS["p01_i1"]
PLATE_ANSWERS["p80_i0"] = PLATE_ANSWERS["p02_i0"]
PLATE_ANSWERS["p82_i0"] = PLATE_ANSWERS["p02_i0"]
PLATE_ANSWERS["p87_i0"] = PLATE_ANSWERS["p02_i0"]

# When plate has more OCR fragments than corrected answers, map which OCR indices
# to keep (and merge remaining into previous). Default: take first N coords.
# Special merges: list of OCR-index groups → one label
PLATE_MERGE = {
    # p03: 5 OCR → 3 answers
    "p03_i0": [[0, 1], [1, 2], [3, 4]],  # wait - need careful mapping
    "p04_i0": [[0, 1], [2], [2]],  # problematic
}
