#!/usr/bin/env python3
"""Sammenlign L-formens lag ved samme fysiske posisjon rundt hjorne.
Leser de *_analyse.csv som Post_process_lesbar.py lager.
Krever matplotlib. Originalfiler endres ikke.
"""
from pathlib import Path
from bisect import bisect_left
from collections import defaultdict
import csv
import math
import re
from statistics import median

# ========================= ENDRBARE VERDIER =========================
BASE_DIR = Path(__file__).resolve().parent
INNDATA = BASE_DIR / "Analyse_data"
UTDATA = BASE_DIR / "Analyse_L_sammenligning"

# Felles fysisk hjorne: 0 mm. Positive/negative avstander viser de to L-armene.
VIS_FRA_HJORNE_MM = 25.0
RETNINGSAVSTAND_MM = 8.0       # se 8 mm paa hver side for hjornevinkel
MIN_HJORNEVINKEL = 30.0        # grad; L-hjorne naer 90
HJORNESONE_MM = 8.0
MIN_GYLDIG_FART_MM_S = 0.5
MAKS_GYLDIG_FART_MM_S = 25.0   # kun filter for feilestimat, ikke robotgrense
LAG_PNG = True
VIS_GRAFER = False
# ================================================================


def tall(s):
    try:
        v = float(str(s).replace(",", "."))
        return v if math.isfinite(v) else None
    except (ValueError, TypeError):
        return None


def les_fil(path):
    punkter = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"S_x", "S_y", "Avstand_langs_bane_mm", "Faktisk_hastighet_mm_s"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"Manglende kolonner: {sorted(required - set(reader.fieldnames or []))}")
        for row in reader:
            x, y = tall(row["S_x"]), tall(row["S_y"])
            s = tall(row["Avstand_langs_bane_mm"])
            if None in (x, y, s):
                continue
            punkter.append({
                "x": x, "y": y, "s": s,
                "v": tall(row.get("Faktisk_hastighet_mm_s")),
                "wfs": tall(row.get("S_wfs")),
                "i": tall(row.get("S_i")),
                "u": tall(row.get("S_v")),
                "vol": tall(row.get("Tradvolum_per_mm_mm3_mm")),
                "energi": tall(row.get("Elektrisk_energi_J_mm")),
            })
    punkter.sort(key=lambda p: p["s"])
    return punkter


def finn_hjorne(punkter):
    s = [p["s"] for p in punkter]
    best = None
    for j in range(1, len(punkter) - 1):
        left = bisect_left(s, s[j] - RETNINGSAVSTAND_MM)
        right = bisect_left(s, s[j] + RETNINGSAVSTAND_MM)
        if left == 0 and s[j] - s[0] < RETNINGSAVSTAND_MM:
            continue
        if right >= len(punkter):
            continue
        a, b, c = punkter[left], punkter[j], punkter[right]
        ax, ay = b["x"] - a["x"], b["y"] - a["y"]
        bx, by = c["x"] - b["x"], c["y"] - b["y"]
        len1, len2 = math.hypot(ax, ay), math.hypot(bx, by)
        if min(len1, len2) < 1:
            continue
        dot = max(-1.0, min(1.0, (ax * bx + ay * by) / len1 / len2))
        angle = math.degrees(math.acos(dot))
        if best is None or angle > best[0]:
            best = (angle, j)
    return (best[1], best[0]) if best and best[0] >= MIN_HJORNEVINKEL else (None, None)


def afstand(a, b):
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"])


def lagnummer(path):
    m = re.search(r"Lag_(\d+)", path.name, re.IGNORECASE)
    return int(m.group(1)) if m else None


def skriv_csv(path, rader):
    if not rader:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=list(rader[0].keys()), lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(rader)


def median_sone(punkter, key, predicate):
    nums = [p[key] for p in punkter if predicate(p) and p[key] is not None]
    return median(nums) if nums else None


def main():
    files = sorted(INNDATA.rglob("L_*_analyse.csv"))
    files = [f for f in files if lagnummer(f) is not None]
    if not files:
        print(f"Ingen L-analysefiler funnet i {INNDATA}")
        return
    UTDATA.mkdir(parents=True, exist_ok=True)
    gruppene = defaultdict(list)
    # Grupperer hver L-test separat, selv hvis flere tester finnes
    for fil in files:
        grunnnavn = re.sub(r"_Lag_\d+.*$", "", fil.stem, flags=re.IGNORECASE)
        gruppene[(fil.parent.relative_to(INNDATA), grunnnavn)].append(fil)

    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("Installer matplotlib i samme Python-miljo: python -m pip install matplotlib")
        return

    felter = [
        ("v", "Faktisk robothastighet (mm/s)", "hastighet"),
        ("wfs", "Tradmating S_wfs (m/min)", "tradmating"),
        ("i", "Strom S_i (A)", "strom"),
        ("u", "Spenning S_v (V)", "spenning"),
        ("vol", "Beregnet tradvolum (mm3/mm)", "tradvolum"),
        ("energi", "Beregnet elektrisk energi (J/mm)", "energi"),
    ]

    for (rel, grunnnavn), filgruppe in gruppene.items():
        filgruppe.sort(key=lambda f: lagnummer(f))
        serier, oppsummering = [], []
        start_ref, slutt_ref = None, None
        outdir = UTDATA / rel / grunnnavn
        outdir.mkdir(parents=True, exist_ok=True)

        for fil in filgruppe:
            data = les_fil(fil)
            if len(data) < 10:
                print(f"Hopper over {fil.name}: for faa datapunkter")
                continue
            idx, angle = finn_hjorne(data)
            if idx is None:
                print(f"Hopper over {fil.name}: fant ikke tydelig L-hjorne")
                continue

            # Samme fysiske arm paa samme side av 0 for alle lag.
            if start_ref is None:
                start_ref, slutt_ref = data[0], data[-1]
            samme_retning = (afstand(data[0], start_ref) + afstand(data[-1], slutt_ref)
                              <= afstand(data[0], slutt_ref) + afstand(data[-1], start_ref))
            s_corner = data[idx]["s"]
            for p in data:
                p["pos"] = (p["s"] - s_corner) * (1 if samme_retning else -1)
            farts_filter = lambda p: p["v"] is not None and MIN_GYLDIG_FART_MM_S <= p["v"] <= MAKS_GYLDIG_FART_MM_S
            rett = median_sone(data, "v", lambda p: farts_filter(p) and 12 <= abs(p["pos"]) <= VIS_FRA_HJORNE_MM)
            hjorne = median_sone(data, "v", lambda p: farts_filter(p) and abs(p["pos"]) <= HJORNESONE_MM)
            wfs_rett = median_sone(data, "wfs", lambda p: farts_filter(p) and 12 <= abs(p["pos"]) <= VIS_FRA_HJORNE_MM)
            wfs_hjorne = median_sone(data, "wfs", lambda p: farts_filter(p) and abs(p["pos"]) <= HJORNESONE_MM)
            materialforhold = (wfs_hjorne / hjorne) / (wfs_rett / rett) if all(
                x is not None and x > 0 for x in (wfs_hjorne, hjorne, wfs_rett, rett)) else None
            oppsummering.append({
                "Fil": fil.name, "Lag": lagnummer(fil),
                "Retning": "A" if samme_retning else "B",
                "Hjornevinkel_grader": round(angle, 1),
                "Rett_hastighet_mm_s": round(rett, 3) if rett else "",
                "Hjorne_hastighet_mm_s": round(hjorne, 3) if hjorne else "",
                "Fartsreduksjon_prosent": round(100 * (1 - hjorne / rett), 2) if rett and hjorne else "",
                "Materialokning_prosent": round((materialforhold - 1) * 100, 2) if materialforhold else "",
            })
            serier.append((lagnummer(fil), data, samme_retning))
            print(f"{fil.name}: hjorne ved {s_corner:.1f} mm, "
                  f"retning {'A' if samme_retning else 'B'}, "
                  f"fartsreduksjon {oppsummering[-1]['Fartsreduksjon_prosent']} %")

        if not serier:
            continue
        skriv_csv(outdir / "L_lag_sammenligning.csv", oppsummering)

        for key, ylabel, suffix in felter:
            fig, ax = plt.subplots(figsize=(11, 6))
            for lag, punkter, samme in serier:
                points = [(p["pos"], p[key]) for p in punkter
                          if abs(p["pos"]) <= VIS_FRA_HJORNE_MM and p[key] is not None
                          and (key != "v" or MIN_GYLDIG_FART_MM_S <= p["v"] <= MAKS_GYLDIG_FART_MM_S)
                          and (key not in ("vol", "energi") or
                               (p["v"] is not None and MIN_GYLDIG_FART_MM_S <= p["v"] <= MAKS_GYLDIG_FART_MM_S))]
                points.sort()
                if points:
                    x, y = zip(*points)
                    ax.plot(x, y, linewidth=1.4,
                            label=f"Lag {lag:02d} ({'A' if samme else 'B'})")
            ax.axvspan(-HJORNESONE_MM, HJORNESONE_MM, color="gray", alpha=0.09, label="Hjornesone")
            ax.axvline(0, linestyle="--", linewidth=1, color="black", alpha=0.6)
            ax.set(xlabel="Fysisk avstand fra L-hjornet (mm); to forskjellige armer",
                   ylabel=ylabel, title=f"{grunnnavn}: {ylabel} per lag")
            ax.grid(alpha=0.2)
            ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=8)
            fig.tight_layout()
            if LAG_PNG:
                outpng = outdir / f"L_alle_lag_{suffix}.png"
                fig.savefig(outpng, dpi=200, bbox_inches="tight")
            if VIS_GRAFER:
                plt.show()
            plt.close(fig)

        # Retning A og B eksplisitt (kun fartsprofil), for aa se retningsforskjeller
        fig, axes = plt.subplots(2, 1, figsize=(10, 9), sharex=True)
        for lag, data, samme in serier:
            ax = axes[0 if samme else 1]
            points = sorted((p["pos"], p["v"]) for p in data
                            if abs(p["pos"]) <= VIS_FRA_HJORNE_MM
                            and p["v"] is not None and MIN_GYLDIG_FART_MM_S <= p["v"] <= MAKS_GYLDIG_FART_MM_S)
            if points:
                x, y = zip(*points)
                ax.plot(x, y, label=f"Lag {lag:02d}")
        for ax, name in zip(axes, ("Retning A", "Retning B")):
            ax.axvline(0, linestyle="--", color="black", alpha=0.5)
            ax.axvspan(-HJORNESONE_MM, HJORNESONE_MM, color="gray", alpha=0.09)
            ax.set(ylabel="Faktisk hastighet (mm/s)", title=name)
            ax.grid(alpha=0.2)
            ax.legend(fontsize=8, ncol=4)
        axes[-1].set_xlabel("Fysisk avstand fra L-hjornet (mm)")
        fig.suptitle(f"{grunnnavn}: L-lag etter retning")
        fig.tight_layout()
        if LAG_PNG:
            fig.savefig(outdir / "L_hastighet_per_retning.png", dpi=200, bbox_inches="tight")
        if VIS_GRAFER:
            plt.show()
        plt.close(fig)
        print(f"Lagret figurer og oversikt i: {outdir}\n")


if __name__ == "__main__":
    main()
