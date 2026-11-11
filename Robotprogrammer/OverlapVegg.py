# Lag WAAM Vegg I KANT FORM

from datetime import datetime
from math import ceil
from pathlib import Path
#Parametere å endre på : Strøm, Overlap;vibrasjon


# Endrbare parametere
JOBBNAVN = "OVERLAP1"                 # Maks 8 tegn
LENGDE = 100.0                     #mm 
ANTALL_LAG = 15
LAGHOYDE = 1.7                      #mm
BEADWIDTH = 7.5                      #mm
OVERLAP = 0.67                   
X_START, Y_START, Z_START = 225.0, 185.0, 75.0
SVEISEHASTIGHET = 7.0              #mm/s
PROGRAM = "ARGF2"
WAITTIME = 30
STEGLENGDE = 5.0                        # sekunder              

VEKSLENDE = True                   # Sveiseretning for hvert lag
FLERE_PUNKTER = True              # False: bare start og slutt på hvert lag
PUNKTAVSTAND = 5.0 
ACC = 20
DEC = 20
PL_L = 0


USER = 9
TOOL = 1
RX, RY, RZ = 0.0, 0.0, 45.0       # Orientering
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
    elif bevegelse == "MOVC":
        kommando = f"MOVC C{nr:05d} V={fart:.1f} ACC={ACC:d} DEC={DEC:d}"
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
    overlap_forflytt = OVERLAP*BEADWIDTH
    R = 0.5 * overlap_forflytt
    antall_steg = ceil(LENGDE / PUNKTAVSTAND) if FLERE_PUNKTER else 1

    #For X-retning
    bane1 = [(X_START + LENGDE * i / antall_steg,Y_START) for i in range(antall_steg + 1)]

    #SvingPunkt
    svingpunkt =[ ( X_START + LENGDE + R/2 , Y_START + R/2), ( X_START + LENGDE + R , Y_START + R + R/2), (X_START + LENGDE, Y_START + overlap_forflytt)]

    #for X-retning etter Y-retning forflyttning
    bane2 = [(X_START + LENGDE - STEGLENGDE - LENGDE * i / antall_steg,Y_START + overlap_forflytt) for i in range(antall_steg )]
    # xs = [X_START + LENGDE * i / antall_steg for i in range(antall_steg + 1)]
    instruksjoner.append(f"*LAG{lag + 1}")
    if VEKSLENDE and lag % 2 == 1:
        bane1, bane2 = bane2[::-1], bane1[::-1]
        svingpunkt.reverse()
    
    
    if lag > 0:
        if VEKSLENDE:
            flytt(bane1[0][0], bane1[0][1], z, fart=FLYTTHASTIGHET)
            #Kontroler at svingpunkt starter og slutter på samme sted som bane1 og bane2
            #assert bane1[-1] == svingpunkt[0]
            #assert bane2[0] == svingpunkt[-1]

        else:
            # Returner til start med buen av
            flytt(forrige_slutt, Y_START, STARTPOS[2], fart=FLYTTHASTIGHET)
            flytt(bane1[0][0], bane1[0][1], STARTPOS[2], fart=FLYTTHASTIGHET)
            flytt(bane1[0][0], bane1[0][1], z, fart=FLYTTHASTIGHET)

    # Sveis laget
    bue_paa()

    for x, y in bane1[1:]:
        flytt(x, y, z, fart=SVEISEHASTIGHET)
    for x, y in svingpunkt:
        flytt(x, y, z,bevegelse="MOVC", fart=SVEISEHASTIGHET)
    for x, y in bane2:
        flytt(x, y, z, fart=SVEISEHASTIGHET)

    bue_av()
    forrige_slutt = bane2[-1][0]

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
