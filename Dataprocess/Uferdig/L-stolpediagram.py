#!/usr/bin/env python3
"""L-hjørne: prosentvis endring per lag i egne lagrede stolpediagram.
Leser *_analyse.csv fra Post_process_lesbar.py. Endrer ikke inputfilene.
"""
from pathlib import Path
from collections import defaultdict
from statistics import median
from bisect import bisect_left
import csv
import math
import re

# =================== ENDRBARE VERDIER ===================
BASE_DIR = Path(__file__).resolve().parent
INNDATA = BASE_DIR / "Analyse_data"  # Søker også i alle undermapper
UTDATA = BASE_DIR / "Analyse_L_stolper"

HJORNESONE_MM = 8.0             # +/- 8 mm fra identifisert hjørne
RETT_FRA_MM = 12.0              # Rett referansesone: 12–25 mm fra hjørnet
RETT_TIL_MM = 25.0
RETNINGSAVSTAND_MM = 8.0       # Vinkel vurderes 8 mm på hver side
MIN_HJORNEVINKEL_GRADER = 30
MIN_FART_MM_S = 0.5            # Utelukk stopp / ugyldige fartsverdier
MAKS_FART_MM_S = 25.0          # Filter mot numeriske avvik, ikke robotgrense
MIN_PUNKTER_PER_SONE = 2
LAG_PNG = True
VIS_GRAFER = False
# ========================================================

FELTER = {
    "Fartsreduksjon_pct": ("L – fartsreduksjon i hjørnet", "L_fartsreduksjon.png"),
    "Tradvolum_endring_pct": ("L – endring i trådvolum per mm", "L_tradvolum.png"),
    "Tradmating_endring_pct": ("L – endring i trådmating", "L_tradmating.png"),
    "Strom_endring_pct": ("L – endring i strøm", "L_strom.png"),
    "Spenning_endring_pct": ("L – endring i spenning", "L_spenning.png"),
    "Energi_endring_pct": ("L – endring i elektrisk energi per mm", "L_energi.png"),
}


def tall(v):
    try:
        f = float(str(v).strip().replace(",", "."))
        return f if math.isfinite(f) else None
    except (ValueError, TypeError):
        return None


def lagnummer(fil):
    m = re.search(r"_Lag_(\d+)", fil.name, re.I)
    return int(m.group(1)) if m else None


def les_fil(path):
    punkter = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        krevd = {"S_x", "S_y", "Avstand_langs_bane_mm", "Faktisk_hastighet_mm_s"}
        mangler = krevd - set(reader.fieldnames or [])
        if mangler:
            raise ValueError("Mangler kolonner: " + ", ".join(sorted(mangler)))
        for row in reader:
            x, y, s = (tall(row.get(k)) for k in ("S_x", "S_y", "Avstand_langs_bane_mm"))
            if None in (x, y, s):
                continue
            punkter.append({
                "x": x, "y": y, "s": s,
                "fart": tall(row.get("Faktisk_hastighet_mm_s")),
                "volum": tall(row.get("Tradvolum_per_mm_mm3_mm")),
                "wfs": tall(row.get("S_wfs")),
                "strom": tall(row.get("S_i")),
                "spenning": tall(row.get("S_v")),
                "energi": tall(row.get("Elektrisk_energi_J_mm")),
            })
    punkter.sort(key=lambda p: p["s"])
    return punkter


def finn_hjorne(p):
    """Finn sterkeste retningsendring, samme metode som Sammenlign_L_lag.py."""
    s = [a["s"] for a in p]
    best = None
    for j in range(1, len(p) - 1):
        left = bisect_left(s, s[j] - RETNINGSAVSTAND_MM)
        right = bisect_left(s, s[j] + RETNINGSAVSTAND_MM)
        if left == 0 and s[j] - s[0] < RETNINGSAVSTAND_MM:
            continue
        if right >= len(p):
            continue
        a, b, c = p[left], p[j], p[right]
        ux, uy = b["x"] - a["x"], b["y"] - a["y"]
        vx, vy = c["x"] - b["x"], c["y"] - b["y"]
        nu, nv = math.hypot(ux, uy), math.hypot(vx, vy)
        if min(nu, nv) < 1:
            continue
        co = max(-1, min(1, (ux*vx + uy*vy) / (nu*nv)))
        angle = math.degrees(math.acos(co))