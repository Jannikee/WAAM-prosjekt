
# Lag WAAM L-vegg
# Test av PL i hjørnet – MOVL

from datetime import datetime
from math import ceil
from pathlib import Path


# ============================================================
# ENDRBARE PARAMETERE
# ============================================================

JOBBNAVN = "KANTPL"           # Maks 8 tegn

LENGDE = 120.0                # mm, total lengde
ANTALL_LAG = 15
LAGHOYDE = 1.8                # mm

X_START, Y_START, Z_START = 80.0, 27.0, 0.0

SVEISEHASTIGHET = 7.0         # mm/s
PROGRAM = "ARGF2"
WAITTIME = 0                 # sekunder

# PL-test
PL_HJORNE = 0               # 0–8, kun geometrisk hjørne
TEST_UTEN_SVEIS = True        # True = ingen sveisekommandoer

VEKSLENDE = True
FLERE_PUNKTER = True
PUNKTAVSTAND = 5.0            # mm

ACC = 20
DEC = 20

USER = 9
TOOL = 1

RX, RY, RZ = 0.0, 0.0, -170.0

STARTPOS = (0.0, 0.0, 150.0)
SLUTTPOS = (185.0, 150.0, 150.0)


# ============================================================
# FASTE PARAMETERE
# ============================================================

FLYTTHASTIGHET = 11.0        # mm/s, uten bue
LEDDHASTIGHET = 0.78         # VJ i prosent

MAKRO = f"MACRO1 MJ#(0) {PROGRAM}"
RCONF = "1," + ",".join(["0"] * 23)


# ============================================================
# KONTROLL
# ============================================================

if not (
    1 <= len(JOBBNAVN) <= 8
    and JOBBNAVN.isascii()
    and JOBBNAVN.isalnum()
):
    raise ValueError("Ugyldig JOBBNAVN.")

if not (0 <= PL_HJORNE <= 8):
    raise ValueError("PL_HJORNE må være mellom 0 og 8.")

if not (1 <= USER <= 63 and 0 <= TOOL <= 63):
    raise ValueError("Ugyldig USER eller TOOL.")

if (
    LENGDE <= 0
    or ANTALL_LAG < 1
    or LAGHOYDE <= 0
    or SVEISEHASTIGHET <= 0
):
    raise ValueError("Ugyldige sveiseparametere.")

if FLERE_PUNKTER and PUNKTAVSTAND <= 0:
    raise ValueError("PUNKTAVSTAND må være positiv.")

if min(STARTPOS[2], SLUTTPOS[2]) <= (
    Z_START + (ANTALL_LAG - 1) * LAGHOYDE
):
    raise ValueError("Parkposisjonene må være over øverste lag.")


# ============================================================
# OPPSETT
# ============================================================

punkter = []
instruksjoner = ["NOP"]

oversikt = [
    f"JOBB: {JOBBNAVN}",
    f"Antall lag: {ANTALL_LAG}",
    f"L-hoeyde: {LAGHOYDE:g} mm",
    f"Sveisehastighet: {SVEISEHASTIGHET:g} mm/s",
    f"PL hjorne: {PL_HJORNE}",
    f"Test uten sveis: {TEST_UTEN_SVEIS}",
    f"USER={USER}, TOOL={TOOL}",
    ""
]

# Hjørnet til L-banen
HALV = LENGDE / 2

HJORNE_X = X_START + HALV
HJORNE_Y = Y_START


# ============================================================
# BEVEGELSESFUNKSJON
# ============================================================

def flytt(x, y, z, bevegelse="MOVL", fart=None, pl=None):

    nr = len(punkter)

    punkter.append(
        f"C{nr:05d}="
        f"{x:.3f},{y:.3f},{z:.3f},"
        f"{RX:.4f},{RY:.4f},{RZ:.4f}"
    )

    if bevegelse == "MOVJ":
        kommando = (
            f"MOVJ C{nr:05d} "
            f"VJ={LEDDHASTIGHET:.2f}"
        )
    else:
        if fart is None:
            raise ValueError("MOVL krever en hastighet.")

        kommando = f"MOVL C{nr:05d} V={fart:.1f}"

        if pl is not None:
            # Kun PL på hjørnepunktet
            # kommando += f" PL={pl:d}"
            kommando += f" ACC={ACC:d} DEC={DEC:d}"
        else:
            # ACC og DEC på øvrige punkter
            kommando += f" ACC={ACC:d} DEC={DEC:d}"
    instruksjoner.append(kommando)

    oversikt.append(
        f"  {kommando:<48} "
        f"X={x:.1f} Y={y:.1f} Z={z:.1f}"
    )


# ============================================================
# SVEISEFUNKSJONER
# ============================================================

def bue_paa():

    if TEST_UTEN_SVEIS:
        oversikt.append("  TEST – bue deaktivert")
        return

    instruksjoner.extend([MAKRO, "ARCON"])
    oversikt.append("  ARCON")


def bue_av():

    if TEST_UTEN_SVEIS:
        return

    instruksjoner.append("ARCOF")
    instruksjoner.append(f"TIMER T={WAITTIME}")

    oversikt.append("  ARCOF")


# ============================================================
# LAG L-BANE
# ============================================================

def lag_l_bane():

    steg = ceil(HALV / PUNKTAVSTAND) if FLERE_PUNKTER else 1

    # Første arm: X-retning, inkludert hjørnet
    bane = [
        (X_START + HALV * i / steg, Y_START)
        for i in range(steg + 1)
    ]

    # Andre arm: Y-retning, uten å gjenta hjørnet
    bane += [
        (HJORNE_X, Y_START + HALV * i / steg)
        for i in range(1, steg + 1)
    ]

    return bane


def er_hjorne(x, y):

    return (
        abs(x - HJORNE_X) < 0.001
        and abs(y - HJORNE_Y) < 0.001
    )


# ============================================================
# STARTPOSISJON
# ============================================================

flytt(*STARTPOS, bevegelse="MOVJ")

flytt(
    X_START,
    Y_START,
    STARTPOS[2],
    bevegelse="MOVJ"
)

flytt(
    X_START,
    Y_START,
    Z_START,
    fart=FLYTTHASTIGHET
)


# ============================================================
# GENERER ALLE LAG
# ============================================================

for lag in range(ANTALL_LAG):

    z = Z_START + lag * LAGHOYDE

    bane = lag_l_bane()

    if VEKSLENDE and lag % 2 == 1:
        bane.reverse()

    instruksjoner.append(f"*LAG{lag + 1}")

    oversikt.append(
        f"\nLAG {lag + 1:02d} | Z={z:.2f} mm"
    )

    # Flytt til startpunktet for laget
    if lag > 0:

        if VEKSLENDE:
            flytt(
                bane[0][0],
                bane[0][1],
                z,
                fart=FLYTTHASTIGHET
            )

        else:
            # Retur med bue av, via sikker høyde
            flytt(
                forrige_slutt[0],
                forrige_slutt[1],
                STARTPOS[2],
                fart=FLYTTHASTIGHET
            )

            flytt(
                bane[0][0],
                bane[0][1],
                STARTPOS[2],
                fart=FLYTTHASTIGHET
            )

            flytt(
                bane[0][0],
                bane[0][1],
                z,
                fart=FLYTTHASTIGHET
            )

    bue_paa()

    antall_hjornekommandoer = 0

    # Bevegelse langs L-banen
    for x, y in bane[1:]:

        pl = None

        if er_hjorne(x, y):
            pl = PL_HJORNE
            antall_hjornekommandoer += 1

        flytt(
            x,
            y,
            z,
            fart=SVEISEHASTIGHET,
            pl=pl
        )

    if antall_hjornekommandoer != 1:
        raise ValueError(
            f"Lag {lag + 1}: forventet én PL-kommando "
            f"i hjørnet, fant {antall_hjornekommandoer}."
        )

    bue_av()

    # Lagre både X og Y for riktig returbevegelse
    forrige_slutt = bane[-1]


# ============================================================
# AVSLUTNING
# ============================================================

oversikt.append("\nAVSLUTNING")

# Trekk rett opp fra faktisk sluttpunkt
flytt(
    forrige_slutt[0],
    forrige_slutt[1],
    SLUTTPOS[2],
    fart=FLYTTHASTIGHET
)

flytt(*SLUTTPOS, bevegelse="MOVJ")

instruksjoner.append("END")


# ============================================================
# GENERER JBI
# ============================================================

header = [
    "/JOB",
    f"//NAME {JOBBNAVN}",
    "//POS",
    f"///NPOS {len(punkter)},0,0,0,0,0",
    f"///USER {USER}",
    f"///TOOL {TOOL}",
    "///POSTYPE USER",
    "///RECTAN",
    f"///RCONF {RCONF}",
]

inst_header = [
    "//INST",
    f"///DATE {datetime.now():%Y/%m/%d %H:%M}",
    "///ATTR SC,RW,RJ",
    f"////FRAME USER {USER}",
    "///GROUP1 RB1",
]

# ============================================================
# LAGRE FILER
# ============================================================

mappe = Path(__file__).resolve().parent / "JBI"
mappe.mkdir(exist_ok=True)

jbi_fil = mappe / f"{JOBBNAVN}.JBI"
oversikt_fil = mappe / f"{JOBBNAVN}_oversikt.txt"

with jbi_fil.open(
    "w",
    encoding="utf-8",
    newline="\r\n"
) as fil:

    fil.write(
        "\n".join(
            header + punkter + inst_header + instruksjoner
        ) + "\n"
    )



# ============================================================
# RESULTAT
# ============================================================

pl_kommandoer = [
    linje for linje in instruksjoner
    if f"PL={PL_HJORNE}" in linje
]

print(f"\nLaget JBI: {jbi_fil}")
print(f"Antall posisjoner: {len(punkter)}")
print(f"Antall lag: {ANTALL_LAG}")
print(f"PL i hjørnet: {PL_HJORNE}")
print(f"Antall PL-kommandoer: {len(pl_kommandoer)}")
print(f"ARCON: {instruksjoner.count('ARCON')}")
print(f"ARCOF: {instruksjoner.count('ARCOF')}")

if len(pl_kommandoer) != ANTALL_LAG:
    raise ValueError("Antall PL-kommandoer stemmer ikke med antall lag.")
