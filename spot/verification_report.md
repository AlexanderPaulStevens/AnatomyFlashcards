# Spot verification report

Grounding: `python verify_anatomy.py` (full-plate OCR + pin crops + anatomy priors).

## Latest status

- **60 plates**, **241 questions**
- Auto-corrected this session: glued biceps labels (p01/p74/p79), fasciculus lateralis/medialis pin, suboccipital cervicis/capitis split, watermark drops, antebrachii compound repairs, N. femoralis on p25
- Polish bug fixed: no longer splits `thoracodorsalis` / `musculocutaneus` / `antebrachii`

## Remaining flags (review by eye)

| Plate | Flag | Note |
|-------|------|------|
| p11_i2 | antonym pair almost overlapping | surae medialis/lateralis side-by-side — likely OK |
| p44_i0 | empty crop OCR | Nn. clunium medii — tiny/low-contrast text |
| p46_i0 | crop suggests sibling | cervicis pin crop also sees capitis — kept both |
| p61_i0 | empty crop OCR | M. infraspinatus — check pin box |

## How to re-run

```bash
python repair_missed.py   # known OCR fragment repairs
python verify_anatomy.py  # anatomy grounding + auto-fix + report
python verify_anatomy.py --check  # report only
```

See also `verification_report.json` for machine-readable issues.
