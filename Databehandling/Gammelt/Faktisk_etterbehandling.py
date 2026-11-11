#!/usr/bin/env python3
"""Sveiserapport fra ferdigbehandlede CSV-logger (output fra etterbehandlingsskriptet).

Lager:
  * Sveiserapport.xlsx  - ark "Testoversikt" (en rad per test) og "Alle lag" (en rad per fil)
  * en figur per test   - strom, spenning, WFS, effekt, hastighet og varmetilforsel per lag
  * Sammenligning.png   - alle tester side om side (kun hvis det er flere tester)

Alle verdier er MEDIAN over bue-paa-perioden (strom over ARC_STROM_MIN_A),
slik at start/slutt og stillstand ikke trekker snittet.
Energi = gjennomsnittseffekt x buetid. Varmetilforsel (kJ/mm) = energi / banelengde.
"""
import csv
import math
import re
from datetime import datetime
from pathlib import Path
from statistics import median, pstdev

# ======================== ENDRBARE VERDIER ========================
BASE_DIR = Path(__file__).resolve().parent
INNDATA = BASE_DIR / "Behandlet" 
UTDATA = BASE_DIR / "Rapport"
HJORNEOVERSIKT = BASE_DIR / "Analyse_L_U" / "11" / "Hjorneoversikt.csv"  # valgfri

LAG_GRAFER = True
ARC_STROM_MIN_A = 20.0     # strom over dette = bue er paa
MAKS_HULL_S = 2.0          # maks tid mellom to W-malinger som regnes som sammenhengende
MIN_BEVEGELSE_MM_S = 0.5   # lavere fart regnes som stillstand

# Skalering av W-kolonnene (sjekk mot sveiseapparatets display).
# Utskriften viser median per fil, sammenlign med det du stilte inn.
SKALA = dict(I=1.0, V=1.0, WFS=1.0, kW=1.0, kJ=1.0)
# ================================================================

ALLE_KOLONNER = [
    "Test", "Lag", "Mappe", "Fil", "Sveis", "Testtype", "Beskrivelse",
    "Strom_innstilt_A", "Hastighet_innstilt_mm_s", "Trad_mm",
    "Buetid_s", "Banelengde_mm",
    "Strom_A", "Strom_std_A", "Spenning_V", "Spenning_std_V",
    "WFS_m_min", "WFS_std_m_min", "Effekt_kW",
    "Energi_kJ", "Energi_teller_kJ",
    "Hastighet_median_mm_s", "Hastighet_snitt_mm_s",
    "Varmetilforsel_kJ_mm", "Volum_mm3_mm",
    "Fartsreduksjon_hjorne_pct", "Dekning_pct", "Kilde",
]
TEST_KOLONNER = [
    "Test", "Mappe", "Antall_lag", "Testtype", "Beskrivelse",
    "Strom_A", "Spenning_V", "WFS_m_min", "Effekt_kW",
    "Hastighet_median_mm_s", "Varmetilforsel_kJ_mm", "Volum_mm3_mm",
    "Energi_kJ", "Fartsreduksjon_hjorne_pct",
]


def fnum(raw):
    try:
        return float(str(raw).replace(",", "."))
    except (TypeError, ValueError):
        return None


def skal(v, key):
    return None if v is None else v * SKALA[key]


def med(v):
    v = [x for x in v if x is not None]
    return median(v) if v else None


def sd(v):
    v = [x for x in v if x is not None]
    return pstdev(v) if len(v) > 1 else None


def r(v, d=2):
    return None if v is None or not math.isfinite(v) else round(v, d)


def les_fil(fil):
    pos, el, meta = [], [], {}
    with fil.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            if not meta:
                meta = row
            try:
                t = datetime.fromisoformat((row.get("time") or "").strip())
            except ValueError:
                continue
            x, y, z = (fnum(row.get(k)) for k in ("S_x", "S_y", "S_z"))
            if None not in (x, y, z):
                pos.append(dict(t=t, x=x, y=y, z=z, i=fnum(row.get("S_i")),
                                v=fnum(row.get("S_v")), wfs=fnum(row.get("S_wfs"))))
            wi = fnum(row.get("W_I"))
            if wi is not None:
                el.append(dict(t=t, i=skal(wi, "I"),
                               v=skal(fnum(row.get("W_V")), "V"),
                               wfs=skal(fnum(row.get("W_WFS")), "WFS"),
                               kw=skal(fnum(row.get("W_kW")), "kW"),
                               kj=skal(fnum(row.get("W_kJ")), "kJ")))
    pos.sort(key=lambda q: q["t"])
    el.sort(key=lambda q: q["t"])
    return pos, el, meta


def finn_test_og_lag(navn):
    m = re.fullmatch(r"(.+)_Lag_(\d+)", navn, re.I)
    return (m.group(1), int(m.group(2))) if m else (navn, 0)


def les_hjorner():
    """Storste fartsreduksjon per fil fra Hjorneoversikt.csv, hvis den finnes."""
    ut = {}
    if not HJORNEOVERSIKT.is_file():
        return ut
    with HJORNEOVERSIKT.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            rett, hj = fnum(row.get("Rett_hastighet_mm_s")), fnum(row.get("Hjorne_hastighet_mm_s"))
            if rett and hj is not None:
                red = (1 - hj / rett) * 100
                navn = row["Fil"].strip()
                ut[navn] = max(ut.get(navn, red), red)
    return ut


def analyser(fil, hjorner):
    pos, el, meta = les_fil(fil)
    kilde = "W"
    if not el:  # fall tilbake til S-kolonnene (skalert i etterbehandlingen)
        kilde = "S"
        el = [dict(t=p["t"], i=p["i"], v=p["v"], wfs=p["wfs"], kw=None, kj=None)
              for p in pos if p["i"] is not None]
    for s in el:
        if s["kw"] is None and s["i"] is not None and s["v"] is not None:
            s["kw"] = s["i"] * s["v"] / 1000
    arc = [s for s in el if s["i"] is not None and s["i"] >= ARC_STROM_MIN_A]
    if len(arc) < 2:
        print(f"  HOPPER OVER {fil.name}: ingen bue funnet (strom >= {ARC_STROM_MIN_A:g} A)")
        return None

    t0, t1 = arc[0]["t"], arc[-1]["t"]
    buetid = (t1 - t0).total_seconds()
    if buetid <= 0:
        return None

    # Energi: integrer effekt der malingene henger sammen, skaler til hele buetiden
    e_kj, dekket = 0.0, 0.0
    for a, b in zip(arc, arc[1:]):
        dt = (b["t"] - a["t"]).total_seconds()
        if dt <= 0 or dt > MAKS_HULL_S or a["kw"] is None or b["kw"] is None:
            continue
        e_kj += (a["kw"] + b["kw"]) / 2 * dt
        dekket += dt
    energi = e_kj * buetid / dekket if dekket > 0 else None
    dekning = dekket / buetid * 100

    kj = [s["kj"] for s in arc if s["kj"] is not None]
    teller = (kj[-1] - kj[0]) if len(kj) >= 2 and all(b >= a for a, b in zip(kj, kj[1:])) else None

    seg = [p for p in pos if t0 <= p["t"] <= t1]
    lengde = sum(math.dist((a["x"], a["y"], a["z"]), (b["x"], b["y"], b["z"]))
                 for a, b in zip(seg, seg[1:]))
    fart = []
    for a, b in zip(seg, seg[1:]):
        dt = (b["t"] - a["t"]).total_seconds()
        if dt > 0:
            v = math.dist((a["x"], a["y"], a["z"]), (b["x"], b["y"], b["z"])) / dt
            if v >= MIN_BEVEGELSE_MM_S:
                fart.append(v)
    fart_med = med(fart)
    fart_snitt = lengde / buetid if lengde > 0 else None

    wfs_vals = [s["wfs"] for s in arc if s["wfs"] is not None and s["wfs"] > 0]
    wfs_med = med(wfs_vals)
    kw_med = med([s["kw"] for s in arc])
    dia = fnum(meta.get("Trad_mm"))
    areal = math.pi * dia ** 2 / 4 if dia and dia > 0 else None
    volum = (areal * wfs_med * 1000 / 60 / fart_med
             if areal and wfs_med and fart_med else None)
    varme = energi / lengde if energi is not None and lengde > 0 else None

    test, lag = finn_test_og_lag(fil.stem)
    rad = {
        "Test": test, "Lag": lag, "Mappe": str(fil.parent.relative_to(INNDATA)),
        "Fil": fil.name, "Sveis": meta.get("Sveis", ""),
        "Testtype": meta.get("Testtype", ""), "Beskrivelse": meta.get("Beskrivelse", ""),
        "Strom_innstilt_A": fnum(meta.get("Strom_settpunkt_A")),
        "Hastighet_innstilt_mm_s": fnum(meta.get("Hastighet_settpunkt_mm_s")),
        "Trad_mm": dia,
        "Buetid_s": r(buetid, 1), "Banelengde_mm": r(lengde, 1),
        "Strom_A": r(med([s["i"] for s in arc]), 1),
        "Strom_std_A": r(sd([s["i"] for s in arc]), 1),
        "Spenning_V": r(med([s["v"] for s in arc]), 2),
        "Spenning_std_V": r(sd([s["v"] for s in arc]), 2),
        "WFS_m_min": r(wfs_med, 2), "WFS_std_m_min": r(sd(wfs_vals), 2),
        "Effekt_kW": r(kw_med, 3),
        "Energi_kJ": r(energi, 2), "Energi_teller_kJ": r(teller, 2),
        "Hastighet_median_mm_s": r(fart_med, 2), "Hastighet_snitt_mm_s": r(fart_snitt, 2),
        "Varmetilforsel_kJ_mm": r(varme, 3), "Volum_mm3_mm": r(volum, 3),
        "Fartsreduksjon_hjorne_pct": r(hjorner.get(fil.name), 1),
        "Dekning_pct": r(dekning, 0), "Kilde": kilde,
    }
    print(f"  {fil.name}: {rad['Strom_A']} A, {rad['Spenning_V']} V, "
          f"WFS {rad['WFS_m_min']}, {rad['Effekt_kW']} kW, "
          f"{rad['Varmetilforsel_kJ_mm']} kJ/mm, dekning {rad['Dekning_pct']:g} %")
    if dekning < 80:
        print("    ADVARSEL: faa W-malinger i buetiden, energi er skalert opp fra delvis dekning")
    return rad


def test_oversikt(alle):
    grupper = {}
    for rad in alle:
        grupper.setdefault((rad["Mappe"], rad["Test"]), []).append(rad)
    ut = []
    for (mappe, test), rader in sorted(grupper.items()):
        s = {"Test": test, "Mappe": mappe, "Antall_lag": len(rader),
             "Testtype": rader[0]["Testtype"], "Beskrivelse": rader[0]["Beskrivelse"]}
        for k in TEST_KOLONNER[5:]:
            s[k] = r(med([x[k] for x in rader]), 3)
        ut.append(s)
    return grupper, ut


def skriv_excel(alle, oversikt, sti):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    for tittel, kolonner, rader in (("Testoversikt", TEST_KOLONNER, oversikt),
                                    ("Alle lag", ALLE_KOLONNER, alle)):
        ws = wb.active if tittel == "Testoversikt" else wb.create_sheet(tittel)
        ws.title = tittel
        ws.append(kolonner)
        for rad in rader:
            ws.append([rad.get(k) for k in kolonner])
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="305496")
            c.alignment = Alignment(wrap_text=True, vertical="center")
        ws.freeze_panes = "C2"
        ws.auto_filter.ref = ws.dimensions
        ws.row_dimensions[1].height = 32
        for i, k in enumerate(kolonner, 1):
            ws.column_dimensions[get_column_letter(i)].width = max(11, min(26, len(k) + 2))
    wb.save(sti)


def lag_figurer(grupper, oversikt):
    try:
        import matplotlib
        import matplotlib.pyplot as plt
    except ImportError:
        print("Mangler matplotlib: python -m pip install matplotlib")
        return
    paneler = [("Strom_A", "Strom_std_A", "Strom (A)"),
               ("Spenning_V", "Spenning_std_V", "Spenning (V)"),
               ("WFS_m_min", "WFS_std_m_min", "WFS (m/min)"),
               ("Effekt_kW", None, "Effekt (kW)"),
               ("Hastighet_median_mm_s", None, "Hastighet (mm/s)"),
               ("Varmetilforsel_kJ_mm", None, "Varmetilforsel (kJ/mm)")]
    for (mappe, test), rader in sorted(grupper.items()):
        rader = sorted(rader, key=lambda q: q["Lag"])
        fig, axes = plt.subplots(2, 3, figsize=(13, 6.5), sharex=True)
        for ax, (key, std, tittel) in zip(axes.flat, paneler):
            pts = [(q["Lag"], q[key], q.get(std) if std else None)
                   for q in rader if q[key] is not None]
            if pts:
                x, y, e = zip(*pts)
                if std and any(v is not None for v in e):
                    ax.errorbar(x, y, yerr=[v or 0 for v in e], marker="o",
                                capsize=3, linewidth=1.5)
                else:
                    ax.plot(x, y, marker="o", linewidth=1.5)
                m = med(list(y))
                ax.axhline(m, linestyle=":", color="gray", alpha=0.7)
            else:
                ax.text(0.5, 0.5, "ingen data", ha="center", va="center",
                        transform=ax.transAxes, color="gray")
            ax.set_title(tittel, fontsize=10)
            ax.grid(alpha=0.25)
            ax.set_xticks([q["Lag"] for q in rader])
        for ax in axes[1]:
            ax.set_xlabel("Lag")
        fig.suptitle(f"{test}: sveiseparametere per lag (median, feillinje = std; stiplet = testmedian)",
                     fontsize=12)
        fig.tight_layout()
        slug = "_".join([p for p in Path(mappe).parts if p != "."] + [test])
        fig.savefig(UTDATA / f"{slug}.png", dpi=150)
        plt.close(fig)

    if len(oversikt) > 1:
        fig, axes = plt.subplots(2, 3, figsize=(14, 7))
        navn = [f"{o['Test']}" for o in oversikt]
        for ax, (key, _, tittel) in zip(axes.flat, paneler):
            verdier = [o[key] if o[key] is not None else 0 for o in oversikt]
            ax.bar(range(len(oversikt)), verdier)
            ax.set_xticks(range(len(oversikt)))
            ax.set_xticklabels(navn, rotation=60, ha="right", fontsize=7)
            ax.set_title(tittel, fontsize=10)
            ax.grid(axis="y", alpha=0.25)
        fig.suptitle("Sammenligning av tester (median over lag)", fontsize=12)
        fig.tight_layout()
        fig.savefig(UTDATA / "Sammenligning.png", dpi=150)
        plt.close(fig)


def main():
    if not INNDATA.is_dir():
        print(f"Fant ikke mappen: {INNDATA}")
        return
    filer = sorted(p for p in INNDATA.rglob("*.csv")
                   if re.search(r"_Lag_\d+\.csv$", p.name, re.I))
    print(f"Fant {len(filer)} behandlede filer")
    if not filer:
        return
    UTDATA.mkdir(parents=True, exist_ok=True)
    hjorner = les_hjorner()
    alle = []
    for fil in filer:
        try:
            rad = analyser(fil, hjorner)
        except Exception as ex:
            print(f"  FEIL {fil.name}: {ex}")
            continue
        if rad:
            alle.append(rad)
    if not alle:
        print("Ingen filer med bue funnet")
        return
    alle.sort(key=lambda q: (q["Mappe"], q["Test"], q["Lag"]))
    grupper, oversikt = test_oversikt(alle)
    try:
        sti = UTDATA / "Sveiserapport.xlsx"
        skriv_excel(alle, oversikt, sti)
        print(f"\nRapport lagret: {sti}")
    except Exception as ex:
        print(f"Kunne ikke skrive Excel ({ex}). Er filen aapen i Excel?")
    if LAG_GRAFER:
        lag_figurer(grupper, oversikt)
        print(f"Figurer lagret i: {UTDATA}")


if __name__ == "__main__":
    main()