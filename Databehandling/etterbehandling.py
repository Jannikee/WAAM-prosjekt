"""Steg 1: Ubehandlet/<mappe> -> Behandlet/<mappe>.

Gjor raaloggen (1 Hz-rader med 4 Hz-maalinger pakket inni) om til en CSV med
EN rad per maaling og 38 loggkolonner + metadata fra mappenavn og Excel.

To typer testmapper:
  * Vanlig sveis: en raafil per lag (a.csv, b.csv, ...). Lagene nummereres
    etter starttid. Er det mer enn MAKS_PAUSE_MIN mellom to filer hoppes
    hele mappen over (kan vaere to ulike sveiser i samme mappe).
  * Torrkjoring (mappenavn med _AV_, f.eks. L_7_AV_PL_8): en raafil med
    alle lag. Lagene skilles fra hverandre paa Z-hoyde.
"""
import csv
from datetime import datetime
from math import hypot
from statistics import median

from felles import (BEHANDLET, EXCEL_FIL, LOGG_KOLONNER, META_KOLONNER,
                    UBEHANDLET, tall, tid, tolk_mappenavn)

# ======================== ENDRBARE VERDIER ========================
MAKS_PAUSE_MIN = 5
MAPPE_TIL_SVEIS = {}        # f.eks. {'130_10': 5} hvis Excel-match er tvetydig

# Torrkjoring (deles i lag etter Z)
ANTALL_LAG = 15
LAGHOYDE_MM = 1.8
Z_RETNING = 1               # 1 = storre S_z for hvert nytt lag
Z_TOLERANSE_MM = 0.85
BANELENGDE_MM = (105.0, 135.0)   # gyldig XY-lengde per lag
MIN_S_PUNKTER_PER_LAG = 40
# ================================================================

KOL = {navn: i for i, navn in enumerate(LOGG_KOLONNER)}


# -------------------- raalogg -> rader --------------------
def _skaler(raw, faktor, fmt):
    try:
        s = format(float(raw) * faktor, fmt)
    except (TypeError, ValueError):
        return raw
    return s.rstrip("0").rstrip(".") if "." in s else s


def _del(sample):
    pos = sample.find(" ")
    return (sample[:pos], sample[pos + 1:]) if pos > 0 else ("", sample)


def les_raalogg(kilde):
    """En raafil -> liste med 38-kolonners rader (en per maaling/hendelse), sortert paa tid."""
    rader = []
    with kilde.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if not header:
            raise ValueError("Tom CSV-fil")
        treff = [i for i, n in enumerate(header) if n.strip().lower() == "stream"]
        if len(treff) != 1 or not 1 <= treff[0] <= 9:
            raise ValueError("Forventet en stream-kolonne etter 0-8 c-kolonner")
        antall_c = treff[0] - 1

        for felt in reader:
            if not any(f.strip() for f in felt):
                continue
            loggtid = felt[0].strip()
            dato = loggtid[:10] if len(loggtid) >= 10 else ""
            stream = felt[1 + antall_c] if len(felt) > 1 + antall_c else ""
            events = felt[2 + antall_c] if len(felt) > 2 + antall_c else ""

            def ny(klokke):
                rad = [""] * len(LOGG_KOLONNER)
                rad[0] = f"{dato}T{klokke}" if dato and klokke else klokke
                return rad

            # Maalinger: "hh:mm:ss.fff S,x,y,z,nx,ny,nz,v,i,wfs" / "... W,I,V,WFS,kW,kJ"
            for sample in stream.split(";"):
                if not sample.strip():
                    continue
                klokke, kropp = _del(sample.strip())
                rad = ny(klokke)
                w = kropp.split(",")
                t = w[0].strip().upper()
                if t == "S":
                    for k, v in enumerate(w[1:10]):
                        rad[KOL["S_x"] + k] = v
                    rad[KOL["S_v"]] = _skaler(rad[KOL["S_v"]], .01, ".2f")
                    rad[KOL["S_i"]] = _skaler(rad[KOL["S_i"]], .1, ".1f")
                    rad[KOL["S_wfs"]] = _skaler(rad[KOL["S_wfs"]], .01, ".2f")
                elif t == "W":
                    for k, v in enumerate(w[1:6]):
                        rad[KOL["W_I"] + k] = v
                elif t:
                    rad[KOL["word"]] = kropp
                rader.append(rad)

            # Hendelser fra robot/regel-motor
            for ev in events.split(";"):
                if not ev.strip():
                    continue
                klokke, kropp = _del(ev.strip())
                rad = ny(klokke)
                if kropp.startswith("RX:"):
                    ord_ = kropp[3:]
                    w = ord_.split(",")
                    t = w[0].strip().upper()
                    if t in ("K", "R") and len(w) > 1:
                        start = KOL["K_1"] if t == "K" else KOL["R_1"]
                        for k, v in enumerate(w[1:7]):
                            rad[start + k] = v
                    elif len(t) > 1 and t.startswith("J"):
                        rad[KOL["J_job"]] = ord_[1:]
                    rad[KOL["word"]] = kropp
                elif kropp.startswith("R:"):
                    rad[KOL["rule_log"]] = kropp[2:]
                else:
                    rad[KOL["word"]] = kropp
                rader.append(rad)

            # Loggerens c1..c8 (1 Hz)
            c = [felt[1 + k] if len(felt) > 1 + k else "" for k in range(min(antall_c, 8))]
            if any(c):
                rad = [""] * len(LOGG_KOLONNER)
                rad[0] = loggtid
                rad[1:1 + len(c)] = c
                rader.append(rad)

    rader.sort(key=lambda r: r[0])
    return rader


def tidsrom(kilde):
    """Forste og siste logger-timestamp i raafila (ikke Windows-filtid)."""
    tider = []
    with kilde.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        next(reader, None)
        for felt in reader:
            if felt and (t := tid(felt[0])) is not None:
                tider.append(t)
    if not tider:
        raise ValueError(f"Mangler lesbare tidsstempler: {kilde.name}")
    return min(tider), max(tider)


# -------------------- metadata --------------------
def les_excel():
    from openpyxl import load_workbook
    wb = load_workbook(EXCEL_FIL, read_only=True, data_only=True)
    ut = []
    for c in wb.active.iter_rows(min_row=2, max_col=9, values_only=True):
        sveis, trad, strom, fart, dybde, bredde, steg, faktisk, kommentar = c
        if None in (tall(sveis), tall(strom), tall(fart)):
            continue   # Dag 1, Dag 2 ... og tomme rader
        ut.append(dict(sveis=int(tall(sveis)), trad=tall(trad), strom=tall(strom),
                       fart=tall(fart), dybde=dybde, bredde=bredde, steg=steg,
                       faktisk=faktisk, kommentar=kommentar))
    wb.close()
    return ut


def finn_excelrad(mappe, p, excel):
    """Rette sveiser (uten beskrivelse) slaas opp i Excel paa strom/fart/traad."""
    if p["type"] != "Rett" or p["beskrivelse"] or p["har_pl"]:
        return None, "Spesialtest (uten Excel-verdier)"
    kand = [r for r in excel if (r["strom"], r["fart"], r["trad"]) == (p["strom"], p["fart"], p["trad"])]
    if mappe.name in MAPPE_TIL_SVEIS:
        kand = [r for r in kand if r["sveis"] == MAPPE_TIL_SVEIS[mappe.name]]
    if len(kand) == 1:
        return kand[0], f"Sveis {kand[0]['sveis']}"
    if kand:
        return None, "Flere mulige sveiser: " + ", ".join(str(r["sveis"]) for r in kand)
    return None, "Ingen entydig match i Excel"


def metadata(p, excelrad, lag):
    r = excelrad or {}
    return [r.get("sveis", ""), lag, p["type"],
            p["strom"] if p["strom"] is not None else "", p["fart"], p["trad"],
            p["overlapp"] if p["overlapp"] is not None else "", p["beskrivelse"],
            r.get("dybde", ""), r.get("bredde", ""), r.get("steg", ""),
            r.get("faktisk", ""), r.get("kommentar", "")]


def filprefiks(p, excelrad):
    if p["har_pl"] or p["beskrivelse"]:
        return p["opprinnelig_navn"]      # PL-varianter og beskrivelser blandes aldri
    g = lambda v: f"{v:g}"
    if excelrad is not None:
        return f"Sveis_{excelrad['sveis']}_{g(p['strom'])}_{g(p['fart'])}"
    navn = f"{p['type']}_{g(p['strom'])}_{g(p['fart'])}"
    if p["overlapp"] is not None:
        navn += f"_{g(p['overlapp'])}pct"
    return navn + f"_{g(p['trad'])}mm"


def skriv_lag(sti, meta, rader):
    sti.parent.mkdir(parents=True, exist_ok=True)
    with sti.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, lineterminator="\r\n")
        w.writerow(META_KOLONNER + LOGG_KOLONNER)
        w.writerows(meta + r for r in rader)


# -------------------- torrkjoring: del i lag etter Z --------------------
def _s_punkter(rader):
    ut = []
    for r in rader:
        x, y, z = (tall(r[KOL["S_x"] + k]) for k in range(3))
        if None not in (x, y, z) and (t := tid(r[0])) is not None:
            ut.append(dict(t=t, x=x, y=y, z=z))
    return ut


def _forste_lag_z(s):
    """Forste lange horisontale strekning: 20 punkter, >=25 mm XY, nesten konstant Z."""
    n = 20
    for start in range(len(s) - n + 1):
        del_ = s[start:start + n]
        steg = [(hypot(b["x"] - a["x"], b["y"] - a["y"]), abs(b["z"] - a["z"])) for a, b in zip(del_, del_[1:])]
        if sum(d for d, _ in steg) >= 25 and max(d for d, _ in steg) <= 4 and max(dz for _, dz in steg) <= 0.12:
            return median(q["z"] for q in del_)
    raise ValueError("Fant ingen stabil horisontal startbane for lag 1")


def del_i_lag(rader):
    s = _s_punkter(rader)
    if len(s) < ANTALL_LAG * MIN_S_PUNKTER_PER_LAG:
        raise ValueError(f"For faa S-maalinger: {len(s)}")
    z0 = _forste_lag_z(s)
    print(f"  Z for lag 1: {z0:.3f} mm (automatisk)")
    forrige_slutt, lag = -1, {}
    for nr in range(1, ANTALL_LAG + 1):
        niva = z0 + Z_RETNING * (nr - 1) * LAGHOYDE_MM
        idx = [i for i, q in enumerate(s) if i > forrige_slutt and abs(q["z"] - niva) <= Z_TOLERANSE_MM]
        # sammenhengende sekvenser, velg den lengste i XY
        sekv = []
        for i in idx:
            if sekv and i == sekv[-1][-1] + 1:
                sekv[-1].append(i)
            else:
                sekv.append([i])
        if not sekv:
            raise ValueError(f"Lag {nr}: ingen S-punkter naer Z={niva:.3f}")
        xy = lambda run: sum(hypot(s[b]["x"] - s[a]["x"], s[b]["y"] - s[a]["y"]) for a, b in zip(run, run[1:]))
        run = max(sekv, key=xy)
        lengde = xy(run)
        if len(run) < MIN_S_PUNKTER_PER_LAG or not BANELENGDE_MM[0] <= lengde <= BANELENGDE_MM[1]:
            raise ValueError(f"Lag {nr}: {len(run)} S-punkter, XY-lengde {lengde:.1f} mm. Sjekk Z-ankeret.")
        t0, t1 = s[run[0]]["t"], s[run[-1]]["t"]
        lag[nr] = [r for r in rader if (t := tid(r[0])) is not None and t0 <= t <= t1]
        forrige_slutt = run[-1]
        print(f"  Lag {nr:02}: Z={niva:9.3f}, S-punkter={len(run):3}, XY={lengde:6.1f} mm")
    return lag


# -------------------- hovedfunksjon --------------------
def etterbehandle(mappe="", skriv=True, overskriv=False):
    """Behandle alle testmapper under Ubehandlet/<mappe>."""
    inn, ut = UBEHANDLET / mappe, BEHANDLET / mappe
    if not inn.is_dir():
        print("Fant ikke radatamappen:", inn)
        return
    excel = les_excel() if EXCEL_FIL.is_file() else []
    print("MODUS:", "LAGRE" if skriv else "FORHANDSVISNING (skriver ingenting)")
    ok, hoppet = 0, 0

    for testmappe in sorted([inn, *inn.rglob("*")]):
        if not testmappe.is_dir():
            continue
        filer = [f for f in testmappe.glob("*.csv") if not f.name.lower().endswith("_static.csv")]
        if not filer:
            continue
        rel = testmappe.relative_to(UBEHANDLET)
        print(f"\nMAPPE: {rel}")
        p = tolk_mappenavn(testmappe.name)
        if p is None:
            print("  HOPPER OVER: mappenavnet kan ikke tolkes")
            hoppet += len(filer)
            continue

        # Lag liste med (lagnummer, metadata-excelrad, rader-funksjon)
        try:
            if p["torrkjoring"]:
                excelrad = None
                if len(filer) > 1:   # bruk storste fil (de andre er avbrutte forsok)
                    filer = [max(filer, key=lambda f: f.stat().st_size)]
                    print(f"  Flere raafiler, bruker storste: {filer[0].name}")
                lagdata = del_i_lag(les_raalogg(filer[0]))
                plan = [(nr, (lambda r=r: r)) for nr, r in lagdata.items()]
            else:
                excelrad, status = finn_excelrad(testmappe, p, excel)
                print("  Excel:", status)
                if p["type"] == "Rett" and not p["beskrivelse"] and excelrad is None:
                    print("  HOPPER OVER: ma identifisere riktig sveis forst")
                    hoppet += len(filer)
                    continue
                tider = sorted(((f, *tidsrom(f)) for f in filer), key=lambda x: x[1])
                problem = []
                for a, b in zip(tider, tider[1:]):
                    pause = (b[1] - a[2]).total_seconds() / 60
                    if pause > MAKS_PAUSE_MIN:
                        problem.append(f"{a[0].name} -> {b[0].name}: {pause:.1f} min pause")
                    elif pause < 0:
                        problem.append(f"{a[0].name} -> {b[0].name}: overlappende tidsrom")
                if problem:
                    print("  HOPPER OVER: mulig ny sveis / tidsproblem:")
                    for x in problem:
                        print("   ", x)
                    hoppet += len(filer)
                    continue
                plan = [(nr, (lambda f=f: les_raalogg(f))) for nr, (f, _, _) in enumerate(tider, 1)]
                for nr, (f, _, _) in enumerate(tider, 1):
                    print(f"  {f.name} -> Lag {nr:02d}")
        except Exception as ex:
            print("  HOPPER OVER:", ex)
            hoppet += len(filer)
            continue

        prefiks = filprefiks(p, excelrad)
        mal = [(ut / testmappe.relative_to(inn) / f"{prefiks}_Lag_{nr:02d}.csv", nr, hent) for nr, hent in plan]
        finnes = [s for s, _, _ in mal if s.exists()]
        if finnes and not overskriv:
            print(f"  HOPPER OVER: {len(finnes)} resultatfiler finnes allerede (bruk --overskriv)")
            hoppet += len(mal)
            continue
        if not skriv:
            print(f"  Ville skrevet {len(mal)} filer: {prefiks}_Lag_XX.csv")
            ok += len(mal)
            continue
        for sti, nr, hent in mal:
            try:
                rader = hent()
                skriv_lag(sti, metadata(p, excelrad, nr), rader)
                ok += 1
            except Exception as ex:
                print(f"    FEIL lag {nr}: {ex}")
                if sti.exists():
                    sti.unlink()
                hoppet += 1
        print(f"  Lagret {len(mal)} filer i {sti.parent.relative_to(BEHANDLET.parent)}")

    print(f"\nFerdig etterbehandling: {ok} filer {'skrevet' if skriv else 'planlagt'}, {hoppet} hoppet over.")
