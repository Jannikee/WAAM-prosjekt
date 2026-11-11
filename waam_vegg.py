# Lag WAAM Vegg

from datetime import datetime
from math import ceil
from pathlib import Path


# Endrbare parametere
JOBBNAVN = "VEGG2"                 # Maks 8 tegn
LENGDE = 150.0                     #mm
ANTALL_LAG = 15                                         
LAGHOYDE = 1.7                     #mm
X_START, Y_START, Z_START = 30.0, 85.0, 0.0
SVEISEHASTIGHET = 7              #mm/s
PROGRAM = "ARGF2"  
WAITTIME = 30                        # sekunder            

VEKSLENDE = True                   # Sveiseretning for hvert lag
FLERE_PUNKTER = True              # False: bare start og slutt på hvert lag
PUNKTAVSTAND = 5.0                 #mm
ACC = int(20)
DEC = int(20)

USER = 9
TOOL = 1
RX, RY, RZ = 0.0, 0.0, -170.0       # Orientering
STARTPOS = (0.0, 0.0, 150.0)       # Parkposisjon før sveising
SLUTTPOS = (185.0, 150.0, 150.0)   # Parkposisjon etter sveising


# Fast-ish parametere
FLYTTHASTIGHET = 11.0              # mm/s, bevegelse uten bue
LEDDHASTIGHET = 0.78               # VJ i prosent
MAKRO = f"MACRO1 MJ#(0) {PROGRAM}"    # Funksjonen må bekreftes på roboten
RCONF = "1," + ",".join(["0"] * 23)


# Enkel kontroll av innstillingene
if not (1 <= len(JOBBNAVN) <= 8 and JOBBNAVN.isascii() and JOBBNAVN.isalnum()):
    raise ValueError("JOBBNAVN må være 1–8 bokstaver/tall uten spesialtegn.")
if not (1 <= USER <= 63 and 0 <= TOOL <= 63):
    raise ValueError("Ugyldig USER eller TOOL.")
if LENGDE <= 0 or ANTALL_LAG < 1 or LAGHOYDE <= 0 or SVEISEHASTIGHET <= 0:
    raise ValueError("Kontroller lengde, antall lag, laghøyde og hastighet.")
if FLERE_PUNKTER and PUNKTAVSTAND <= 0:
    raise ValueError("PUNKTAVSTAND må være større enn null.")
if min(STARTPOS[2], SLUTTPOS[2]) <= Z_START + (ANTALL_LAG - 1) * LAGHOYDE:
    raise ValueError("Parkposisjonenes Z må ligge over øverste programmerte lag.")

punkter = []
instruksjoner = ["NOP"]
oversikt = [f"{JOBBNAVN}: {ANTALL_LAG} lag, {LENGDE:g} mm, Z-steg {LAGHOYDE:g} mm",
            f"USER={USER}, TOOL={TOOL}, sveisehastighet={SVEISEHASTIGHET:g} mm/s",
            ""]


def flytt(x, y, z, bevegelse="MOVL", fart=None):
    nr = len(punkter)
    punkter.append(f"C{nr:05d}={x:.3f},{y:.3f},{z:.3f},{RX:.4f},{RY:.4f},{RZ:.4f}")
    if bevegelse == "MOVJ":
        kommando = f"MOVJ C{nr:05d} VJ={LEDDHASTIGHET:.2f}"
    else:
        kommando = f"MOVL C{nr:05d} V={fart:.1f} ACC={ACC:d} DEC={DEC:d}"
    instruksjoner.append(kommando)
    oversikt.append(f"  {kommando:<28} X={x:.1f} Y={y:.1f} Z={z:.1f}")


def bue_paa():
    instruksjoner.extend([MAKRO, "ARCON"])
    oversikt.append("  ARCON (sveis på)")



def bue_av():
    instruksjoner.append("ARCOF")
    instruksjoner.append(f"TIMER T={WAITTIME}")  # Vent {WAITTIME} sekunder for å sikre at sveisen er ferdig
    oversikt.append("  ARCOF (sveis av)")



flytt(*STARTPOS, bevegelse="MOVJ")
flytt(X_START, Y_START, STARTPOS[2], bevegelse="MOVJ")
flytt(X_START, Y_START, Z_START, fart=FLYTTHASTIGHET)

for lag in range(ANTALL_LAG):
    z = Z_START + lag * LAGHOYDE
    antall_steg = ceil(LENGDE / PUNKTAVSTAND) if FLERE_PUNKTER else 1
    xs = [X_START + LENGDE * i / antall_steg for i in range(antall_steg + 1)]
    instruksjoner.append(f"*LAG{lag + 1}")
    if VEKSLENDE and lag % 2 == 1:
        xs.reverse()
    oversikt.append(f"\nLAG {lag + 1} | X {xs[0]:g} -> {xs[-1]:g} | Z={z:.2f}")
    
    if lag > 0:
        if VEKSLENDE:
            flytt(xs[0], Y_START, z, fart=FLYTTHASTIGHET)
        else:
            # Returner til start med buen av
            flytt(forrige_slutt, Y_START, STARTPOS[2], fart=FLYTTHASTIGHET)
            flytt(xs[0], Y_START, STARTPOS[2], fart=FLYTTHASTIGHET)
            flytt(xs[0], Y_START, z, fart=FLYTTHASTIGHET)

    # Sveis laget
    bue_paa()

    for x in xs[1:]:
        flytt(x, Y_START, z, fart=SVEISEHASTIGHET)

    bue_av()
    forrige_slutt = xs[-1]

# Trekk rett opp med buen av før retur til siste parkposisjon
oversikt.append("\nAVSLUTNING")
flytt(forrige_slutt, Y_START, SLUTTPOS[2], fart=FLYTTHASTIGHET)
flytt(*SLUTTPOS, bevegelse="MOVJ")
instruksjoner.append("END")


header = [
    "/JOB", f"//NAME {JOBBNAVN}", "//POS", f"///NPOS {len(punkter)},0,0,0,0,0",
    f"///USER {USER}", f"///TOOL {TOOL}", "///POSTYPE USER", "///RECTAN",
    f"///RCONF {RCONF}",
]
inst_header = [
    "//INST", f"///DATE {datetime.now():%Y/%m/%d %H:%M}",
    "///ATTR SC,RW,RJ", f"////FRAME USER {USER}", "///GROUP1 RB1",
]

mappe = Path(__file__).resolve().parent / "JBI"
mappe.mkdir(exist_ok=True)
with (mappe / f"{JOBBNAVN}.JBI").open("w", encoding="utf-8", newline="\r\n") as fil:
    fil.write("\n".join(header + punkter + inst_header + instruksjoner) + "\n")
(mappe / f"{JOBBNAVN}_oversikt.txt").write_text("\n".join(oversikt) + "\n", encoding="utf-8")
print(f"Laget JBI og oversikt i: {mappe}")
print(f"{len(punkter)} posisjoner, {instruksjoner.count('ARCON')} ARCON, {instruksjoner.count('ARCOF')} ARCOF")
