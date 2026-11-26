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

from felles import ANALYSE, BEHANDLET, RAPPORT, les_behandlet, les_temperatur, med, rund as r, tall, test_og_lag

# ======================== ENDRBARE VERDIER ========================
LAG_GRAFER = True
ARC_STROM_MIN_A = 20.0      # strom over dette = bue er paa
MAKS_HULL_S = 2.0           # maks tid mellom to W-maalinger som regnes sammenhengende
MIN_BEVEGELSE_MM_S = 0.5
FJERN_GJENTATTE_W = True    # ~30 % av W-maalingene er kopier av forrige (sveisemaskinen
                            # oppdaterer saktere enn 4 Hz). True = bruk bare nye verdier.
EFTER_BUE_S = 30.0          # temperaturtoppen kommer noen sekunder ETTER at buen stopper
TEMP_KANALER = ["c1"]       # kanaler som brukes. Ubrukte kanaler star ofte som 0 i loggen.
                            # Legg til f.eks. "c2" naar du kobler paa flere termoelementer.
# Hvor sitter termoelementene? Navnet vises i figurene. Ukjente kanaler heter bare "c<n>".
KANALNAVN = {
    "c1": "c1 substrat (midt paa plata)",
    # "c2": "c2 enden av streken",
    # "c3": "c3 ved U-en",
}
# ================================================================

TEMP_KOLONNER = [f"{p}_{k}" for k in TEMP_KANALER for p in ("Temp_start_C", "Temp_maks_C")]
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
] + TEMP_KOLONNER
TEST_KOLONNER = [
    "Test", "Mappe", "Antall_lag", "Testtype", "Beskrivelse",
    "Strom_A", "Spenning_V", "WFS_m_min", "Effekt_kW",
    "Hastighet_median_mm_s", "Varmetilforsel_kJ_mm", "Volum_mm3_mm",
    "Energi_kJ", "Fartsreduksjon_hjorne_pct",
] + TEMP_KOLONNER


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
    kurver = {}
    serier = {k: v for k, v in les_temperatur(fil).items() if k in TEMP_KANALER}
    for kanal, serie in serier.items():
        tider = [q[0] for q in serie]
        # T_start = naermeste maaling til buestart; T_maks = hoyeste verdi fra buestart til EFTER_BUE_S etter bue
        T_start = min(serie, key=lambda q: abs((q[0] - t0).total_seconds()))
        if abs((T_start[0] - t0).total_seconds()) <= 5:
            rad[f"Temp_start_C_{kanal}"] = r(T_start[1], 1)
        vindu = [v for t, v in serie if 0 <= (t - t0).total_seconds() <= buetid + EFTER_BUE_S]
        if vindu:
            rad[f"Temp_maks_C_{kanal}"] = r(max(vindu), 1)
        kurver[kanal] = [((t - t0).total_seconds(), v) for t, v in serie
                         if -10 <= (t - t0).total_seconds() <= buetid + 60]
    rad["_kurver"] = kurver
    rad["_buetid"] = buetid
    rad["_bue"] = (t0, t1)
    rad["_serie"] = serier
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
            v = [x.get(k) for x in rader if x.get(k) is not None]
            # temperatur: hoyeste maks over lagene; ellers median
            s[k] = r(max(v), 1) if v and k.startswith("Temp_maks") else r(med(v), 3)
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
        # temperaturkolonner tas bare med hvis noen filer har dem
        kolonner = [k for k in kolonner if k not in TEMP_KOLONNER or any(x.get(k) is not None for x in rader)]
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
        kanaler = sorted({k[-2:] for q in rader for k in q if k.startswith("Temp_maks_") and q[k] is not None})
        rader_n = 3 if kanaler else 2
        fig, axes = plt.subplots(rader_n, 3, figsize=(13, 3.3 * rader_n), sharex=False)
        akser = list(axes.flat)
        for ax, (key, std, tittel) in zip(akser, paneler):
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
        if kanaler:
            a_start, a_maks, a_tid = akser[6:9]
            for kanal in kanaler:
                navn = KANALNAVN.get(kanal, kanal)
                for ax, pre in ((a_start, "Temp_start_C_"), (a_maks, "Temp_maks_C_")):
                    pts = [(q["Lag"], q[pre + kanal]) for q in rader if q.get(pre + kanal) is not None]
                    if pts:
                        ax.plot(*zip(*pts), marker="o", linewidth=1.5, label=navn)
            a_start.set_title("Temperatur ved buestart (C) - mellomlagstemp.", fontsize=10)
            a_maks.set_title(f"Hoyeste temperatur (C), til {EFTER_BUE_S:g} s etter bue", fontsize=10)
            for ax in (a_start, a_maks):
                ax.set_xticks([q["Lag"] for q in rader])
                ax.set_xlabel("Lag")
                ax.grid(alpha=0.25)
            a_maks.legend(fontsize=7)
            # temperaturkurve mot tid for hvert lag, forste kanal som har data
            kanal = kanaler[0]
            for q in rader:
                kurve = q.get("_kurver", {}).get(kanal)
                if kurve:
                    a_tid.plot(*zip(*kurve), linewidth=1, label=f"lag {q['Lag']}")
                    a_tid.axvline(0, color="gray", linewidth=0.5)
            a_tid.set_title(f"{KANALNAVN.get(kanal, kanal)}: temperatur mot tid fra buestart", fontsize=9)
            a_tid.set_xlabel("s fra buestart")
            a_tid.grid(alpha=0.25)
            if len(rader) <= 12:
                a_tid.legend(fontsize=6, ncol=2)
            for ax in akser[3:6]:
                ax.set_xlabel("Lag")
        else:
            for ax in axes[1]:
                ax.set_xlabel("Lag")
        fig.suptitle(f"{test}: sveiseparametere per lag (median, feillinje = std; stiplet = testmedian)", fontsize=12)
        fig.tight_layout()
        slug = "_".join([p for p in Path(mappe).parts if p != "."] + [test])
        fig.savefig(RAPPORT / f"{slug}.png", dpi=150)
        plt.close(fig)

    # Temperatur gjennom hele testen: alle lag etter hverandre pa en tidsakse
    for (mappe, test), rader in sorted(grupper.items()):
        rader = sorted(rader, key=lambda q: q["Lag"])
        kanaler = sorted({k for q in rader for k in q.get("_serie", {})})
        if not kanaler:
            continue
        t_null = min(q["_bue"][0] for q in rader)
        sek = lambda t: (t - t_null).total_seconds() / 60
        fig, ax = plt.subplots(figsize=(13, 4.5))
        for kanal in kanaler:
            xs, ys = [], []
            for q in rader:
                serie = q.get("_serie", {}).get(kanal)
                if serie:
                    xs += [sek(t) for t, _ in serie]
                    ys += [v for _, v in serie]
            if xs:
                o = sorted(range(len(xs)), key=lambda i: xs[i])
                ax.plot([xs[i] for i in o], [ys[i] for i in o], linewidth=1.2, label=KANALNAVN.get(kanal, kanal))
        topp = ax.get_ylim()[1]
        for q in rader:
            a, b = (sek(t) for t in q["_bue"])
            ax.axvspan(a, b, color="orange", alpha=0.15)
            ax.text((a + b) / 2, topp, f"lag {q['Lag']}", ha="center", va="bottom", fontsize=8)
        ax.set_xlabel("Minutter fra forste buestart")
        ax.set_ylabel("Temperatur (C)")
        ax.set_title(f"{test}: temperatur gjennom lagene (oransje = bue pa)", pad=18)
        ax.grid(alpha=0.25)
        ax.legend(fontsize=8)
        fig.tight_layout()
        slug = "_".join([p for p in Path(mappe).parts if p != "."] + [test])
        fig.savefig(RAPPORT / f"{slug}_temperaturforlop.png", dpi=150)
        plt.close(fig)

    if len(oversikt) > 1:
        paneler2 = list(paneler)
        if any(o.get("Temp_maks_C_c1") is not None for o in oversikt):
            paneler2 += [("Temp_maks_C_c1", None, "Hoyeste temp. c1 (C)")]
        rader_n = 2 if len(paneler2) <= 6 else 3
        fig, axes = plt.subplots(rader_n, 3, figsize=(14, 3.5 * rader_n))
        for ax, (key, _, tittel) in zip(axes.flat, paneler2):
            # tester uten verdi (f.eks. uten temperatur) tas ikke med i panelet
            dat = [o for o in oversikt if o.get(key) is not None] if key.startswith("Temp_") else oversikt
            ax.bar(range(len(dat)), [o.get(key) or 0 for o in dat])
            ax.set_xticks(range(len(dat)))
            ax.set_xticklabels([o["Test"] for o in dat], rotation=60, ha="right", fontsize=7)
            ax.set_title(tittel, fontsize=10)
            ax.grid(axis="y", alpha=0.25)
        for ax in list(axes.flat)[len(paneler2):]:
            ax.axis("off")
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
