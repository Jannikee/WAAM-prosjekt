#!/usr/bin/env python3
"""Analyse av L-/U-sveiser fra ferdigbehandlede CSV-logger.

ALL hastighet regnes fra to paafolgende posisjonsmaalinger (ingen utjevning).
Hjorneoversikten bruker LAVESTE 2-punkts-fart i hjornesonen (ikke median).
Verdien plasseres ved midtpunktet i rom og langs banen.
Kun laveste hastighet og geometrisk sving markeres; start/retur er fjernet.
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
INNDATA = BASE_DIR / "Behandlet" / "11" / "06"      # Bytt til "Behandlet_PL_test" for PL-testene
UTDATA = BASE_DIR / "Analyse_L_U" / "11" / "06"   # Bruk samme resultatmappe som tidligere

LAG_GRAFER = True
# Ingen hastighetsvinduer: alltid to paafolgende posisjonsmaalinger.
RETNINGSAVSTAND_MM = 8.0       # maal retning 8 mm paa hver side
MIN_HJORNEVINKEL_GRADER = 30.0
HJORNESONE_MM = 8.0            # omraade rundt hvert funnet hjorne
MIN_AVSTAND_MELLOM_HJORNER_MM = 15.0
UTELAT_ENDER_MM = 5.0
MIN_BEVEGELSE_MM_S = 0.5
MIN_TRADMATING_M_MIN = 0.1
HASTIGHETSGRENSE_PROSENT = 95.0  # fartsfall under 95 % av rett hastighet
# Marker kun laveste malte hastighet i den lokale hjornesonen.
# Ingen beregning eller markering av start/retur for hastighetsfallet.
ZOOM_HALVBREDDE_MM = 16.0       # utsnitt +/- mm rundt hjornets sentrum
# Merk: beregnet hastighetsmaal er kun volumbalanse, ikke en
# ferdig anbefalt robotkommando; valider i robot/logg og bead-geometri.
# ================================================================

def fnum(raw):
    try:
        return float(str(raw).replace(",", "."))
    except (TypeError, ValueError):
        return None


def les_data(fil):
    """Hent alle S-posisjoner; WFS kan mangle uten at fartspunkter forsvinner."""
    out = []
    with fil.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            x, y, z, wfs = (fnum(row.get(k)) for k in ("S_x", "S_y", "S_z", "S_wfs"))
            if any(v is None for v in (x, y, z)):
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

    # Geometrisk banelengde fra etterfolgende posisjoner.
    data[0]["s"] = 0.0
    for i in range(1, len(data)):
        data[i]["s"] = data[i-1]["s"] + length(data[i-1], data[i])

    # Hvert intervall inneholder KUN maaling i-1 og i.
    # Farten gjelder segmentet mellom punktene, ikke et helt tidsvindu.
    # s/x/y/z representerer MIDTPUNKTET av dette segmentet.
    intervaller = []
    for forrige, denne in zip(data, data[1:]):
        dt = (denne["t"] - forrige["t"]).total_seconds()
        if dt <= 0:
            continue
        ds = length(forrige, denne)
        speed = ds / dt
        # WFS ma finnes i begge ender; ikke gjett verdier ved manglende logging.
        wfs = ((forrige["wfs"] + denne["wfs"]) / 2
               if forrige["wfs"] is not None and denne["wfs"] is not None else None)
        intervaller.append({
            "s": (forrige["s"] + denne["s"]) / 2,
            "x": (forrige["x"] + denne["x"]) / 2,
            "y": (forrige["y"] + denne["y"]) / 2,
            "z": (forrige["z"] + denne["z"]) / 2,
            "t0": forrige["t"],
            "t1": denne["t"],
            "dt": dt,
            "ds": ds,
            "speed": speed,
            "wfs": wfs,
            # Hastighet beregnes og brukes ogsa i torrekjoring uten traadmating.
            "valid": speed >= MIN_BEVEGELSE_MM_S,
            "valid_material": (speed >= MIN_BEVEGELSE_MM_S
                               and wfs is not None
                               and wfs >= MIN_TRADMATING_M_MIN),
        })
    if not intervaller:
        print(f"  HOPPER OVER {fil.name}: ingen gyldige tidsintervaller")
        return []

    corners = finn_hjorner(data)
    if not corners:
        print(f"  ADVARSEL {fil.name}: ingen tydelige hjorner funnet")

    corner_s = [data[i]["s"] for i, _ in corners]
    total_len = data[-1]["s"]
    # Kun stabile, sveiste partier, uten ender eller identifiserte hjorner
    straight = [q for q in intervaller if q["valid"]
                and UTELAT_ENDER_MM <= q["s"] <= total_len-UTELAT_ENDER_MM
                and all(abs(q["s"] - s0) > HJORNESONE_MM for s0 in corner_s)]
    ref_speed = med([q["speed"] for q in straight])
    ref_wfs = med([q["wfs"] for q in straight if q["valid_material"]])
    ref_ratio = ref_wfs * 1000/60 / ref_speed if ref_speed and ref_wfs else None

    # Lokal traddiameter ma hentes fra metadata i behandlede filer
    with fil.open(encoding="utf-8-sig", newline="") as handle:
        first = next(csv.DictReader(handle), {})
    diameter = fnum(first.get("Trad_mm"))
    area = math.pi * diameter**2/4 if diameter and diameter > 0 else None
    for q in intervaller:
        # Volum per mm er ikke rapportert naer stillstand (< MIN_BEVEGELSE_MM_S).
        q["mm3_per_mm"] = (area * q["wfs"] * 1000/60 / q["speed"]
                            if area and q["valid_material"] else None)

    # Hver enkelt hastighet er beregnet fra nøyaktig to målepunkter.
    # Hjørnehastighet er nå LAVESTE slike intervall i sonen (ikke median).
    # Referansefarten på rette partier er medianen av individuelle
    # to-punkts-hastigheter for å redusere påvirkning fra målevariasjon.
    rows = []
    fartsperioder = []
    detaljer = []
    for hjorne_nr, (ci, angle) in enumerate(corners, 1):
        center = data[ci]["s"]
        zone = [q for q in intervaller if q["valid"]
                and abs(q["s"] - center) <= HJORNESONE_MM]
        if not zone:
            continue

        lavest = min(zone, key=lambda q: q["speed"])
        actual = lavest["speed"]
        # Bruk trådmating fra SAMME intervall som hastighetsminimum.
        wire = lavest["wfs"] if lavest["valid_material"] else None
        ratio = wire * 1000 / 60 / actual if wire is not None and actual > 0 else None
        target = wire * 1000 / 60 / ref_ratio if wire is not None and ref_ratio else None
        rows.append({
            "Fil": fil.name,
            "Hjorne": hjorne_nr,
            "Posisjon_langs_bane_mm": fmt(center),
            "Retningsendring_grader": fmt(angle, 1),
            "Rett_hastighet_mm_s": fmt(ref_speed),
            "Hjorne_hastighet_mm_s": fmt(actual),
            "Rett_wfs_m_min": fmt(ref_wfs),
            "Hjorne_wfs_m_min": fmt(wire),
            "Volumforhold_hjorne_rett": fmt(ratio / ref_ratio if ratio is not None and ref_ratio else None, 3),
            "Beregnet_hastighet_for_lik_tilforsel_mm_s": fmt(target),
            "Merk": f"Hjornefart=laveste enkeltintervall innen +/- {HJORNESONE_MM:g} mm; teoretisk volummaal",
        })
        fartsperioder.append((hjorne_nr, center, lavest))
        detaljer.append({
            "Fil": fil.name,
            "Sving": hjorne_nr,
            "Hjorne_s_mm": fmt(center),
            "Lavest_s_mm": fmt(lavest["s"]),
            "Lavest_fart_mm_s": fmt(lavest["speed"], 3),
            "Intervall_fra": lavest["t0"].isoformat(),
            "Intervall_til": lavest["t1"].isoformat(),
            "Lavest_dt_s": fmt(lavest["dt"], 3),
            "Lavest_ds_mm": fmt(lavest["ds"], 3),
            "Lavest_X_mm": fmt(lavest["x"]),
            "Lavest_Y_mm": fmt(lavest["y"]),
        })

    grense = (ref_speed * HASTIGHETSGRENSE_PROSENT / 100
              if ref_speed is not None else None)

    # Samlet fil med konkrete malepunkter – lages ogsa uten grafer.
    if detaljer:
        folder = UTDATA / fil.relative_to(INNDATA).parent
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / f"{fil.stem}_fartspunkter.csv").open(
                "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(detaljer[0]))
            writer.writeheader()
            writer.writerows(detaljer)

    if LAG_GRAFER:
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            print("  Mangler matplotlib. Installer: python -m pip install matplotlib")
        else:
            folder = UTDATA / fil.relative_to(INNDATA).parent
            folder.mkdir(parents=True, exist_ok=True)
            # Ett plott per variabel, egne filer
            plots = [("hastighet", "speed", "Robothastighet (mm/s)")]
            if any(q["wfs"] is not None and q["wfs"] >= MIN_TRADMATING_M_MIN
                   for q in intervaller):
                plots.append(("tradmating", "wfs", "Tradmating (m/min)"))
            if any(q["mm3_per_mm"] is not None for q in intervaller):
                plots.append(("materialtilforsel", "mm3_per_mm",
                              "Tradvolum per banelengde (mm3/mm)"))
            for suffix, key, ylabel in plots:
                fig, ax = plt.subplots(figsize=(10, 4))
                x = [q["s"] for q in intervaller if q[key] is not None]
                y = [q[key] for q in intervaller if q[key] is not None]
                ax.plot(x, y)
                for k, center in enumerate(corner_s):
                    ax.axvline(center, linestyle="--", alpha=0.6,
                               label="Svingens sentrum" if k == 0 else None)
                if key == "speed":
                    if grense is not None:
                        ax.axhline(grense, linestyle=":",
                                   label=f"{HASTIGHETSGRENSE_PROSENT:g} % av rett fart")
                    for indeks, (_, center, lavest) in enumerate(fartsperioder):
                        ax.scatter(lavest["s"], lavest["speed"], marker="x", s=65,
                                   zorder=5,
                                   label="Laveste fart i hjornesonen" if indeks == 0 else None)
                    ax.legend(loc="best", fontsize=8)
                ax.set(xlabel="Avstand langs bane (mm, mellom posisjoner)", ylabel=ylabel,
                       title=f"{fil.stem}: {ylabel}")
                fig.tight_layout()
                fig.savefig(folder / f"{fil.stem}_{suffix}.png", dpi=160)
                plt.close(fig)
            # Egen innzoomet graf: kun hjornesenter og laveste fart.
            for svingnummer, center, lavest in fartsperioder:
                lo = max(0, center - ZOOM_HALVBREDDE_MM)
                hi = center + ZOOM_HALVBREDDE_MM
                zoom = [q for q in intervaller
                        if lo <= q["s"] <= hi]
                if not zoom:
                    continue

                fig = plt.figure(figsize=(12, 5))
                ax = fig.add_axes((0.08, 0.15, 0.59, 0.72))
                ax.plot([q["s"] for q in zoom], [q["speed"] for q in zoom],
                        linewidth=2, label="Beregnet hastighet")
                if grense is not None:
                    ax.axhline(grense, linestyle=":", color="gray",
                               label=f"{HASTIGHETSGRENSE_PROSENT:g} %-grense ({grense:.2f} mm/s)")
                ax.axvline(center, linestyle="--", alpha=0.6,
                           label="Svingens sentrum")
                ax.scatter(lavest["s"], lavest["speed"], marker="X",
                           s=95, zorder=5, label="Laveste fart i hjornesonen")
                ax.set(xlabel="Avstand langs banen (mm)",
                       ylabel="Hastighet mellom to maalinger (mm/s)")
                ax.grid(alpha=0.25)
                ax.legend(loc="best", fontsize=8)

                fig.text(0.72, 0.77, "LAVESTE FART NAER HJORNET",
                         fontsize=11, weight="bold")
                fig.text(0.72, 0.59,
                         f"Avstand: {lavest['s']:.2f} mm\n"
                         f"Fart: {lavest['speed']:.3f} mm/s\n"
                         f"dt: {lavest['dt']:.3f} s\n"
                         f"X: {lavest['x']:.2f} mm\n"
                         f"Y: {lavest['y']:.2f} mm",
                         fontsize=10, va="top", family="monospace")
                fig.suptitle(f"{fil.stem} - sving {svingnummer}: hastighet",
                             fontsize=13, y=0.97)
                fig.savefig(folder / f"{fil.stem}_sving_{svingnummer}_detaljer.png",
                            dpi=180, bbox_inches="tight")
                plt.close(fig)

            fig, ax = plt.subplots(figsize=(5, 5))
            ax.plot([q["x"] for q in data], [q["y"] for q in data])
            for k, (ci, _) in enumerate(corners):
                ax.scatter([data[ci]["x"]], [data[ci]["y"]], marker="o",
                           label="Svingens sentrum" if k == 0 else None)
            for indeks, (_, center, lavest) in enumerate(fartsperioder):
                ax.scatter(lavest["x"], lavest["y"], marker="x", s=65,
                           label="Laveste fart i hjornesonen" if indeks == 0 else None)
            if corners or fartsperioder:
                ax.legend(loc="best", fontsize=7)
            ax.set(xlabel="X (mm)", ylabel="Y (mm)", title=f"{fil.stem}: bane XY")
            ax.set_aspect("equal", adjustable="box")
            fig.tight_layout()
            fig.savefig(folder / f"{fil.stem}_bane.png", dpi=160)
            plt.close(fig)

    print(f"  {fil.name}: {len(data)} posisjoner, {len(intervaller)} mellomrom, "
          f"{len(corners)} hjorner, referansefart={fmt(ref_speed)} mm/s")
    if ref_speed is None:
        print("  ADVARSEL: for faa stabile rette maalinger til referanse")
    if ref_wfs is None:
        print("  INFO: ingen relevant tradmating; materialtilforsel kan ikke beregnes")
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
