"""Steg 3: Sveiserapport. Behandlet/<mappe> -> Rapport/.

Lager:
  * Sveiserapport.xlsx - ark "Testoversikt" (en rad per test) og "Alle lag"
  * en figur per test  - strom, spenning, WFS, effekt, hastighet, varmetilforsel per lag
  * Sammenligning.png  - alle tester side om side

Verdiene er MEDIAN over bue-paa-perioden (strom >= ARC_STROM_MIN_A).
Energi = integrert effekt (trapes) over buetiden. Varmetilforsel = energi / banelengde.
"""
import csv
import math
import re
from pathlib import Path
from statistics import pstdev

from felles import ANALYSE, BEHANDLET, RAPPORT, les_behandlet, med, rund as r, tall, test_og_lag

# ======================== ENDRBARE VERDIER ========================
LAG_GRAFER = True
ARC_STROM_MIN_A = 20.0      # strom over dette = bue er paa
MAKS_HULL_S = 2.0           # maks tid mellom to W-maalinger som regnes sammenhengende
MIN_BEVEGELSE_MM_S = 0.5
FJERN_GJENTATTE_W = True    # ~30 % av W-maalingene er kopier av forrige (sveisemaskinen
                            # oppdaterer saktere enn 4 Hz). True = bruk bare nye verdier.
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


def sd(v):
    v = [x for x in v if x is not None]
    return pstdev(v) if len(v) > 1 else None


def les_hjorner():
    """Storste fartsreduksjon per fil fra alle Hjorneoversikt.csv under Analyse_L_U."""
    ut = {}
    for fil in ANALYSE.rglob("Hjorneoversikt.csv"):
        with fil.open(encoding="utf-8-sig", newline="") as fh:
            for rad in csv.DictReader(fh):
                rett, hj = tall(rad.get("Rett_hastighet_mm_s")), tall(rad.get("Hjorne_hastighet_mm_s"))
                if rett and hj is not None:
                    red = (1 - hj / rett) * 100
                    ut[rad["Fil"].strip()] = max(ut.get(rad["Fil"].strip(), red), red)
    return ut


def energiteller(arc):
    """Okning i W_kJ. Telleren nullstilles ved buestart, saa nedganger hoppes over."""
    kj = [s["kj"] for s in arc if s["kj"] is not None]
    if len(kj) < 2:
        return None
    return sum(b - a for a, b in zip(kj, kj[1:]) if b >= a)


def analyser(fil, hjorner):
    meta, pos, el = les_behandlet(fil)
    if FJERN_GJENTATTE_W:
        el = [w for k, w in enumerate(el)
              if k == 0 or (w["i"], w["v"], w["wfs"], w["kw"], w["kj"]) !=
              (el[k - 1]["i"], el[k - 1]["v"], el[k - 1]["wfs"], el[k - 1]["kw"], el[k - 1]["kj"])]
    kilde = "W"
    if not el:   # fall tilbake til robotens avlesning (S_i, S_v, S_wfs)
        kilde = "S"
        el = [dict(t=p["t"], i=p["i"], v=p["v"], wfs=p["wfs"], kw=None, kj=None) for p in pos if p["i"] is not None]
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

    # Energi: trapesintegrasjon der maalingene henger sammen, skalert til hele buetiden
    e_kj, dekket = 0.0, 0.0
    for a, b in zip(arc, arc[1:]):
        dt = (b["t"] - a["t"]).total_seconds()
        if 0 < dt <= MAKS_HULL_S and a["kw"] is not None and b["kw"] is not None:
            e_kj += (a["kw"] + b["kw"]) / 2 * dt
            dekket += dt
    energi = e_kj * buetid / dekket if dekket > 0 else None
    dekning = dekket / buetid * 100

    seg = [p for p in pos if t0 <= p["t"] <= t1]
    xyz = lambda p: (p["x"], p["y"], p["z"])
    lengde = sum(math.dist(xyz(a), xyz(b)) for a, b in zip(seg, seg[1:]))
    fart = [v for a, b in zip(seg, seg[1:])
            if (dt := (b["t"] - a["t"]).total_seconds()) > 0
            and (v := math.dist(xyz(a), xyz(b)) / dt) >= MIN_BEVEGELSE_MM_S]
    fart_med = med(fart)

    wfs = [s["wfs"] for s in arc if s["wfs"] is not None and s["wfs"] > 0]
    wfs_med = med(wfs)
    dia = tall(meta.get("Trad_mm"))
    areal = math.pi * dia ** 2 / 4 if dia and dia > 0 else None
    volum = areal * wfs_med * 1000 / 60 / fart_med if areal and wfs_med and fart_med else None
    varme = energi / lengde if energi is not None and lengde > 0 else None

    test, lag = test_og_lag(fil.name)
    rad = {
        "Test": test, "Lag": lag, "Mappe": str(fil.parent.relative_to(BEHANDLET)),
        "Fil": fil.name, "Sveis": meta.get("Sveis", ""),
        "Testtype": meta.get("Testtype", ""), "Beskrivelse": meta.get("Beskrivelse", ""),
        "Strom_innstilt_A": tall(meta.get("Strom_settpunkt_A")),
        "Hastighet_innstilt_mm_s": tall(meta.get("Hastighet_settpunkt_mm_s")),
        "Trad_mm": dia, "Buetid_s": r(buetid, 1), "Banelengde_mm": r(lengde, 1),
        "Strom_A": r(med([s["i"] for s in arc]), 1), "Strom_std_A": r(sd([s["i"] for s in arc]), 1),
        "Spenning_V": r(med([s["v"] for s in arc]), 2), "Spenning_std_V": r(sd([s["v"] for s in arc]), 2),
        "WFS_m_min": r(wfs_med, 2), "WFS_std_m_min": r(sd(wfs), 2),
        "Effekt_kW": r(med([s["kw"] for s in arc]), 3),
        "Energi_kJ": r(energi, 2), "Energi_teller_kJ": r(energiteller(arc), 2),
        "Hastighet_median_mm_s": r(fart_med, 2),
        "Hastighet_snitt_mm_s": r(lengde / buetid if lengde > 0 else None, 2),
        "Varmetilforsel_kJ_mm": r(varme, 3), "Volum_mm3_mm": r(volum, 3),
        "Fartsreduksjon_hjorne_pct": r(hjorner.get(fil.name), 1),
        "Dekning_pct": r(dekning, 0), "Kilde": kilde,
    }
    print(f"  {fil.name}: {rad['Strom_A']} A, {rad['Spenning_V']} V, WFS {rad['WFS_m_min']}, "
          f"{rad['Effekt_kW']} kW, {rad['Varmetilforsel_kJ_mm']} kJ/mm, dekning {rad['Dekning_pct']:g} %")
    if dekning < 80:
        print("    ADVARSEL: faa W-maalinger i buetiden, energi er skalert opp fra delvis dekning")
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
    for tittel, kolonner, rader in (("Testoversikt", TEST_KOLONNER, oversikt), ("Alle lag", ALLE_KOLONNER, alle)):
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
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    paneler = [("Strom_A", "Strom_std_A", "Strom (A)"), ("Spenning_V", "Spenning_std_V", "Spenning (V)"),
               ("WFS_m_min", "WFS_std_m_min", "WFS (m/min)"), ("Effekt_kW", None, "Effekt (kW)"),
               ("Hastighet_median_mm_s", None, "Hastighet (mm/s)"),
               ("Varmetilforsel_kJ_mm", None, "Varmetilforsel (kJ/mm)")]
    for (mappe, test), rader in sorted(grupper.items()):
        rader = sorted(rader, key=lambda q: q["Lag"])
        fig, axes = plt.subplots(2, 3, figsize=(13, 6.5), sharex=True)
        for ax, (key, std, tittel) in zip(axes.flat, paneler):
            pts = [(q["Lag"], q[key], q.get(std) if std else None) for q in rader if q[key] is not None]
            if pts:
                x, y, e = zip(*pts)
                if std and any(v is not None for v in e):
                    ax.errorbar(x, y, yerr=[v or 0 for v in e], marker="o", capsize=3, linewidth=1.5)
                else:
                    ax.plot(x, y, marker="o", linewidth=1.5)
                ax.axhline(med(list(y)), linestyle=":", color="gray", alpha=0.7)
            else:
                ax.text(0.5, 0.5, "ingen data", ha="center", va="center", transform=ax.transAxes, color="gray")
            ax.set_title(tittel, fontsize=10)
            ax.grid(alpha=0.25)
            ax.set_xticks([q["Lag"] for q in rader])
        for ax in axes[1]:
            ax.set_xlabel("Lag")
        fig.suptitle(f"{test}: sveiseparametere per lag (median, feillinje = std; stiplet = testmedian)", fontsize=12)
        fig.tight_layout()
        slug = "_".join([p for p in Path(mappe).parts if p != "."] + [test])
        fig.savefig(RAPPORT / f"{slug}.png", dpi=150)
        plt.close(fig)

    if len(oversikt) > 1:
        fig, axes = plt.subplots(2, 3, figsize=(14, 7))
        for ax, (key, _, tittel) in zip(axes.flat, paneler):
            ax.bar(range(len(oversikt)), [o[key] or 0 for o in oversikt])
            ax.set_xticks(range(len(oversikt)))
            ax.set_xticklabels([o["Test"] for o in oversikt], rotation=60, ha="right", fontsize=7)
            ax.set_title(tittel, fontsize=10)
            ax.grid(axis="y", alpha=0.25)
        fig.suptitle("Sammenligning av tester (median over lag)", fontsize=12)
        fig.tight_layout()
        fig.savefig(RAPPORT / "Sammenligning.png", dpi=150)
        plt.close(fig)


def rapport(mappe=""):
    inn = BEHANDLET / mappe
    if not inn.is_dir():
        print("Fant ikke mappen:", inn)
        return
    filer = sorted(p for p in inn.rglob("*.csv") if re.search(r"_Lag_\d+\.csv$", p.name, re.I))
    print(f"Fant {len(filer)} behandlede filer")
    RAPPORT.mkdir(parents=True, exist_ok=True)
    hjorner = les_hjorner()
    alle = []
    for fil in filer:
        try:
            if (rad := analyser(fil, hjorner)):
                alle.append(rad)
        except Exception as ex:
            print(f"  FEIL {fil.name}: {ex}")
    if not alle:
        print("Ingen filer med bue funnet")
        return
    alle.sort(key=lambda q: (q["Mappe"], q["Test"], q["Lag"]))
    grupper, oversikt = test_oversikt(alle)
    sti = RAPPORT / "Sveiserapport.xlsx"
    try:
        skriv_excel(alle, oversikt, sti)
        print(f"\nRapport lagret: {sti.relative_to(BEHANDLET.parent)}")
    except PermissionError:
        print("Kunne ikke skrive Sveiserapport.xlsx. Er den aapen i Excel?")
    if LAG_GRAFER:
        lag_figurer(grupper, oversikt)
        print(f"Figurer lagret i: {RAPPORT.relative_to(BEHANDLET.parent)}")
