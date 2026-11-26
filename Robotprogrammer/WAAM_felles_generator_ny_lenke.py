#!/usr/bin/env python3
"""Felles WAAM banegenerator: RETT, L, U, ÅPEN T og I (dobbel T).

Bygget rundt de eksisterende WAAM-generatorenes parametere og JBI-format.
Standard: bare XY-forhåndsvisning, IKKE JBI.

T er ETT sammenhengende spor:
 start venstre øverst -> hele toppen -> U til høyre -> tilbake under
 toppen til midten -> L ned -> U i bunnen -> L opp -> venstre
 og stopp like under startpunktet, UTEN avsluttende U-kobling.

I (dobbel T, hatt oppe og nede) er også ETT sammenhengende spor:
 start venstre øverst -> hele toppen -> U til høyre -> tilbake til
 stammen -> ned stammens høyre side -> ut til høyre i bunnhatten ->
 U til høyre -> hele bunnen mot venstre -> U til venstre -> inn mot
 stammen -> opp stammens venstre side -> venstre og stopp like under start.

U-svingen er en halvsirkel (R = d/2). Siste MOVL ligger 5 mm før
halvsirkelen, deretter tre MOVC-punkter på sirkelen:
 MOVL  5 mm før start          (rett linje)
 MOVC  start  (0 grader)       <- lineær bevegelse hit (Yaskawa)
 MOVC  topp   (90 grader)  = start + (R langs, R ut)
 MOVC  slutt  (180 grader) = start + (2R langs)
Neste MOVL etter svingen er lineær igjen.

VIKTIG: Banegenerering er ikke robotvalidering. Kontroller MOVC-/PL-
syntaks, orientering, sikker inn-/utkjøring og sveiseprogram i robotcellen.
"""

import csv
import shutil
from dataclasses import dataclass
from datetime import datetime
from math import acos, asin, atan2, ceil, cos, degrees, hypot, pi, radians, sin, sqrt, tan
from pathlib import Path

# ============================================================
# ENDRBARE PARAMETERE  (beholdt fra de tidligere generatorene)
# ============================================================
JOBBNAVN = "ITEST"              # Maks 8 ASCII bokstaver/tall
FORM = "I"                     # "RETT", "L", "U", "T" eller "I"

LAG_JBI = True              # False = kun XY-forhåndsvisning
LAGRE_BILDE = True
VIS_BANE = True          # True = åpne plottvinduet i VS Code
TEST_UTEN_SVEIS = False         # Relevant KUN hvis LAG_JBI=True
LAG_OVERSIKT = True             # Lagrer oversikt (type, parametere, dato) i mappen "Oversikt"

# Basisgeometri og lag
LENGDE = 100.0                 # RETT: hel lengde; L: total; U: per arm
ANTALL_LAG = 20
LAGHOYDE = 1.7
X_START, Y_START, Z_START = -75.0, -72.0, 70
VEKSLENDE = True
FLERE_PUNKTER = True
PUNKTAVSTAND = 5.0

# Hastighet - separate innstillinger for rette deler, L og U
SVEISEHASTIGHET = 7.0          # mm/s, rett strekning
HASTIGHET_L = 7.0              # mm/s, ved L-hjørner (90 grader)
HASTIGHET_U = 12.0              # mm/s, ved U-svinger (180 grader)
SONE_L_MM = 10.0               # mm før og etter L-hjørnet
SONE_U_MM = 3.0               # mm før og etter U-svingen

# PL brukes KUN på MOVL-målet i et 90-graders L-hjørne
PL_L = 1                       # None = utelat PL; 1 til 8 = skriv PL=n
ACC = 20
DEC = 20


# U og T: samme definisjon som tidligere U-kode
BEADWIDTH = 7.8             # mm, nominell strengbredde 7.8 eller 8.7
OVERLAP = 0.5               # senteravstand = BEADWIDTH * OVERLAP
# Merk: OVERLAP=0.7 her betyr 70 % av beadwidth i senteravstand,
# og dermed omtrent 30 % geometrisk breddeoverlapp.

# NY ÅPEN T: topplinjen og retursporet ligger én senteravstand fra hverandre.
T_TOPPLENGDE = 100.0          # mm, hele den øvre vannrette banen
T_STAMME_LENGDE = 110.0       # mm, lengden nedover fra underkanten
T_EKSTRA_INNSPENNING = 0.0   # mm, ekstra lengde nederst til å gripe
T_STAMME_SENTER_X = None      # None = midt på toppen; ellers absolutt X i USER
T_SLUTT_X_OFFSET = 0.0        # 0 = slutt rett under start (ikke koblet sammen)

# I: bruker T_TOPPLENGDE, T_STAMME_SENTER_X og T_SLUTT_X_OFFSET over.
# T_STAMME_LENGDE = avstand mellom innsiden av topphatten og innsiden av bunnhatten.
I_BUNNLENGDE = None          # None = samme som T_TOPPLENGDE; bunnhatten sentreres under stammen

# Sveiseprosess og robot
PROGRAM = "ARGF2"
WAITTIME = 30                 # sekunder etter ARCOF

# Vifte og ventetid mellom lag (rekkefolge etter ARCOF: WAITTIME -> vifte paa -> VIFTE_TID -> vent IN# -> vifte av)
VIFTE_MODUS = "av"            # "av" = ingen vifte, "hvert_lag" = etter hvert lag, "kun_slutt" = bare etter siste lag
VIFTE_UTGANG = 9              # OT#(n) som styrer viften
VIFTE_TID = 50                # sekunder viften gaar etter laget
VENT_TEMP = False             # True = vent paa IN#(VENT_INNGANG)=ON etter hvert lag (ikke etter siste)
VENT_INNGANG = 17             # IN#(n) som er ON naar plata er under temperaturgrensen (nivaasignal)
VENT_TIMEOUT = 120            # s: gaar videre selv om signalet uteblir (sikring)
USER = 1
TOOL = 1
FLYTTHASTIGHET = 11.0       # mm/s, bevegelse uten bue
LEDDHASTIGHET = 0.78        # VJ i prosent
STARTPOS = (-107.0, -40.0, 200.0)       # Parkposisjon før sveising
SLUTTPOS = (-107.0, -40.0, 200.0)

# Brennerens RX, RY, RZ. Dette er ROBOTENS orienteringsverdier,
# ikke nødvendigvis fysisk arbeid-/føringsvinkel i grader.
RX, RY, RZ = 0.0, 0.0, -150.0  
VINKEL_RETT = (RX, RY, RZ)
VINKEL_L = (RX, RY, RZ)
VINKEL_U = (RX, RY, RZ)

# BRENNERVINKEL I FORHOLD TIL KJØRERETNINGEN (grader). 0 og 0 = loddrett, som før.
# Vinklene følger banen og speiles automatisk når retningen snur (VEKSLENDE).
SIDEVINKEL = 0.0      # + = brenneren lener ut mot siden UTEN sveis (høyre i
                      #     kjøreretningen på lag 1), buen peker inn mot nabostrengen.
                      # - = motsatt side
KJOREVINKEL = 0.0     # + = stikkende (buen peker framover), - = slepende
# Ved hjørner/svinger reises brenneren opp til loddrett, og legges ned igjen
# på andre siden. Den står loddrett i selve hjørnet.
OPP_VED_L = True      # reis opp ved 90-graders hjørner
OPP_VED_U = True      # reis opp gjennom U-svingene (loddrett gjennom hele svingen)
OPP_NED_MM = 10.0     # mm brenneren bruker på å reise seg før / legge seg ned etter

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
    sving: tuple[XY, ...] = ()   # toppunktet (90 grader) i U-svingen, MOVC

    def snudd(self):
        # Kjøres svingen motsatt vei, reverseres også mellompunktene
        return Segment(self.typ, self.til, self.fra, tuple(reversed(self.sving)))


def avstand(a: XY, b: XY) -> float:
    return hypot(b[0] - a[0], b[1] - a[1])


def linje(a: XY, b: XY) -> Segment:
    return Segment("linje", a, b)


def u_sving(a: XY, b: XY, ut: XY) -> Segment:
    """Halvsirkel fra a til b (avstand d = diameter), utbuling i retning `ut`.

    R = d/2, t = enhetsvektor fra a mot b. MOVC-punkter:
      a (0 grader), topp = a + R*t + R*ut (90 grader), b (180 grader)
    """
    d = avstand(a, b)
    R = d / 2
    t = ((b[0] - a[0]) / d, (b[1] - a[1]) / d)

    def p(langs, utover):
        return (a[0] + utover * ut[0] + langs * t[0],
                a[1] + utover * ut[1] + langs * t[1])

    return Segment("u", a, b, (p(R, R),))


def sirkel_bue(p1: XY, p2: XY, p3: XY, n: int = 40):
    """Punkter langs sirkelbuen gjennom p1 -> p2 -> p3 (slik MOVC tolker
    tre påfølgende MOVC-punkter). Returnerer (punkter, buelengde).
    Ligger punktene på linje, brukes rette streker."""
    ax_, ay = p1; bx, by = p2; cx, cy = p3
    D = 2 * (ax_ * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(D) < 1e-12:
        return [p1, p2, p3], avstand(p1, p2) + avstand(p2, p3)
    a2, b2, c2 = ax_**2 + ay**2, bx**2 + by**2, cx**2 + cy**2
    ux = (a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / D
    uy = (a2 * (cx - bx) + b2 * (ax_ - cx) + c2 * (bx - ax_)) / D
    r = hypot(ax_ - ux, ay - uy)
    v1, v2, v3 = (atan2(q[1] - uy, q[0] - ux) for q in (p1, p2, p3))
    # Velg omløpsretning slik at buen passerer p2
    ccw = lambda a, b: (b - a) % (2 * pi)
    if ccw(v1, v2) <= ccw(v1, v3):
        sveip = ccw(v1, v3)
    else:
        sveip = -ccw(v3, v1)
    from math import cos, sin
    pts = [(ux + r * cos(v1 + sveip * i / n), uy + r * sin(v1 + sveip * i / n))
           for i in range(n + 1)]
    return pts, abs(sveip) * r


def u_bane(seg: Segment):
    """XY-bane for en U: halvsirkel gjennom start, topp og slutt."""
    return sirkel_bue(seg.fra, seg.sving[0], seg.til)


def movc_punkter(seg: Segment):
    """De tre MOVC-målene i U-svingen (start, topp, slutt), i kjørerekkefølge."""
    return [seg.fra, *seg.sving, seg.til]


def senteravstand() -> float:
    return BEADWIDTH * OVERLAP


""" def valider_innstillinger():
    if FORM not in {"RETT", "L", "U", "T", "I"}:
        raise ValueError('FORM må være "RETT", "L", "U", "T" eller "I".')
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
    if FORM in ("T", "I"):
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
    elif FORM == "I":
        # I-FORM / dobbel T (én sammenhengende bane), hatt oppe og nede.
        d2 = d / 2
        xr = x + T_TOPPLENGDE
        xm = T_STAMME_SENTER_X if T_STAMME_SENTER_X is not None else x + T_TOPPLENGDE / 2
        xl, xh = xm - d2, xm + d2
        lb = I_BUNNLENGDE if I_BUNNLENGDE is not None else T_TOPPLENGDE
        xb0, xb1 = xm - lb / 2, xm + lb / 2       # bunnhattens ender
        yu = y + d                                 # topphattens nedre spor
        yb = yu + T_STAMME_LENGDE                  # bunnhattens øvre spor
        yb2 = yb + d                               # bunnhattens nedre spor
        s = [
            linje((x, y), (xr, y)),                        # Hele toppen
            u_sving((xr, y), (xr, yu), ut=(1, 0)),         # U til høyre, oppe
            linje((xr, yu), (xh, yu)),                     # Retur mot stammen
            linje((xh, yu), (xh, yb)),                     # Ned stammens høyre side
            linje((xh, yb), (xb1, yb)),                    # Ut til høyre i bunnhatten
            u_sving((xb1, yb), (xb1, yb2), ut=(1, 0)),     # U til høyre, nede
            linje((xb1, yb2), (xb0, yb2)),                 # Hele bunnen mot venstre
            u_sving((xb0, yb2), (xb0, yb), ut=(-1, 0)),    # U til venstre, nede
            linje((xb0, yb), (xl, yb)),                    # Inn mot stammen
            linje((xl, yb), (xl, yu)),                     # Opp stammens venstre side
            linje((xl, yu), (x + T_SLUTT_X_OFFSET, yu)),   # L til venstre
            # INTET siste U: sveisingen slutter like under start.
        ]
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

    En U har tre MOVC-mål: start, topp og slutt. Linjen foran en U
    stopper 5 mm før start (siste MOVL), så går roboten lineært
    inn til første MOVC-punkt.
    """
    resultat = []
    for indeks, seg in enumerate(segmenter):
        if seg.typ == "u":
            for punkt in movc_punkter(seg):
                resultat.append((punkt, "MOVC", "U", False))
            continue

        lengde = avstand(seg.fra, seg.til)
        neste_er_u = indeks < len(segmenter) - 1 and segmenter[indeks + 1].typ == "u"
        kort = min(5.0, lengde * 0.5) if neste_er_u else 0.0
        brukt = lengde - kort                  # del av linjen som får MOVL-punkter
        steg = max(1, ceil(brukt / PUNKTAVSTAND)) if FLERE_PUNKTER else 1
        for i in range(1, steg + 1):
            t = (i / steg) * brukt / lengde    # relativ posisjon på hele linjen
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
# BRENNERVINKEL: vipp basisorienteringen relativt til kjøreretningen
# ============================================================
# Antar at RX, RY, RZ er Yaskawa-vinkler i USER-rammen (R = Rz*Ry*Rx) og at
# USER-Z peker opp (lagene bygges i +Z). Sjekk alltid uten bue først.

def _matmul(A, B):
    return [[sum(A[i][k] * B[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def _rot_fra_euler(rx, ry, rz):
    a, b, c = radians(rx), radians(ry), radians(rz)
    Rx = [[1, 0, 0], [0, cos(a), -sin(a)], [0, sin(a), cos(a)]]
    Ry = [[cos(b), 0, sin(b)], [0, 1, 0], [-sin(b), 0, cos(b)]]
    Rz = [[cos(c), -sin(c), 0], [sin(c), cos(c), 0], [0, 0, 1]]
    return _matmul(Rz, _matmul(Ry, Rx))


def _euler_fra_rot(R):
    ry = asin(max(-1.0, min(1.0, -R[2][0])))
    return tuple(round(degrees(v), 4) + 0.0
                 for v in (atan2(R[2][1], R[2][2]), ry, atan2(R[1][0], R[0][0])))


def _rodrigues(akse, vinkel):
    n = sqrt(sum(v * v for v in akse))
    if n < 1e-12 or abs(vinkel) < 1e-12:
        return [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    x, y, z = (v / n for v in akse)
    c, s, C = cos(vinkel), sin(vinkel), 1 - cos(vinkel)
    return [[c + x*x*C, x*y*C - z*s, x*z*C + y*s],
            [y*x*C + z*s, c + y*y*C, y*z*C - x*s],
            [z*x*C - y*s, z*y*C + x*s, c + z*z*C]]


def brennerretning(psi, kjore, side):
    """Enhetsvektor fra brenner mot arbeidsstykket (USER). psi = kjøreretning i XY."""
    t = (cos(psi), sin(psi))
    venstre = (-sin(psi), cos(psi))
    k, s = tan(radians(kjore)), tan(radians(side))
    w = (k * t[0] + s * venstre[0], k * t[1] + s * venstre[1], -1.0)
    n = sqrt(sum(v * v for v in w))
    return tuple(v / n for v in w)


def vippet_vinkel(basis, psi, kjore, side):
    """(RX, RY, RZ) for basisorienteringen vippet til ønsket brennerretning."""
    if abs(kjore) < 1e-9 and abs(side) < 1e-9:
        return basis
    w0, w = (0.0, 0.0, -1.0), brennerretning(psi, kjore, side)
    akse = (w0[1]*w[2] - w0[2]*w[1], w0[2]*w[0] - w0[0]*w[2], w0[0]*w[1] - w0[1]*w[0])
    vinkel = acos(max(-1.0, min(1.0, sum(a * b for a, b in zip(w0, w)))))
    return _euler_fra_rot(_matmul(_rodrigues(akse, vinkel), _rot_fra_euler(*basis)))


def _retning(a, b):
    d = avstand(a, b)
    return ((b[0] - a[0]) / d, (b[1] - a[1]) / d)


def hjorner_langs_banen(segmenter):
    """[(s_senter, dpsi, halvbredde, type)] for hver retningsendring langs banen."""
    start, s = [], 0.0
    for seg in segmenter:
        start.append(s)
        pts = [seg.fra, *seg.sving, seg.til]
        s += sum(avstand(a, b) for a, b in zip(pts, pts[1:]))
    ut = []
    for i, seg in enumerate(segmenter):
        if seg.typ == "u":
            pts = [seg.fra, *seg.sving, seg.til]
            lengde = sum(avstand(a, b) for a, b in zip(pts, pts[1:]))
            t_inn = _retning(segmenter[i-1].fra, segmenter[i-1].til) if i > 0 else _retning(seg.fra, seg.sving[0])
            p2 = seg.sving[1]
            kryss = t_inn[0] * (p2[1] - seg.fra[1]) - t_inn[1] * (p2[0] - seg.fra[0])
            ut.append((start[i] + lengde / 2, pi if kryss > 0 else -pi, lengde / 2, "U"))
        elif i + 1 < len(segmenter) and ulike_retninger(seg, segmenter[i + 1]):
            a, b = _retning(seg.fra, seg.til), _retning(segmenter[i+1].fra, segmenter[i+1].til)
            ut.append((start[i + 1], atan2(a[0]*b[1] - a[1]*b[0], a[0]*b[0] + a[1]*b[1]), 0.0, "L"))
    return ut


def brennervinkler(segmenter, side_fortegn=1):
    """(psi, kjørevinkel, sidevinkel) for hvert punkt i baneinstruksjoner(segmenter).

    Brenneren reises lineært opp til loddrett over OPP_NED_MM før hvert hjørne
    (OPP_VED_L / OPP_VED_U), står loddrett i hjørnet/gjennom svingen, og
    legges ned igjen over OPP_NED_MM etterpå. Kjøreretningen dreies gradvis
    gjennom hjørnet slik at en eventuell vinkel som beholdes følger banen.
    """
    hjorner = hjorner_langs_banen(segmenter)
    psi0 = atan2(*reversed(_retning(segmenter[0].fra, segmenter[0].til)))

    def ved(s):
        psi, faktor = psi0, 1.0
        for c, dpsi, h, typ in hjorner:
            bredde = h + max(OPP_NED_MM, 1e-6)
            psi += dpsi * min(1.0, max(0.0, (s - (c - bredde)) / (2 * bredde)))
            if (typ == "L" and OPP_VED_L) or (typ == "U" and OPP_VED_U):
                faktor = min(faktor, 1.0 if OPP_NED_MM <= 0 and abs(s - c) > h
                             else min(1.0, max(0.0, (abs(s - c) - h) / max(OPP_NED_MM, 1e-6))))
        return psi, KJOREVINKEL * faktor, SIDEVINKEL * side_fortegn * faktor

    ut, s, forrige = [], 0.0, segmenter[0].fra
    for xy, *_ in baneinstruksjoner(segmenter):
        s += avstand(forrige, xy)
        forrige = xy
        ut.append(ved(s))
    return ved(0.0), ut


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
            # Svingen: halvsirkel gjennom MOVC start, topp, slutt.
            pts, _ = u_bane(seg)
            ax.plot([p[0] for p in pts], [p[1] for p in pts],
                    color="darkorange", lw=2.7)
            mc = movc_punkter(seg)
            ax.scatter([p[0] for p in mc], [p[1] for p in mc],
                       color="darkorange", s=22, zorder=4)

    if SIDEVINKEL or KJOREVINKEL:
        # Piler: hvor buen peker sett ovenfra (lag 1). Lengde ~ vinkelen.
        _, vinkler = brennervinkler(segmenter, 1)
        for (xy, *_), (psi, kjore, side) in zip(baneinstruksjoner(segmenter), vinkler):
            w = brennerretning(psi, kjore, side)
            if abs(w[0]) + abs(w[1]) > 1e-6:
                ax.annotate("", xy=(xy[0] + 7 * w[0], xy[1] + 7 * w[1]), xytext=xy,
                            arrowprops=dict(arrowstyle="->", lw=0.9, color="crimson"))
        ax.plot([], [], color="crimson",
                label=f"Buens retning (side {SIDEVINKEL:g}°, kjøre {KJOREVINKEL:g}°)")

    start, slutt = segmenter[0].fra, segmenter[-1].til
    ax.scatter([start[0]], [start[1]], color="green", s=65, zorder=6, label="Start")
    ax.scatter([slutt[0]], [slutt[1]], color="crimson", s=65, zorder=6, label="Slutt")
    # Y-aksen er invertert: positiv offset = opp på bildet (mot start øverst)
    ax.annotate("Start", start, xytext=(8, 8), textcoords="offset points", ha="left")
    ax.annotate("Slutt", slutt, xytext=(8, -14), textcoords="offset points", ha="left")
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

    def bue_av(siste=False):
        if TEST_UTEN_SVEIS:
            return
        instruksjoner.extend(["ARCOF", f"TIMER T={WAITTIME}"])
        vifte = VIFTE_MODUS == "hvert_lag" or (VIFTE_MODUS == "kun_slutt" and siste)
        if vifte:
            instruksjoner.extend([f"DOUT OT#({VIFTE_UTGANG}) ON", f"TIMER T={VIFTE_TID:.2f}"])
        if VENT_TEMP and not siste:
            # WAIT sjekker tilstanden: er plata allerede under grensen (signal ON) gaar den videre med en gang
            instruksjoner.append(f"WAIT IN#({VENT_INNGANG})=ON T={VENT_TIMEOUT:.2f}")
        if vifte:
            instruksjoner.append(f"DOUT OT#({VIFTE_UTGANG}) OFF")

    def lagvinkler(deler, lag):
        """Startvinkel + vinkel per punkt. Sidevinkel speiles på lag som kjøres motsatt vei."""
        fortegn = -1 if (VEKSLENDE and lag % 2 == 1) else 1
        (psi0, k0, s0), per_punkt = brennervinkler(deler, fortegn)
        return vippet_vinkel(VINKEL_RETT, psi0, k0, s0), per_punkt

    if VIFTE_MODUS != "av" and not TEST_UTEN_SVEIS:
        instruksjoner.append(f"DOUT OT#({VIFTE_UTGANG}) OFF")
    first = segmenter[0].fra
    v_start, _ = lagvinkler(segmenter, 0)
    flytt(*STARTPOS, bevegelse="MOVJ")
    flytt(first[0], first[1], STARTPOS[2], bevegelse="MOVJ", vinkel=v_start)
    flytt(first[0], first[1], Z_START, fart=FLYTTHASTIGHET, vinkel=v_start)
    siste_xy = first

    for lag in range(ANTALL_LAG):
        z = Z_START + lag * LAGHOYDE
        deler = snu_segmenter(segmenter) if (VEKSLENDE and lag % 2 == 1) else segmenter
        start_xy = deler[0].fra
        v_start, vinkler = lagvinkler(deler, lag)
        if lag > 0:
            if VEKSLENDE:
                flytt(start_xy[0], start_xy[1], z, fart=FLYTTHASTIGHET, vinkel=v_start)
            else:
                flytt(siste_xy[0], siste_xy[1], STARTPOS[2], fart=FLYTTHASTIGHET)
                flytt(start_xy[0], start_xy[1], STARTPOS[2], fart=FLYTTHASTIGHET, vinkel=v_start)
                flytt(start_xy[0], start_xy[1], z, fart=FLYTTHASTIGHET, vinkel=v_start)
        instruksjoner.append(f"*LAG{lag+1}")
        bue_paa()
        for (xy, bevegelse, sone, er_l_punkt), (psi, kjore, side) in zip(baneinstruksjoner(deler), vinkler):
            fart, vinkel = innstillinger_for(sone)
            vinkel = vippet_vinkel(vinkel, psi, kjore, side)
            pl = PL_L if er_l_punkt else None
            flytt(xy[0], xy[1], z, bevegelse=bevegelse,
                  fart=fart, vinkel=vinkel, pl=pl)
        bue_av(siste=(lag == ANTALL_LAG - 1))
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
             "U": "U-vegg (180 grader)", "T": "Åpen T-vegg",
             "I": "I-vegg (dobbel T)"}


def banelengde(segmenter) -> float:
    """Sveiselengde for ett lag (U regnes langs sirkelbuen)."""
    total = 0.0
    for s in segmenter:
        total += u_bane(s)[1] if s.typ == "u" else avstand(s.fra, s.til)
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
        ("Vifte/vent", "VIFTE_MODUS / VIFTE_TID (s)", f"{VIFTE_MODUS} / {VIFTE_TID}"),
        ("Vifte/vent", "VENT_TEMP / IN# / timeout (s)", f"{VENT_TEMP} / {VENT_INNGANG} / {VENT_TIMEOUT}"),
        ("Robot", "USER / TOOL", f"{USER} / {TOOL}"),
        ("Robot", "RX, RY, RZ", f"{RX}, {RY}, {RZ}"),
        ("Brennervinkel", "SIDEVINKEL (grader)", SIDEVINKEL),
        ("Brennervinkel", "KJOREVINKEL (grader)", KJOREVINKEL),
        ("Brennervinkel", "OPP_VED_L / OPP_VED_U", f"{OPP_VED_L} / {OPP_VED_U}"),
        ("Brennervinkel", "OPP_NED_MM", OPP_NED_MM),
        ("Robot", "STARTPOS", STARTPOS),
        ("Robot", "SLUTTPOS", SLUTTPOS),
    ]
    if FORM in ("RETT", "L", "U"):
        p.insert(4, ("Geometri", "LENGDE (mm)", LENGDE))
    if FORM in ("T", "I"):
        p[4:4] = [
            ("Geometri", "T_TOPPLENGDE (mm)", T_TOPPLENGDE),
            ("Geometri", "T_STAMME_LENGDE (mm)", T_STAMME_LENGDE),
            ("Geometri", "T_EKSTRA_INNSPENNING (mm)", T_EKSTRA_INNSPENNING),
            ("Geometri", "T_STAMME_SENTER_X", T_STAMME_SENTER_X),
            ("Geometri", "T_SLUTT_X_OFFSET (mm)", T_SLUTT_X_OFFSET),
        ]
    if FORM == "I":
        p.insert(9, ("Geometri", "I_BUNNLENGDE (mm)", I_BUNNLENGDE))
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

    linjer += ["", "BANE (lag 1, U-sving: MOVC start, topp, slutt)", "-" * 60]
    for i, s in enumerate(segmenter, start=1):
        tekst = f"  {i}: {s.typ:5} {s.fra} -> {s.til}"
        if s.typ == "u":
            tekst += "   MOVC " + " ".join(f"({p[0]:.3f}, {p[1]:.3f})" for p in movc_punkter(s))
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
        "Lengde mm": T_TOPPLENGDE if FORM in ("T", "I") else LENGDE,
        "Program": PROGRAM,
        "Vekslende": "Ja" if VEKSLENDE else "Nei",
        "Sveiselengde totalt mm": round(sveiselengde, 1),
        "Oversiktsfil": txt.name,
        "Sidevinkel grader": SIDEVINKEL,
        "Kjorevinkel grader": KJOREVINKEL,
    }
    if not ny:
        # Eldre logg uten vinkelkolonnene: skriv fila på nytt med de nye kolonnene
        with csv_fil.open(encoding="utf-8-sig", newline="") as fh:
            gamle = list(csv.DictReader(fh, delimiter=";"))
        if gamle and set(rad) - set(gamle[0]):
            with csv_fil.open("w", encoding="utf-8-sig", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=list(rad), delimiter=";", restval="")
                w.writeheader()
                w.writerows({k: r.get(k, "") for k in rad} for r in gamle)
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