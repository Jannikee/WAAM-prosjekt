#!/usr/bin/env python3
"""Felles WAAM banegenerator: RETT, L, U og ÅPEN T.

Bygget rundt de eksisterende WAAM-generatorenes parametere og JBI-format.
Standard: bare XY-forhåndsvisning, IKKE JBI.

T er ETT sammenhengende spor:
 start venstre øverst -> hele toppen -> U til høyre -> tilbake under
 toppen til midten -> L ned -> U i bunnen -> L opp -> venstre
 og stopp like under startpunktet, UTEN avsluttende U-kobling.

U-svingen bruker nå tre MOVC-punkter fra kant-koden (R = d/2):
 p1 = start + (R/2 ut,  R/2 langs)
 p2 = start + (R ut,    R + R/2 langs)
 p3 = sluttpunktet (en senteravstand d fra start)

VIKTIG: Banegenerering er ikke robotvalidering. Kontroller MOVC-/PL-
syntaks, orientering, sikker inn-/utkjøring og sveiseprogram i robotcellen.
"""

import csv
import shutil
from dataclasses import dataclass
from datetime import datetime
from math import ceil, hypot
from pathlib import Path

# ============================================================
# ENDRBARE PARAMETERE  (beholdt fra de tidligere generatorene)
# ============================================================
JOBBNAVN = "UTEST"              # Maks 8 ASCII bokstaver/tall
FORM = "U"                     # "RETT", "L", "U" eller "T"

LAG_JBI = True              # False = kun XY-forhåndsvisning
LAGRE_BILDE = True
VIS_BANE = False          # True = åpne plottvinduet i VS Code
TEST_UTEN_SVEIS = False         # Relevant KUN hvis LAG_JBI=True
LAG_OVERSIKT = True             # Lagrer oversikt (type, parametere, dato) i mappen "Oversikt"

# Basisgeometri og lag
LENGDE = 100.0                 # RETT: hel lengde; L: total; U: per arm
ANTALL_LAG = 15
LAGHOYDE = 1.4
X_START, Y_START, Z_START = 225.0, 210.0, 75.0
VEKSLENDE = True
FLERE_PUNKTER = True
PUNKTAVSTAND = 5.0

# Hastighet - separate innstillinger for rette deler, L og U
SVEISEHASTIGHET = 7.0          # mm/s, rett strekning
HASTIGHET_L = 7.0              # mm/s, ved L-hjørner (90 grader)
HASTIGHET_U = 11.0              # mm/s, ved U-svinger (180 grader)
SONE_L_MM = 10.0               # mm før og etter L-hjørnet
SONE_U_MM = 3.0               # mm før og etter U-svingen

# PL brukes KUN på MOVL-målet i et 90-graders L-hjørne
PL_L = 1                       # None = utelat PL; 1 til 8 = skriv PL=n
ACC = 20
DEC = 20

# U og T: samme definisjon som tidligere U-kode
BEADWIDTH = 11               # mm, nominell strengbredde
OVERLAP = 0.5                  # senteravstand = BEADWIDTH * OVERLAP
# Merk: OVERLAP=0.7 her betyr 70 % av beadwidth i senteravstand,
# og dermed omtrent 30 % geometrisk breddeoverlapp.

# NY ÅPEN T: topplinjen og retursporet ligger én senteravstand fra hverandre.
T_TOPPLENGDE = 100.0          # mm, hele den øvre vannrette banen
T_STAMME_LENGDE = 110.0       # mm, lengden nedover fra underkanten
T_EKSTRA_INNSPENNING = 0.0   # mm, ekstra lengde nederst til å gripe
T_STAMME_SENTER_X = None      # None = midt på toppen; ellers absolutt X i USER
T_SLUTT_X_OFFSET = 0.0        # 0 = slutt rett under start (ikke koblet sammen)

# Sveiseprosess og robot
PROGRAM = "ARGF2"
WAITTIME = 60                 # sekunder etter ARCOF
USER = 9
TOOL = 1
FLYTTHASTIGHET = 11.0       # mm/s, bevegelse uten bue
LEDDHASTIGHET = 0.78        # VJ i prosent
STARTPOS = (225.0, 185.0, 200.0)
SLUTTPOS = (225.0, 185.0, 200.0)

# Brennerens RX, RY, RZ. Dette er ROBOTENS orienteringsverdier,
# ikke nødvendigvis fysisk arbeid-/føringsvinkel i grader.
RX, RY, RZ = 0.0, 0.0, 45.0  
VINKEL_RETT = (RX, RY, RZ)
VINKEL_L = (RX, RY, RZ)
VINKEL_U = (RX, RY, RZ)

BASE_DIR = Path(__file__).resolve().parent
MAKRO = f"MACRO1 MJ#(0) {PROGRAM}"
RCONF = "1," + ",".join(["0"] * 23)

# ============================================================
# DATATYPER OG HJELPEFUNKSJONER
# ============================================================
XY = tuple[float, float]


@dataclass(frozen=True)
class Segment:
    typ: str                     # "linje" eller "u"
    fra: XY
    til: XY
    sving: tuple[XY, ...] = ()   # mellompunkter i U-svingen (MOVC), i kjøreretning

    def snudd(self):
        # Kjøres svingen motsatt vei, reverseres også mellompunktene
        return Segment(self.typ, self.til, self.fra, tuple(reversed(self.sving)))


def avstand(a: XY, b: XY) -> float:
    return hypot(b[0] - a[0], b[1] - a[1])


def linje(a: XY, b: XY) -> Segment:
    return Segment("linje", a, b)


def u_sving(a: XY, b: XY, ut: XY) -> Segment:
    """U-sving fra a til b (avstand d), utbuling i retning `ut` (enhetsvektor).

    Samme punkter som i kant-koden, med R = d/2:
      p1 = a + R/2 * ut + R/2 * t
      p2 = a + R   * ut + (R + R/2) * t
      p3 = b
    der t er enhetsvektoren fra a mot b.
    """
    d = avstand(a, b)
    R = d / 2
    t = ((b[0] - a[0]) / d, (b[1] - a[1]) / d)

    def p(langs, utover):
        return (a[0] + utover * ut[0] + langs * t[0],
                a[1] + utover * ut[1] + langs * t[1])

    p1 = p(R / 2, R / 2)
    p2 = p(R + R / 2, R)
    return Segment("u", a, b, (p1, p2))


def senteravstand() -> float:
    return BEADWIDTH * OVERLAP


""" def valider_innstillinger():
    if FORM not in {"RETT", "L", "U", "T"}:
        raise ValueError('FORM må være "RETT", "L", "U" eller "T".')
    if not (1 <= len(JOBBNAVN) <= 8 and JOBBNAVN.isascii() and JOBBNAVN.isalnum()):
        raise ValueError("JOBBNAVN: 1-8 ASCII bokstaver/tall.")
    if PL_L is not None and (type(PL_L) is not int or not 1 <= PL_L <= 8):
        raise ValueError("PL_L må være None eller et heltall 1-8 (ikke PL=0).")
    if not 1 <= USER <= 63 or not 0 <= TOOL <= 63:
        raise ValueError("Ugyldig USER eller TOOL.")
    if min(LENGDE, LAGHOYDE, SVEISEHASTIGHET, HASTIGHET_L, HASTIGHET_U,
           FLYTTHASTIGHET, BEADWIDTH) <= 0 or ANTALL_LAG < 1:
        raise ValueError("Lengder, hastigheter og ANTALL_LAG må være positive.")
    if not 0 < OVERLAP <= 1:
        raise ValueError("OVERLAP må være mellom 0 og 1 (0 ikke tillatt).")
    if FLERE_PUNKTER and PUNKTAVSTAND <= 0:
        raise ValueError("PUNKTAVSTAND må være positiv.")
    if min(SONE_L_MM, SONE_U_MM) < 0:
        raise ValueError("SONE_L_MM/SONE_U_MM må være >= 0.")
    if FORM == "T":
        if T_TOPPLENGDE <= 0 or T_STAMME_LENGDE <= 0 or T_EKSTRA_INNSPENNING < 0:
            raise ValueError("Ugyldige T-lengder.")
        if not 0 <= T_SLUTT_X_OFFSET < T_TOPPLENGDE / 2:
            raise ValueError("T_SLUTT_X_OFFSET må være mellom 0 og halv topplengde.")
        xm = T_STAMME_SENTER_X if T_STAMME_SENTER_X is not None else X_START + T_TOPPLENGDE / 2
        d = senteravstand()
        if not (X_START + d < xm - d / 2 and xm + d / 2 < X_START + T_TOPPLENGDE - d):
            raise ValueError("T-stammen er for bred/nær kanten. Endre topplengde, senter eller OVERLAP.")
    if min(STARTPOS[2], SLUTTPOS[2]) <= Z_START + (ANTALL_LAG - 1) * LAGHOYDE:
        raise ValueError("Parkposisjonenes Z må ligge over øverste programmerte lag.")
    for navn, vinkel in [("VINKEL_RETT", VINKEL_RETT),
                        ("VINKEL_L", VINKEL_L), ("VINKEL_U", VINKEL_U)]:
        if len(vinkel) != 3:
            raise ValueError(f"{navn} må inneholde (RX, RY, RZ).") """


# ============================================================
# GEOMETRI: de samme bevegelsesprinsippene som gammel L og U
# ============================================================

def generer_segmenter():
    x, y = X_START, Y_START
    d = senteravstand()
    if FORM == "RETT":
        s = [linje((x, y), (x + LENGDE, y))]
    elif FORM == "L":
        h = LENGDE / 2
        s = [linje((x, y), (x + h, y)),
             linje((x + h, y), (x + h, y + h))]
    elif FORM == "U":
        xr = x + LENGDE
        s = [linje((x, y), (xr, y)),
             u_sving((xr, y), (xr, y + d), ut=(1, 0)),
             linje((xr, y + d), (x, y + d))]
    else:
        # ÅPEN T (én sammenhengende bane) -- start og stopp skilt av d.
        xr = x + T_TOPPLENGDE
        xm = T_STAMME_SENTER_X if T_STAMME_SENTER_X is not None else x + T_TOPPLENGDE / 2
        xl, xh = xm - d / 2, xm + d / 2
        yu = y + d
        yb = yu + T_STAMME_LENGDE + T_EKSTRA_INNSPENNING
        s = [
            linje((x, y), (xr-1, y)),                            # Hele toppen
            u_sving((xr, y), (xr, yu), ut=(1, 0)),                # U til høyre
            linje((xr, yu), (xh, yu)),                        # Retur mot midten
            linje((xh, yu), (xh, yb)),                        # L ned langs stamme
            u_sving((xh, yb), (xl, yb), ut=(0, 1)),            # U nederst
            linje((xl, yb), (xl, yu)),                        # Opp langs stammen
            linje((xl, yu), (x + T_SLUTT_X_OFFSET, yu)),       # L til venstre
            # INTET siste U: her slutter sveisingen like under start.
        ]

    """ for i, (a, b) in enumerate(zip(s, s[1:])):
        if avstand(a.til, b.fra) > 0.00001:
            raise ValueError(f"Brutt bane mellom segment {i+1} og {i+2}.") """
    return s


def snu_segmenter(segmenter):
    return [s.snudd() for s in reversed(segmenter)]


def ulike_retninger(s1: Segment, s2: Segment):
    if s1.typ != "linje" or s2.typ != "linje":
        return False
    dx1, dy1 = s1.til[0] - s1.fra[0], s1.til[1] - s1.fra[1]
    dx2, dy2 = s2.til[0] - s2.fra[0], s2.til[1] - s2.fra[1]
    lengde = hypot(dx1, dy1) * hypot(dx2, dy2)
    if lengde <= 1e-9:
        return False
    # 90-graders retningsendringer, ikke 180-graders returer
    cosv = (dx1 * dx2 + dy1 * dy2) / lengde
    return -0.5 < cosv < 0.5


def finn_sone(segmenter, indeks, t):
    """t er relativ posisjon langs rett segment, 0..1.
    Merker også rette strekninger et valgt antall mm før/etter sving.
    """
    seg = segmenter[indeks]
    lengde = avstand(seg.fra, seg.til)
    fra_avstand, til_avstand = t * lengde, (1 - t) * lengde
    for sone, kondisjon in (
        ("U", indeks > 0 and segmenter[indeks - 1].typ == "u" and fra_avstand <= SONE_U_MM + 1e-9),
        ("U", indeks < len(segmenter) - 1 and segmenter[indeks + 1].typ == "u" and til_avstand <= SONE_U_MM + 1e-9),
        ("L", indeks > 0 and ulike_retninger(segmenter[indeks - 1], seg) and fra_avstand <= SONE_L_MM + 1e-9),
        ("L", indeks < len(segmenter) - 1 and ulike_retninger(seg, segmenter[indeks + 1]) and til_avstand <= SONE_L_MM + 1e-9),
    ):
        if kondisjon:
            return sone
    return "RETT"


def baneinstruksjoner(segmenter):
    """List av bevegelser: målpunkt, MOVL/MOVC, sone og PL-bryter.

    En U har nå tre MOVC-mål: de to svingpunktene (p1, p2) og sluttpunktet.
    Startpunktet er allerede foregående MOVL-mål, som i kant-koden.
    """
    resultat = []
    for indeks, seg in enumerate(segmenter):
        if seg.typ == "u":
            for punkt in (*seg.sving, seg.til):
                resultat.append((punkt, "MOVC", "U", False))
            continue

        lengde = avstand(seg.fra, seg.til)
        steg = max(1, ceil(lengde / PUNKTAVSTAND)) if FLERE_PUNKTER else 1
        for i in range(1, steg + 1):
            t = i / steg
            punkt = (seg.fra[0] + (seg.til[0] - seg.fra[0]) * t,
                     seg.fra[1] + (seg.til[1] - seg.fra[1]) * t)
            sone = finn_sone(segmenter, indeks, t)
            er_l_punkt = (
                i == steg
                and indeks < len(segmenter) - 1
                and ulike_retninger(seg, segmenter[indeks + 1])
            )
            resultat.append((punkt, "MOVL", sone, er_l_punkt))
    return resultat


def innstillinger_for(sone):
    if sone == "L":
        return HASTIGHET_L, VINKEL_L
    if sone == "U":
        return HASTIGHET_U, VINKEL_U
    return SVEISEHASTIGHET, VINKEL_RETT


# ============================================================
# XY-FORHÅNDSVISNING (ingen JBI)
# ============================================================

def vis_forhandsvisning(segmenter, filbane=None):
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(12, 6.5))
    for indeks, seg in enumerate(segmenter):
        if seg.typ == "linje":
            px = [seg.fra[0], seg.til[0]]
            py = [seg.fra[1], seg.til[1]]
            ax.plot(px, py, color="royalblue", lw=2.7)
            # Retningspil på midten
            x1 = seg.fra[0] + .44 * (seg.til[0] - seg.fra[0])
            y1 = seg.fra[1] + .44 * (seg.til[1] - seg.fra[1])
            x2 = seg.fra[0] + .57 * (seg.til[0] - seg.fra[0])
            y2 = seg.fra[1] + .57 * (seg.til[1] - seg.fra[1])
            ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                        arrowprops=dict(arrowstyle="-|>", lw=1.7, color="royalblue"))
        else:
            # Svingen vises som rette streker gjennom MOVC-punktene
            # (start -> p1 -> p2 -> slutt). Dette er IKKE en simulering av MOVC.
            pts = [seg.fra, *seg.sving, seg.til]
            ax.plot([p[0] for p in pts], [p[1] for p in pts],
                    color="darkorange", lw=2.7)
            ax.scatter([p[0] for p in seg.sving], [p[1] for p in seg.sving],
                       color="darkorange", s=22, zorder=4)

    start, slutt = segmenter[0].fra, segmenter[-1].til
    ax.scatter([start[0]], [start[1]], color="green", s=65, zorder=6, label="Start")
    ax.scatter([slutt[0]], [slutt[1]], color="crimson", s=65, zorder=6, label="Slutt")
    ax.annotate("Start", start, xytext=(8, -17), textcoords="offset points", ha="left")
    ax.annotate("Slutt", slutt, xytext=(8, 12), textcoords="offset points", ha="left")
    ax.set_title(f"{JOBBNAVN}: {FORM} – åpen sveisebane (lag 1)")
    ax.set_xlabel("X (mm), USER")
    ax.set_ylabel("Y (mm), USER")
    ax.set_aspect("equal", adjustable="datalim")
    ax.invert_yaxis()  # T-stammen peker nedover på bildet
    ax.grid(alpha=.2)
    ax.legend(loc="best")
    fig.tight_layout()
    if filbane is not None:
        filbane.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(filbane, dpi=180)
        print(f"Forhåndsvisning: {filbane}")
    if VIS_BANE:
        plt.show()
    plt.close(fig)


# ============================================================
# JBI FRA EKSISTERENDE KODE: kjøres bare hvis LAG_JBI=True
# ============================================================

def skriv_jbi(segmenter):
    punkter = []
    instruksjoner = ["NOP"]

    def flytt(x, y, z, bevegelse="MOVL", fart=None, vinkel=None, pl=None):
        if vinkel is None:
            vinkel = VINKEL_RETT
        nr = len(punkter)
        punkter.append(f"C{nr:05d}={x:.3f},{y:.3f},{z:.3f},"
                       f"{vinkel[0]:.4f},{vinkel[1]:.4f},{vinkel[2]:.4f}")
        if bevegelse == "MOVJ":
            kommando = f"MOVJ C{nr:05d} VJ={LEDDHASTIGHET:.2f}"
        elif bevegelse == "MOVC":
            kommando = f"MOVC C{nr:05d} V={fart:.1f} ACC={ACC:d} DEC={DEC:d}"
        else:
            kommando = f"MOVL C{nr:05d} V={fart:.1f}"
            if pl is not None:
                # Følg gammel PL-test: unngå ACC/DEC sammen med PL.
                kommando += f" PL={pl:d}"
            else:
                kommando += f" ACC={ACC:d} DEC={DEC:d}"
        instruksjoner.append(kommando)

    def bue_paa():
        if not TEST_UTEN_SVEIS:
            instruksjoner.extend([MAKRO, "ARCON"])

    def bue_av():
        if not TEST_UTEN_SVEIS:
            instruksjoner.extend(["ARCOF", f"TIMER T={WAITTIME}"])

    first = segmenter[0].fra
    flytt(*STARTPOS, bevegelse="MOVJ")
    flytt(first[0], first[1], STARTPOS[2], bevegelse="MOVJ")
    flytt(first[0], first[1], Z_START, fart=FLYTTHASTIGHET)
    siste_xy = first

    for lag in range(ANTALL_LAG):
        z = Z_START + lag * LAGHOYDE
        deler = snu_segmenter(segmenter) if (VEKSLENDE and lag % 2 == 1) else segmenter
        start_xy = deler[0].fra
        if lag > 0:
            if VEKSLENDE:
                flytt(start_xy[0], start_xy[1], z, fart=FLYTTHASTIGHET)
            else:
                flytt(siste_xy[0], siste_xy[1], STARTPOS[2], fart=FLYTTHASTIGHET)
                flytt(start_xy[0], start_xy[1], STARTPOS[2], fart=FLYTTHASTIGHET)
                flytt(start_xy[0], start_xy[1], z, fart=FLYTTHASTIGHET)
        instruksjoner.append(f"*LAG{lag+1}")
        bue_paa()
        for xy, bevegelse, sone, er_l_punkt in baneinstruksjoner(deler):
            fart, vinkel = innstillinger_for(sone)
            pl = PL_L if er_l_punkt else None
            flytt(xy[0], xy[1], z, bevegelse=bevegelse,
                  fart=fart, vinkel=vinkel, pl=pl)
        bue_av()
        siste_xy = deler[-1].til

    flytt(siste_xy[0], siste_xy[1], SLUTTPOS[2], fart=FLYTTHASTIGHET)
    flytt(*SLUTTPOS, bevegelse="MOVJ")
    instruksjoner.append("END")

    header = ["/JOB", f"//NAME {JOBBNAVN}", "//POS",
              f"///NPOS {len(punkter)},0,0,0,0,0", f"///USER {USER}",
              f"///TOOL {TOOL}", "///POSTYPE USER", "///RECTAN",
              f"///RCONF {RCONF}"]
    inst_header = ["//INST", f"///DATE {datetime.now():%Y/%m/%d %H:%M}",
                   "///ATTR SC,RW,RJ", f"////FRAME USER {USER}", "///GROUP1 RB1"]
    mappe = BASE_DIR / "JBI"
    mappe.mkdir(exist_ok=True)
    jbi_fil = mappe / f"{JOBBNAVN}.JBI"
    with jbi_fil.open("w", encoding="utf-8", newline="\r\n") as fh:
        fh.write("\n".join(header + punkter + inst_header + instruksjoner) + "\n")
    print(f"JBI: {jbi_fil}")
    print(f"Posisjoner: {len(punkter)}, lag: {ANTALL_LAG}, "
          f"ARCON: {instruksjoner.count('ARCON')}, "
          f"ARCOF: {instruksjoner.count('ARCOF')}, "
          f"PL: {sum(' PL=' in linje for linje in instruksjoner)}")
    return instruksjoner


# ============================================================
# OVERSIKT: logg over hver kjøring (type sveis, parametere, dato)
# ============================================================

FORM_NAVN = {"RETT": "Rett vegg", "L": "L-vegg (90 grader)",
             "U": "U-vegg (180 grader)", "T": "Åpen T-vegg"}


def banelengde(segmenter) -> float:
    """Sveiselengde for ett lag (U regnes langs punktene i svingen)."""
    total = 0.0
    for s in segmenter:
        pts = [s.fra, *s.sving, s.til]
        total += sum(avstand(a, b) for a, b in zip(pts, pts[1:]))
    return total


def samle_parametere(segmenter):
    """Alle parametere som ble brukt, som (gruppe, navn, verdi)-rader."""
    p = [
        ("Jobb", "JOBBNAVN", JOBBNAVN),
        ("Jobb", "FORM", f"{FORM} ({FORM_NAVN.get(FORM, FORM)})"),
        ("Jobb", "LAG_JBI", LAG_JBI),
        ("Jobb", "TEST_UTEN_SVEIS", TEST_UTEN_SVEIS),
        ("Lag", "ANTALL_LAG", ANTALL_LAG),
        ("Lag", "LAGHOYDE (mm)", LAGHOYDE),
        ("Lag", "VEKSLENDE", VEKSLENDE),
        ("Lag", "X_START, Y_START, Z_START", f"{X_START}, {Y_START}, {Z_START}"),
        ("Lag", "FLERE_PUNKTER", FLERE_PUNKTER),
        ("Lag", "PUNKTAVSTAND (mm)", PUNKTAVSTAND),
        ("Hastighet", "SVEISEHASTIGHET (mm/s)", SVEISEHASTIGHET),
        ("Hastighet", "HASTIGHET_L (mm/s)", HASTIGHET_L),
        ("Hastighet", "HASTIGHET_U (mm/s)", HASTIGHET_U),
        ("Hastighet", "FLYTTHASTIGHET (mm/s)", FLYTTHASTIGHET),
        ("Hastighet", "LEDDHASTIGHET (VJ %)", LEDDHASTIGHET),
        ("Hastighet", "SONE_L_MM / SONE_U_MM", f"{SONE_L_MM} / {SONE_U_MM}"),
        ("Hastighet", "PL_L", PL_L),
        ("Hastighet", "ACC / DEC", f"{ACC} / {DEC}"),
        ("Streng", "BEADWIDTH (mm)", BEADWIDTH),
        ("Streng", "OVERLAP", OVERLAP),
        ("Streng", "Senteravstand (mm)", round(senteravstand(), 3)),
        ("Sveiseprosess", "PROGRAM", PROGRAM),
        ("Sveiseprosess", "WAITTIME (s)", WAITTIME),
        ("Robot", "USER / TOOL", f"{USER} / {TOOL}"),
        ("Robot", "RX, RY, RZ", f"{RX}, {RY}, {RZ}"),
        ("Robot", "STARTPOS", STARTPOS),
        ("Robot", "SLUTTPOS", SLUTTPOS),
    ]
    if FORM in ("RETT", "L", "U"):
        p.insert(4, ("Geometri", "LENGDE (mm)", LENGDE))
    if FORM == "T":
        p[4:4] = [
            ("Geometri", "T_TOPPLENGDE (mm)", T_TOPPLENGDE),
            ("Geometri", "T_STAMME_LENGDE (mm)", T_STAMME_LENGDE),
            ("Geometri", "T_EKSTRA_INNSPENNING (mm)", T_EKSTRA_INNSPENNING),
            ("Geometri", "T_STAMME_SENTER_X", T_STAMME_SENTER_X),
            ("Geometri", "T_SLUTT_X_OFFSET (mm)", T_SLUTT_X_OFFSET),
        ]
    return p


def skriv_oversikt(segmenter, jbi_instruksjoner=None, bildefil=None):
    """Skriver én oversiktsfil per kjøring + legger til en rad i oversikt_alle.csv.

    Filene havner i mappen "Oversikt" ved siden av skriptet og overskrives aldri
    (filnavnet har dato og klokkeslett).
    """
    na = datetime.now()
    mappe = BASE_DIR / "Oversikt"
    mappe.mkdir(exist_ok=True)
    stem = f"{na:%Y-%m-%d_%H%M%S}_{JOBBNAVN}_{FORM}"

    bevegelser = baneinstruksjoner(segmenter)
    n_movl = sum(1 for b in bevegelser if b[1] == "MOVL")
    n_movc = sum(1 for b in bevegelser if b[1] == "MOVC")
    lengde_lag = banelengde(segmenter)
    sveiselengde = lengde_lag * ANTALL_LAG
    teoretisk_hoyde = ANTALL_LAG * LAGHOYDE
    # Grov tid: kun sveisebevegelser, uten oppstart/ventetid
    tid_s = sum(
        avstand(a[0], b[0]) / innstillinger_for(b[2])[0]
        for a, b in zip([(segmenter[0].fra, "", "", False), *bevegelser], bevegelser)
    ) * ANTALL_LAG
    ventetid_s = 0 if TEST_UTEN_SVEIS else WAITTIME * ANTALL_LAG
    start, slutt = segmenter[0].fra, segmenter[-1].til

    linjer = [
        f"OVERSIKT {JOBBNAVN}",
        "=" * 60,
        f"Dato:            {na:%Y-%m-%d %H:%M:%S}",
        f"Type sveis:      {FORM_NAVN.get(FORM, FORM)}",
        f"Jobbnavn (JBI):  {JOBBNAVN}",
        f"JBI generert:    {'Ja' if jbi_instruksjoner is not None else 'Nei (kun forhåndsvisning)'}",
        f"Uten sveis:      {'Ja (TEST_UTEN_SVEIS)' if TEST_UTEN_SVEIS else 'Nei'}",
        "",
        "RESULTAT",
        "-" * 60,
        f"Antall lag:                 {ANTALL_LAG}",
        f"Teoretisk veggehøyde:       {teoretisk_hoyde:.1f} mm ({ANTALL_LAG} x {LAGHOYDE} mm)",
        f"Sveiselengde per lag:       {lengde_lag:.1f} mm",
        f"Sveiselengde totalt:        {sveiselengde:.1f} mm",
        f"Bevegelser per lag:         {n_movl} MOVL + {n_movc} MOVC",
        f"Grov sveisetid (kun bane):  {tid_s / 60:.1f} min (+ {ventetid_s / 60:.1f} min ventetid etter ARCOF)",
        f"Start XY (lag 1):           {start}",
        f"Slutt XY (lag 1):           {slutt}",
    ]
    if jbi_instruksjoner is not None:
        linjer += [
            f"Posisjoner i JBI:           {sum(1 for i in jbi_instruksjoner if i.startswith(('MOVL', 'MOVJ', 'MOVC')))}",
            f"ARCON / ARCOF:              {jbi_instruksjoner.count('ARCON')} / {jbi_instruksjoner.count('ARCOF')}",
        ]

    linjer += ["", "PARAMETERE", "-" * 60]
    gruppe = None
    for g, navn, verdi in samle_parametere(segmenter):
        if g != gruppe:
            linjer.append(f"[{g}]")
            gruppe = g
        linjer.append(f"  {navn:<28} {verdi}")

    linjer += ["", "BANE (lag 1, U-sving vises med MOVC-punkter)", "-" * 60]
    for i, s in enumerate(segmenter, start=1):
        tekst = f"  {i}: {s.typ:5} {s.fra} -> {s.til}"
        if s.sving:
            tekst += "   via " + " ".join(f"({p[0]:.3f}, {p[1]:.3f})" for p in s.sving)
        linjer.append(tekst)

    linjer += ["", "Notater (fyll inn selv etter sveising):", "  ", "  ",
               "", "MERK: Banen er generert, ikke validert på robot."]

    txt = mappe / f"{stem}.txt"
    txt.write_text("\n".join(linjer) + "\n", encoding="utf-8")

    # Kopier forhåndsvisningen hit så bilde og parametere ligger sammen
    if bildefil is not None and Path(bildefil).exists():
        shutil.copy(bildefil, mappe / f"{stem}.png")

    # Samlet logg: én rad per kjøring, åpnes direkte i Excel
    csv_fil = mappe / "oversikt_alle.csv"
    ny = not csv_fil.exists()
    rad = {
        "Dato": f"{na:%Y-%m-%d %H:%M:%S}",
        "Jobbnavn": JOBBNAVN,
        "Type": FORM_NAVN.get(FORM, FORM),
        "JBI": "Ja" if jbi_instruksjoner is not None else "Nei",
        "Uten sveis": "Ja" if TEST_UTEN_SVEIS else "Nei",
        "Antall lag": ANTALL_LAG,
        "Laghoyde mm": LAGHOYDE,
        "Sveisehastighet mm/s": SVEISEHASTIGHET,
        "Hastighet L mm/s": HASTIGHET_L,
        "Hastighet U mm/s": HASTIGHET_U,
        "Beadwidth mm": BEADWIDTH,
        "Overlap": OVERLAP,
        "Senteravstand mm": round(senteravstand(), 3),
        "Lengde mm": T_TOPPLENGDE if FORM == "T" else LENGDE,
        "Program": PROGRAM,
        "Vekslende": "Ja" if VEKSLENDE else "Nei",
        "Sveiselengde totalt mm": round(sveiselengde, 1),
        "Oversiktsfil": txt.name,
    }
    with csv_fil.open("a", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rad), delimiter=";")
        if ny:
            w.writeheader()
        w.writerow(rad)
    print(f"Oversikt: {txt}")
    print(f"Samlet logg: {csv_fil}")


def main():
    #valider_innstillinger()
    segmenter = generer_segmenter()
    print(f"FORM={FORM} | segmenter={len(segmenter)} | "
          f"senteravstand={senteravstand():g} mm")
    print(f"Start XY={segmenter[0].fra}; Slutt XY={segmenter[-1].til}; "
          f"Avstand mellom start/slutt={avstand(segmenter[0].fra, segmenter[-1].til):.2f} mm")
    for i, s in enumerate(segmenter, start=1):
        print(f"  {i}: {s.typ:5} {s.fra} -> {s.til}")
    bilde = BASE_DIR / "Forhandsvisning" / f"{JOBBNAVN}_{FORM}_XY.png" if LAGRE_BILDE else None
    if LAGRE_BILDE or VIS_BANE:
        vis_forhandsvisning(segmenter, bilde)
    instruksjoner = None
    if LAG_JBI:
        print("ADVARSEL: JBI er IKKE validert på robotkontroller. Kontroller alt før kjøring.")
        instruksjoner = skriv_jbi(segmenter)
    else:
        print("Ingen JBI generert (LAG_JBI=False).")
    if LAG_OVERSIKT:
        skriv_oversikt(segmenter, instruksjoner, bilde)


if __name__ == "__main__":
    main()