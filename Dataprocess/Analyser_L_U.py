#!/usr/bin/env python3
"""Analyse av L-/U-sveiser fra ferdigbehandlede CSV-logger.

Kjor fra Dataprocess. Krever matplotlib for grafer.
"""
import csv
import math
from bisect import bisect_left
from datetime import datetime
from pathlib import Path
from statistics import median

# ======================== ENDRBARE VERDIER ========================
BASE_DIR = Path(__file__).resolve().parent
INNDATA = BASE_DIR / "Behandlet"   # Post_process.py sine resultatfiler
UTDATA = BASE_DIR / "Analyse_L_U"

LAG_GRAFER = True
VINDU_HASTIGHET_PUNKTER = 3    # sentral differanse: i-3 til i+3
RETNINGSAVSTAND_MM = 8.0       # maal retning 8 mm paa hver side
MIN_HJORNEVINKEL_GRADER = 30.0
HJORNESONE_MM = 8.0            # omraade rundt hvert funnet hjorne
MIN_AVSTAND_MELLOM_HJORNER_MM = 15.0
UTELAT_ENDER_MM = 5.0
MIN_BEVEGELSE_MM_S = 0.5
MIN_TRADMATING_M_MIN = 0.1
# Merk: beregnet hastighetsmaal er kun volumbalanse, ikke en
# ferdig anbefalt robotkommando; valider i robot/logg og bead-geometri.
# ================================================================

def fnum(raw):
    try:
        return float(str(raw).replace(",", "."))
    except (TypeError, ValueError):
        return None


def les_data(fil):
    """Hent bare rader med komplette S-posisjoner og S_wfs."""
    out = []
    with fil.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            x, y, z, wfs = (fnum(row.get(k)) for k in ("S_x", "S_y", "S_z", "S_wfs"))
            if any(v is None for v in (x, y, z, wfs)):
                continue
            try:
                t = datetime.fromisoformat((row.get("time") or "").strip())
            except ValueError:
                continue
            out.append(dict(t=t, x=x, y=y, z=z, wfs=wfs,
                            i=fnum(row.get("S_i")), volt=fnum(row.get("S_v"))))
    out.sort(key=lambda q: q["t"])
    # Unnga dt=0; det gir ikke meningsfull estimert hastighet
    unique = []
    for q in out:
        if unique and q["t"] == unique[-1]["t"]:
            continue
        unique.append(q)
    return unique


def length(a, b):
    return math.dist((a["x"], a["y"], a["z"]),
                     (b["x"], b["y"], b["z"]))


def finn_hjorner(samples):
    """Grov deteksjon av retningsendringer i XY-planet."""
    s = [q["s"] for q in samples]
    kandidater = []
    for i in range(1, len(samples) - 1):
        before = bisect_left(s, s[i] - RETNINGSAVSTAND_MM)
        after = bisect_left(s, s[i] + RETNINGSAVSTAND_MM)
        if before == 0 and s[i] - s[0] < RETNINGSAVSTAND_MM:
            continue
        if after >= len(samples):
            continue
        a, b, c = samples[before], samples[i], samples[after]
        v1 = (b["x"] - a["x"], b["y"] - a["y"])
        v2 = (c["x"] - b["x"], c["y"] - b["y"])
        n1, n2 = math.hypot(*v1), math.hypot(*v2)
        if min(n1, n2) < 1:
            continue
        cosv = max(-1, min(1, (v1[0]*v2[0] + v1[1]*v2[1]) / (n1*n2)))
        angle = math.degrees(math.acos(cosv))
        if angle >= MIN_HJORNEVINKEL_GRADER:
            kandidater.append((i, angle))
    # En hel kurve gir mange treff rundt samme hjorne: behold toppen per gruppe
    groups = []
    for item in kandidater:
        if groups and s[item[0]] - s[groups[-1][-1][0]] <= MIN_AVSTAND_MELLOM_HJORNER_MM:
            groups[-1].append(item)
        else:
            groups.append([item])
    return sorted((max(group, key=lambda p: p[1]) for group in groups), key=lambda p: p[0])


def med(values):
    return median(values) if values else None


def fmt(value, digits=2):
    return "" if value is None or not math.isfinite(value) else round(value, digits)


def analyser(fil):
    data = les_data(fil)
    if len(data) < 12:
        print(f"  HOPPER OVER {fil.name}: for faa komplette S-maalinger ({len(data)})")
        return []

    # Avstand langs banen og hastighet beregnet over flere samples
    data[0]["s"] = 0.0
    for i in range(1, len(data)):
        data[i]["s"] = data[i-1]["s"] + length(data[i-1], data[i])

    n = len(data)
    for i, q in enumerate(data):
        left = max(0, i - VINDU_HASTIGHET_PUNKTER)
        right = min(n-1, i + VINDU_HASTIGHET_PUNKTER)
        dt = (data[right]["t"] - data[left]["t"]).total_seconds()
        # netto posisjonsforskyvning er egnet paa rette partier; rundt
        # skarpe hjorner bruker vi isteden faktisk forflyttet banelengde.
        ds = data[right]["s"] - data[left]["s"]
        q["speed"] = ds / dt if dt > 0 else None
        q["valid"] = (q["speed"] is not None and q["speed"] >= MIN_BEVEGELSE_MM_S
                      and q["wfs"] >= MIN_TRADMATING_M_MIN)

    corners = finn_hjorner(data)
    if not corners:
        print(f"  ADVARSEL {fil.name}: ingen tydelige hjorner funnet")

    corner_s = [data[i]["s"] for i, _ in corners]
    total_len = data[-1]["s"]
    # Kun stabile, sveiste partier, uten ender eller identifiserte hjorner
    straight = [q for q in data if q["valid"]
                and UTELAT_ENDER_MM <= q["s"] <= total_len-UTELAT_ENDER_MM
                and all(abs(q["s"] - s0) > HJORNESONE_MM for s0 in corner_s)]
    ref_speed = med([q["speed"] for q in straight])
    ref_wfs = med([q["wfs"] for q in straight])
    ref_ratio = ref_wfs * 1000/60 / ref_speed if ref_speed and ref_wfs else None

    # Lokal traddiameter ma hentes fra metadata i behandlede filer
    with fil.open(encoding="utf-8-sig", newline="") as handle:
        first = next(csv.DictReader(handle), {})
    diameter = fnum(first.get("Trad_mm"))
    area = math.pi * diameter**2/4 if diameter and diameter > 0 else None
    for q in data:
        q["mm3_per_mm"] = (area * q["wfs"] * 1000/60 / q["speed"]
                            if area and q["valid"] else None)

    rows = []
    for idx, (ci, angle) in enumerate(corners, 1):
        center = data[ci]["s"]
        zone = [q for q in data if q["valid"] and abs(q["s"]-center) <= HJORNESONE_MM]
        actual = med([q["speed"] for q in zone])
        wire = med([q["wfs"] for q in zone])
        ratio = wire*1000/60/actual if actual and wire else None
        # Hastighet som gir samme trådvolum per lengde som rett parti,
        # ved observert hjornetraading. Krever separat geometrisk vurdering.
        target = wire*1000/60/ref_ratio if ref_ratio and wire else None
        rows.append({
            "Fil": fil.name,
            "Hjorne": idx,
            "Posisjon_langs_bane_mm": fmt(center),
            "Retningsendring_grader": fmt(angle, 1),
            "Rett_hastighet_mm_s": fmt(ref_speed),
            "Hjorne_hastighet_mm_s": fmt(actual),
            "Rett_wfs_m_min": fmt(ref_wfs),
            "Hjorne_wfs_m_min": fmt(wire),
            "Volumforhold_hjorne_rett": fmt(ratio/ref_ratio if ratio and ref_ratio else None, 3),
            "Beregnet_hastighet_for_lik_tilforsel_mm_s": fmt(target),
            "Merk": "Teoretisk volummaal; ikke validert som robotkommando",
        })

    if LAG_GRAFER:
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            print("  Mangler matplotlib. Installer: python -m pip install matplotlib")
        else:
            folder = UTDATA / fil.relative_to(INNDATA).parent
            folder.mkdir(parents=True, exist_ok=True)
            # Ett plott per variabel, egne filer
            plots = [
                ("hastighet", "speed", "Robothastighet (mm/s)"),
                ("tradmating", "wfs", "Tradmating (m/min)"),
                ("materialtilforsel", "mm3_per_mm", "Traddvolum per banelengde (mm3/mm)"),
            ]
            for suffix, key, ylabel in plots:
                fig, ax = plt.subplots(figsize=(10, 4))
                x = [q["s"] for q in data if q[key] is not None]
                y = [q[key] for q in data if q[key] is not None]
                ax.plot(x, y)
                for center in corner_s:
                    ax.axvline(center, linestyle="--", alpha=0.6)
                ax.set(xlabel="Avstand langs bane (mm)", ylabel=ylabel,
                       title=f"{fil.stem}: {ylabel}")
                fig.tight_layout()
                fig.savefig(folder / f"{fil.stem}_{suffix}.png", dpi=160)
                plt.close(fig)
            fig, ax = plt.subplots(figsize=(5, 5))
            ax.plot([q["x"] for q in data], [q["y"] for q in data])
            for ci, _ in corners:
                ax.scatter([data[ci]["x"]], [data[ci]["y"]])
            ax.set(xlabel="X (mm)", ylabel="Y (mm)", title=f"{fil.stem}: bane XY")
            ax.set_aspect("equal", adjustable="box")
            fig.tight_layout()
            fig.savefig(folder / f"{fil.stem}_bane.png", dpi=160)
            plt.close(fig)

    print(f"  {fil.name}: {len(data)} punkter, {len(corners)} hjorner, "
          f"referansefart={fmt(ref_speed)} mm/s")
    if ref_speed is None:
        print("  ADVARSEL: for faa stabile rette maalinger til referanse")
    return rows


def main():
    if not INNDATA.is_dir():
        print(f"Fant ikke mappen: {INNDATA}")
        return
    files = [p for p in INNDATA.rglob("*.csv")
             if p.parent.name.upper().startswith(("L_", "U_"))
             or p.name.upper().startswith(("L_", "U_"))]
    print(f"Fant {len(files)} L-/U-filer")
    if not files:
        print("Sjekk INNDATA og filnavn/mappe-navn")
        return
    summary = []
    for fil in sorted(files):
        try:
            summary.extend(analyser(fil))
        except Exception as exc:
            print(f"  FEIL {fil.name}: {exc}")
    UTDATA.mkdir(parents=True, exist_ok=True)
    if summary:
        output = UTDATA / "Hjorneoversikt.csv"
        with output.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(summary[0]))
            writer.writeheader()
            writer.writerows(summary)
        print(f"Oversikt lagret: {output}")
    else:
        print("Ingen hjorner med beregningsresultat funnet")


if __name__ == "__main__":
    main()
