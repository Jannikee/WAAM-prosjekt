"""Felles hjelpefunksjoner og mappeoppsett for databehandlingen.

Om loggdataene
--------------
Loggeren skriver EN rad per sekund (1 Hz) i kolonnen "timestamp", men hver
rad inneholder ca. 4 S-maalinger (robot) og 4 W-maalinger (sveisemaskin),
hver med sitt eget klokkeslett. Selve maalefrekvensen er altsaa 4 Hz
(ca. 0,25 s mellom hver S- og hver W-maaling).

  * Ca. 30 % av W-maalingene er eksakte kopier av forrige W-maaling
    (sveisemaskinen oppdaterer litt sjeldnere enn loggeren spor).
  * W_kJ er en energiteller som nullstilles hver gang buen tennes.
    De forste 1-3 W-verdiene i en fil kan derfor vaere gammel verdi fra
    forrige lag for den hopper til 0.
"""
import csv
import math
import re
from datetime import datetime
from pathlib import Path

# ============================ MAPPER ============================
BASE_DIR = Path(__file__).resolve().parent
UBEHANDLET = BASE_DIR / "Ubehandlet"
BEHANDLET = BASE_DIR / "Behandlet"
ANALYSE = BASE_DIR / "Analyse_L_U"
RAPPORT = BASE_DIR / "Rapport"
EXCEL_FIL = BASE_DIR / "Vegg_test_str_målinger.xlsx"

STANDARD_TRAD_MM = 1.2   # brukes naar mappenavnet ikke sier noe om traad

# ===================== KOLONNER I BEHANDLEDE FILER =====================
LOGG_KOLONNER = [
    "time", "c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8",
    "S_x", "S_y", "S_z", "S_nx", "S_ny", "S_nz", "S_v", "S_i", "S_wfs",
    "W_I", "W_V", "W_WFS", "W_kW", "W_kJ",
    "R_1", "R_2", "R_3", "R_4", "R_5", "R_6",
    "K_1", "K_2", "K_3", "K_4", "K_5", "K_6", "J_job", "word", "rule_log",
]
META_KOLONNER = [
    "Sveis", "Lag", "Testtype", "Strom_settpunkt_A", "Hastighet_settpunkt_mm_s",
    "Trad_mm", "Overlapp_prosent", "Beskrivelse", "Dybde_mm", "Bredde_mm",
    "Steghoyde_brukt_mm", "Steghoyde_faktisk_mm", "Kommentar",
]


# ============================ TALL ============================
def tall(v):
    """Tekst -> float. Godtar komma som desimaltegn. Tom/ugyldig -> None."""
    if v is None or str(v).strip() == "":
        return None
    try:
        return float(str(v).replace(",", "."))
    except ValueError:
        return None


def med(verdier):
    from statistics import median
    v = [x for x in verdier if x is not None]
    return median(v) if v else None


def rund(v, d=2):
    return None if v is None or not math.isfinite(v) else round(v, d)


def tid(tekst):
    try:
        return datetime.fromisoformat((tekst or "").strip())
    except ValueError:
        return None


# ============================ FILNAVN ============================
def test_og_lag(filnavn):
    """'L_7_80_PL_8_Lag_13.csv' -> ('L_7_80_PL_8', 13)."""
    m = re.fullmatch(r"(.+)_Lag_(\d+)", Path(filnavn).stem, re.I)
    return (m.group(1), int(m.group(2))) if m else (Path(filnavn).stem, 0)


def er_l_eller_u(fil):
    return fil.parent.name.upper().startswith(("L_", "U_")) or fil.name.upper().startswith(("L_", "U_"))


def tolk_mappenavn(navn):
    """Les mappenavn: [TYPE_]STROM_FART[_overlapp][_trad][_PL..][_fri beskrivelse].

    Eksempler: 130_8, L_80_7_1, U_80_7_50_1, L_7_80_PL_8, U_80_7_NoD_K.
    'AV' i stedet for strom (L_7_AV_PL_0) betyr torrkjoring uten bue.
    Hvis forste tall er minst (L_7_80) tolkes det som FART_STROM og byttes om.
    Returnerer None hvis navnet ikke kan tolkes.
    """
    deler = navn.split("_")
    type_ = "Rett"
    if deler[0].upper() in {"L", "U", "TEMP", "T"}:
        type_ = deler.pop(0).upper()
    if len(deler) < 2:
        return None

    torrkjoring = deler[1].upper() == "AV"
    a, b = tall(deler[0]), (None if torrkjoring else tall(deler[1]))
    if a is None or (b is None and not torrkjoring):
        return None
    if torrkjoring:
        strom, fart = None, a
    elif a < b:          # L_7_80 = 7 mm/s, 80 A
        strom, fart = b, a
    else:
        strom, fart = a, b

    rest = deler[2:]
    ovrige, har_pl, i = [], torrkjoring, 0
    while i < len(rest):
        tok = rest[i].upper()
        if tok == "PL":
            har_pl = True
            i += 1
            if i < len(rest) and re.fullmatch(r"[0-8]|AV|OFF|NONE|UTEN", rest[i], re.I):
                i += 1
            continue
        if re.fullmatch(r"PL(?:[0-8]|AV|OFF|NONE|UTEN)", tok):
            har_pl = True
            i += 1
            continue
        ovrige.append(rest[i])
        i += 1

    # Skill tall (med/uten enhet) fra fri beskrivelse
    mm, pct, rene, beskrivelse = [], [], [], []
    for tok in ovrige:
        m = re.fullmatch(r"(\d+(?:[.,]\d+)?)(mm|pct|%)?", tok, re.I)
        if not m:
            beskrivelse.append(tok)
            continue
        enhet = (m.group(2) or "").lower()
        (mm if enhet == "mm" else pct if enhet in {"pct", "%"} else rene).append(tall(m.group(1)))
    if len(mm) > 1 or len(pct) > 1:
        return None
    trad = mm[0] if mm else None
    overlapp = pct[0] if pct else None

    if type_ == "U" and len(rene) == 2 and trad is None and overlapp is None:
        overlapp, trad = rene                      # U_80_7_50_1
    elif len(rene) == 1 and trad is None:
        trad = rene[0]                             # L_80_7_1
    elif len(rene) == 1 and type_ == "U" and overlapp is None:
        overlapp = rene[0]
    elif rene:
        return None

    return dict(type=type_, strom=strom, fart=fart,
                trad=trad if trad is not None else STANDARD_TRAD_MM,
                overlapp=overlapp, har_pl=har_pl, torrkjoring=torrkjoring,
                beskrivelse="_".join(beskrivelse), opprinnelig_navn=navn)


# ======================= LES BEHANDLEDE FILER =======================
def les_behandlet(fil):
    """Les en behandlet lagfil.

    Returnerer (meta, S, W):
      meta: forste rad (metadata-kolonnene)
      S: robotmaalinger sortert paa tid, dict(t, x, y, z, v, i, wfs)
         (S_v/S_i/S_wfs er robotens avlesning av spenning/strom/WFS)
      W: sveisemaskinmaalinger sortert paa tid, dict(t, i, v, wfs, kw, kj)
    """
    meta, S, W = {}, [], []
    with fil.open(encoding="utf-8-sig", newline="") as fh:
        for rad in csv.DictReader(fh):
            if not meta:
                meta = rad
            t = tid(rad.get("time"))
            if t is None:
                continue
            x, y, z = (tall(rad.get(k)) for k in ("S_x", "S_y", "S_z"))
            if None not in (x, y, z):
                S.append(dict(t=t, x=x, y=y, z=z, v=tall(rad.get("S_v")),
                              i=tall(rad.get("S_i")), wfs=tall(rad.get("S_wfs"))))
            wi = tall(rad.get("W_I"))
            if wi is not None:
                W.append(dict(t=t, i=wi, v=tall(rad.get("W_V")), wfs=tall(rad.get("W_WFS")),
                              kw=tall(rad.get("W_kW")), kj=tall(rad.get("W_kJ"))))
    S.sort(key=lambda q: q["t"])
    W.sort(key=lambda q: q["t"])
    return meta, S, W


def skriv_csv(sti, rader, felt=None):
    sti.parent.mkdir(parents=True, exist_ok=True)
    felt = felt or list(rader[0])
    with sti.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=felt, lineterminator="\r\n")
        w.writeheader()
        w.writerows(rader)
