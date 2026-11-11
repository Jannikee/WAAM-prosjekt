"""Steg 2: Hjorneanalyse av L- og U-sveiser. Behandlet/<mappe> -> Analyse_L_U/<mappe>.

Hastighet = avstand / tid mellom to paafolgende S-maalinger (4 Hz, ca. 0,25 s).
Ingen utjevning. Per hjorne brukes LAVESTE slike hastighet innen
+/- HJORNESONE_MM. Referansefarten er medianen paa rette partier.

Lager:
  per lag:  <fil>_hastighet.png, _tradmating.png, _materialtilforsel.png,
            _sving_N_detaljer.png, _fartspunkter.csv
  samlet:   Hjorneoversikt.csv
            Hjorneoversikt_med_fartsreduksjon.csv + Fartsreduksjon_<test>.png
            Hjornehastighet_per_lag.csv + Hjornehastighet_oppsummering.csv
"""
import math
from bisect import bisect_left
from collections import defaultdict
from statistics import mean, median

from felles import ANALYSE, BEHANDLET, er_l_eller_u, les_behandlet, med, skriv_csv, tall, test_og_lag

# ======================== ENDRBARE VERDIER ========================
LAG_GRAFER = True
RETNINGSAVSTAND_MM = 8.0        # retning maales 8 mm paa hver side
MIN_HJORNEVINKEL_GRADER = 30.0
HJORNESONE_MM = 8.0             # sone rundt hvert hjorne
MIN_AVSTAND_MELLOM_HJORNER_MM = 15.0
UTELAT_ENDER_MM = 5.0
MIN_BEVEGELSE_MM_S = 0.5
MIN_TRADMATING_M_MIN = 0.1
HASTIGHETSGRENSE_PROSENT = 95.0
ZOOM_HALVBREDDE_MM = 16.0
STANDARD_PROGRAMMERT_FART = 7.0  # brukes hvis fila mangler Hastighet_settpunkt_mm_s
VARSEL_MATERIALOKNING_PCT = 10.0
# ================================================================


def _f(v, d=2):
    return "" if v is None or not math.isfinite(v) else round(v, d)


def finn_hjorner(data):
    """Retningsendringer i XY over +/- RETNINGSAVSTAND_MM. Returnerer [(indeks, vinkel)]."""
    s = [q["s"] for q in data]
    kand = []
    for i in range(1, len(data) - 1):
        foer = bisect_left(s, s[i] - RETNINGSAVSTAND_MM)
        etter = bisect_left(s, s[i] + RETNINGSAVSTAND_MM)
        if (foer == 0 and s[i] - s[0] < RETNINGSAVSTAND_MM) or etter >= len(data):
            continue
        a, b, c = data[foer], data[i], data[etter]
        v1 = (b["x"] - a["x"], b["y"] - a["y"])
        v2 = (c["x"] - b["x"], c["y"] - b["y"])
        n1, n2 = math.hypot(*v1), math.hypot(*v2)
        if min(n1, n2) < 1:
            continue
        vinkel = math.degrees(math.acos(max(-1, min(1, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))))
        if vinkel >= MIN_HJORNEVINKEL_GRADER:
            kand.append((i, vinkel))
    # samme hjorne gir mange treff: behold storste vinkel per gruppe
    grupper = []
    for k in kand:
        if grupper and s[k[0]] - s[grupper[-1][-1][0]] <= MIN_AVSTAND_MELLOM_HJORNER_MM:
            grupper[-1].append(k)
        else:
            grupper.append([k])
    return [max(g, key=lambda p: p[1]) for g in grupper]


def intervaller(data):
    """Fart, WFS og posisjon for hvert mellomrom mellom to S-maalinger (midtpunkt)."""
    ut = []
    for a, b in zip(data, data[1:]):
        dt = (b["t"] - a["t"]).total_seconds()
        if dt <= 0:
            continue
        ds = math.dist((a["x"], a["y"], a["z"]), (b["x"], b["y"], b["z"]))
        fart = ds / dt
        wfs = (a["wfs"] + b["wfs"]) / 2 if a["wfs"] is not None and b["wfs"] is not None else None
        ut.append(dict(s=(a["s"] + b["s"]) / 2, x=(a["x"] + b["x"]) / 2, y=(a["y"] + b["y"]) / 2,
                       t0=a["t"], t1=b["t"], dt=dt, ds=ds, speed=fart, wfs=wfs,
                       valid=fart >= MIN_BEVEGELSE_MM_S,
                       valid_material=fart >= MIN_BEVEGELSE_MM_S and wfs is not None and wfs >= MIN_TRADMATING_M_MIN))
    return ut


def analyser_fil(fil, inn, ut):
    meta, data, _ = les_behandlet(fil)
    # fjern dobbelt-tidsstempler (dt = 0)
    data = [q for k, q in enumerate(data) if k == 0 or q["t"] != data[k - 1]["t"]]
    if len(data) < 12:
        print(f"  HOPPER OVER {fil.name}: for faa S-maalinger ({len(data)})")
        return []
    data[0]["s"] = 0.0
    for a, b in zip(data, data[1:]):
        b["s"] = a["s"] + math.dist((a["x"], a["y"], a["z"]), (b["x"], b["y"], b["z"]))

    iv = intervaller(data)
    if not iv:
        print(f"  HOPPER OVER {fil.name}: ingen gyldige tidsintervaller")
        return []
    hjorner = finn_hjorner(data)
    if not hjorner:
        print(f"  ADVARSEL {fil.name}: ingen tydelige hjorner funnet")
    hjorne_s = [data[i]["s"] for i, _ in hjorner]
    total = data[-1]["s"]

    rett = [q for q in iv if q["valid"] and UTELAT_ENDER_MM <= q["s"] <= total - UTELAT_ENDER_MM
            and all(abs(q["s"] - s0) > HJORNESONE_MM for s0 in hjorne_s)]
    ref_fart = med([q["speed"] for q in rett])
    ref_wfs = med([q["wfs"] for q in rett if q["valid_material"]])
    ref_forhold = ref_wfs * 1000 / 60 / ref_fart if ref_fart and ref_wfs else None

    d = tall(meta.get("Trad_mm"))
    areal = math.pi * d ** 2 / 4 if d and d > 0 else None
    for q in iv:
        q["mm3_per_mm"] = areal * q["wfs"] * 1000 / 60 / q["speed"] if areal and q["valid_material"] else None

    rader, laveste, detaljer = [], [], []
    for nr, (ci, vinkel) in enumerate(hjorner, 1):
        senter = data[ci]["s"]
        sone = [q for q in iv if q["valid"] and abs(q["s"] - senter) <= HJORNESONE_MM]
        if not sone:
            continue
        lav = min(sone, key=lambda q: q["speed"])
        traad = lav["wfs"] if lav["valid_material"] else None
        forhold = traad * 1000 / 60 / lav["speed"] if traad is not None and lav["speed"] > 0 else None
        rader.append({
            "Fil": fil.name, "Hjorne": nr,
            "Posisjon_langs_bane_mm": _f(senter),
            "Retningsendring_grader": _f(vinkel, 1),
            "Rett_hastighet_mm_s": _f(ref_fart),
            "Hjorne_hastighet_mm_s": _f(lav["speed"]),
            "Rett_wfs_m_min": _f(ref_wfs),
            "Hjorne_wfs_m_min": _f(traad),
            "Volumforhold_hjorne_rett": _f(forhold / ref_forhold if forhold is not None and ref_forhold else None, 3),
            "Beregnet_hastighet_for_lik_tilforsel_mm_s": _f(traad * 1000 / 60 / ref_forhold if traad is not None and ref_forhold else None),
            "Programmert_hastighet_mm_s": _f(tall(meta.get("Hastighet_settpunkt_mm_s"))),
            "Merk": f"Hjornefart=laveste enkeltintervall innen +/- {HJORNESONE_MM:g} mm; teoretisk volummaal",
        })
        laveste.append((nr, senter, lav))
        detaljer.append({
            "Fil": fil.name, "Sving": nr, "Hjorne_s_mm": _f(senter), "Lavest_s_mm": _f(lav["s"]),
            "Lavest_fart_mm_s": _f(lav["speed"], 3), "Intervall_fra": lav["t0"].isoformat(),
            "Intervall_til": lav["t1"].isoformat(), "Lavest_dt_s": _f(lav["dt"], 3),
            "Lavest_ds_mm": _f(lav["ds"], 3), "Lavest_X_mm": _f(lav["x"]), "Lavest_Y_mm": _f(lav["y"]),
        })

    mappe = ut / fil.relative_to(inn).parent
    if detaljer:
        skriv_csv(mappe / f"{fil.stem}_fartspunkter.csv", detaljer)
    if LAG_GRAFER:
        grense = ref_fart * HASTIGHETSGRENSE_PROSENT / 100 if ref_fart is not None else None
        tegn_lag(fil.stem, mappe, iv, hjorne_s, laveste, grense)

    print(f"  {fil.name}: {len(data)} posisjoner, {len(hjorner)} hjorner, referansefart={_f(ref_fart)} mm/s")
    if ref_fart is None:
        print("  ADVARSEL: for faa stabile rette maalinger til referanse")
    return rader


def tegn_lag(navn, mappe, iv, hjorne_s, laveste, grense):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    mappe.mkdir(parents=True, exist_ok=True)

    plott = [("hastighet", "speed", "Robothastighet (mm/s)")]
    if any(q["wfs"] is not None and q["wfs"] >= MIN_TRADMATING_M_MIN for q in iv):
        plott.append(("tradmating", "wfs", "Tradmating (m/min)"))
    if any(q["mm3_per_mm"] is not None for q in iv):
        plott.append(("materialtilforsel", "mm3_per_mm", "Tradvolum per banelengde (mm3/mm)"))
    for suffiks, key, ylabel in plott:
        fig, ax = plt.subplots(figsize=(10, 4))
        pts = [(q["s"], q[key]) for q in iv if q[key] is not None]
        ax.plot(*zip(*pts))
        for k, c in enumerate(hjorne_s):
            ax.axvline(c, linestyle="--", alpha=0.6, label="Svingens sentrum" if k == 0 else None)
        if key == "speed":
            if grense is not None:
                ax.axhline(grense, linestyle=":", label=f"{HASTIGHETSGRENSE_PROSENT:g} % av rett fart")
            for k, (_, _, lav) in enumerate(laveste):
                ax.scatter(lav["s"], lav["speed"], marker="x", s=65, zorder=5,
                           label="Laveste fart i hjornesonen" if k == 0 else None)
            ax.legend(loc="best", fontsize=8)
        ax.set(xlabel="Avstand langs bane (mm, mellom posisjoner)", ylabel=ylabel, title=f"{navn}: {ylabel}")
        fig.tight_layout()
        fig.savefig(mappe / f"{navn}_{suffiks}.png", dpi=160)
        plt.close(fig)

    for nr, senter, lav in laveste:
        zoom = [q for q in iv if max(0, senter - ZOOM_HALVBREDDE_MM) <= q["s"] <= senter + ZOOM_HALVBREDDE_MM]
        if not zoom:
            continue
        fig = plt.figure(figsize=(12, 5))
        ax = fig.add_axes((0.08, 0.15, 0.59, 0.72))
        ax.plot([q["s"] for q in zoom], [q["speed"] for q in zoom], linewidth=2, label="Beregnet hastighet")
        if grense is not None:
            ax.axhline(grense, linestyle=":", color="gray",
                       label=f"{HASTIGHETSGRENSE_PROSENT:g} %-grense ({grense:.2f} mm/s)")
        ax.axvline(senter, linestyle="--", alpha=0.6, label="Svingens sentrum")
        ax.scatter(lav["s"], lav["speed"], marker="X", s=95, zorder=5, label="Laveste fart i hjornesonen")
        ax.set(xlabel="Avstand langs banen (mm)", ylabel="Hastighet mellom to maalinger (mm/s)")
        ax.grid(alpha=0.25)
        ax.legend(loc="best", fontsize=8)
        fig.text(0.72, 0.77, "LAVESTE FART NAER HJORNET", fontsize=11, weight="bold")
        fig.text(0.72, 0.59, f"Avstand: {lav['s']:.2f} mm\nFart: {lav['speed']:.3f} mm/s\n"
                             f"dt: {lav['dt']:.3f} s\nX: {lav['x']:.2f} mm\nY: {lav['y']:.2f} mm",
                 fontsize=10, va="top", family="monospace")
        fig.suptitle(f"{navn} - sving {nr}: hastighet", fontsize=13, y=0.97)
        fig.savefig(mappe / f"{navn}_sving_{nr}_detaljer.png", dpi=180, bbox_inches="tight")
        plt.close(fig)


# ---------------- samlede resultater ----------------
def fartsreduksjon(oversikt, ut):
    """Hjorneoversikt_med_fartsreduksjon.csv + ett stolpediagram per test."""
    rader, grupper = [], defaultdict(list)
    for r in oversikt:
        rett, hj = tall(r["Rett_hastighet_mm_s"]), tall(r["Hjorne_hastighet_mm_s"])
        if not rett or hj is None:
            continue
        test, lag = test_og_lag(r["Fil"])
        ny = {"Fil": r["Fil"], "Test": test, "Lag": lag, "Hjorne": r["Hjorne"],
              "Rett_hastighet_mm_s": rett, "Hjorne_hastighet_mm_s": hj,
              "Fartsreduksjon_pct": round((1 - hj / rett) * 100, 3),
              "Volumforhold_hjorne_rett": tall(r["Volumforhold_hjorne_rett"]),
              "Beregnet_hastighet_for_lik_tilforsel_mm_s": tall(r["Beregnet_hastighet_for_lik_tilforsel_mm_s"])}
        rader.append(ny)
        grupper[test].append(ny)
    if not rader:
        return
    rader.sort(key=lambda q: (q["Test"], q["Lag"], q["Hjorne"]))
    skriv_csv(ut / "Hjorneoversikt_med_fartsreduksjon.csv", rader)

    if not LAG_GRAFER:
        return
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    for test, data in sorted(grupper.items()):
        hjorner = sorted({q["Hjorne"] for q in data})
        lag = sorted({q["Lag"] for q in data})
        bredde = 0.8 / len(hjorner)
        fig, ax = plt.subplots(figsize=(11, 5))
        alle = []
        for k, h in enumerate(hjorner):
            pts = sorted((q["Lag"], q["Fartsreduksjon_pct"]) for q in data if q["Hjorne"] == h)
            x = [l + (k - (len(hjorner) - 1) / 2) * bredde for l, _ in pts]
            y = [v for _, v in pts]
            alle += y
            stolper = ax.bar(x, y, width=bredde, label=f"Hjorne {h}" if len(hjorner) > 1 else None)
            for st, v in zip(stolper, y):
                ax.annotate(f"{v:.1f} %", (st.get_x() + st.get_width() / 2, st.get_height()),
                            xytext=(0, 4 if v >= 0 else -4), textcoords="offset points",
                            ha="center", va="bottom" if v >= 0 else "top", fontsize=8)
        ax.axhline(0, color="black", linewidth=0.8)
        ax.set(title=f"{test} - fartsreduksjon per lag", xlabel="Lagnummer", ylabel="Fartsreduksjon (%)")
        ax.set_xticks(lag)
        ax.set_xticklabels([f"{n:02d}" for n in lag])
        lo, hi = min(0, min(alle)), max(0, max(alle))
        marg = max(0.3, (hi - lo) * 0.2)
        ax.set_ylim(lo - marg, hi + marg)
        ax.grid(axis="y", alpha=0.2)
        ax.set_axisbelow(True)
        if len(hjorner) > 1:
            ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(ut / f"Fartsreduksjon_{test}.png", dpi=200)
        plt.close(fig)


def hastighetsforslag(oversikt, ut):
    """Materialokning i hjornet og forslag til fart for lik tilforsel."""
    def gruppe(fil):
        if fil.startswith("L_"):
            return "L"
        if fil.startswith("U_"):
            return "U " + next((p for p in fil.split("_") if p.lower().endswith("pct")), "ukjent")
        return "Annet"

    rader, grupper = [], defaultdict(list)
    for r in oversikt:
        v_r, v_h, w_r, w_h = (tall(r[k]) for k in ("Rett_hastighet_mm_s", "Hjorne_hastighet_mm_s",
                                                   "Rett_wfs_m_min", "Hjorne_wfs_m_min"))
        if None in (v_r, v_h, w_r, w_h) or min(v_r, v_h, w_r, w_h) <= 0:
            continue   # torrkjoring eller mangler WFS
        prog = tall(r.get("Programmert_hastighet_mm_s")) or STANDARD_PROGRAMMERT_FART
        forhold = (w_h / v_h) / (w_r / v_r)   # traadvolum per mm, hjorne / rett
        ekstra = (forhold - 1) * 100
        g = gruppe(r["Fil"])
        rader.append({
            "Fil": r["Fil"], "Gruppe": g, "Hjorne": r["Hjorne"],
            "Rett_hastighet_mm_s": f"{v_r:.2f}", "Hjorne_hastighet_mm_s": f"{v_h:.2f}",
            "Materialendring_prosent": f"{ekstra:.1f}",
            "Onsket_faktisk_hjornefart_mm_s": f"{v_h * forhold:.2f}",
            "Navaerende_programmert_fart_mm_s": f"{prog:.2f}",
            "Eksperimentelt_programforslag_mm_s": f"{prog * forhold:.2f}",
            "Merknad": "Sjekk manuelt – stor økning" if ekstra > VARSEL_MATERIALOKNING_PCT else "Foreløpig anslag",
        })
        grupper[g].append((ekstra, v_h * forhold, prog * forhold))
    if not rader:
        return
    skriv_csv(ut / "Hjornehastighet_per_lag.csv", rader)
    sammendrag = [{
        "Gruppe": g, "Antall": len(v),
        "Gjennomsnitt_materialendring_pct": f"{mean(x[0] for x in v):.1f}",
        "Median_materialendring_pct": f"{median(x[0] for x in v):.1f}",
        "Gjennomsnitt_onsket_faktisk_fart_mm_s": f"{mean(x[1] for x in v):.2f}",
        "Gjennomsnitt_eksperimentelt_programforslag_mm_s": f"{mean(x[2] for x in v):.2f}",
        "Merknad": "Kun estimat – ikke validert på robot",
    } for g, v in sorted(grupper.items())]
    skriv_csv(ut / "Hjornehastighet_oppsummering.csv", sammendrag)
    for s in sammendrag:
        print(f"  {s['Gruppe']}: {s['Antall']} hjorner | ekstra materiale {s['Gjennomsnitt_materialendring_pct']} % | "
              f"forslag programmert fart {s['Gjennomsnitt_eksperimentelt_programforslag_mm_s']} mm/s")


def hjorneanalyse(mappe=""):
    inn, ut = BEHANDLET / mappe, ANALYSE / mappe
    if not inn.is_dir():
        print("Fant ikke mappen:", inn)
        return
    filer = sorted(f for f in inn.rglob("*.csv") if er_l_eller_u(f))
    print(f"Fant {len(filer)} L-/U-filer i {inn.relative_to(BEHANDLET.parent)}")
    oversikt = []
    for fil in filer:
        try:
            oversikt += analyser_fil(fil, inn, ut)
        except Exception as ex:
            print(f"  FEIL {fil.name}: {ex}")
    if not oversikt:
        print("Ingen hjorner med resultat funnet")
        return
    skriv_csv(ut / "Hjorneoversikt.csv", oversikt)
    fartsreduksjon(oversikt, ut)
    hastighetsforslag(oversikt, ut)
    print(f"Hjorneanalyse lagret i {ut.relative_to(BEHANDLET.parent)}")
