# C-code for å lage enkel vegg
from pathlib import Path
from math import ceil

# Endre disse verdiene
JOBBNAVN = "VEGG15"
LENGDE = 150.0             # mm
ANTALL_LAG = 15
LAGHOYDE = 1.8             # mm, økning i Z for hvert lag
X_START, Y_START, Z_START = 15.0, 150.0, 0.0
SVEISEHASTIGHET = 8.0      # mm/s

VEKSLENDE = True           # True: frem og tilbake
FLERE_PUNKTER = False      # False: bare endepunktene i hvert lag
PUNKTAVSTAND = 5.0         # mm, brukes hvis FLERE_PUNKTER = True
ARC_AV_MELLOM_LAG = True   # True: M103 etter hvert lag, M101 før neste

STARTPOS = (0.0, 0.0, 150.0)      # i fri luft, USER-koordinater
SLUTTPOS = (185.0, 150.0, 150.0) # i fri luft, USER-koordinater

# Resten trenger du vanligvis ikke endre
if min(LENGDE, ANTALL_LAG, LAGHOYDE, SVEISEHASTIGHET, PUNKTAVSTAND) <= 0:
    raise ValueError("Lengder, lagantall og hastigheter må være positive.")
if not ARC_AV_MELLOM_LAG and not VEKSLENDE:
    raise ValueError("Kontinuerlig bue mellom lag krever vekslende retning.")
topp_z = Z_START + (ANTALL_LAG - 1) * LAGHOYDE
if STARTPOS[2] <= topp_z or SLUTTPOS[2] <= topp_z:
    raise ValueError("Start- og sluttposisjon må være høyere enn siste lag i Z.")


def bevegelse(type_, x, y, z, fart=None):
    tekst = f"{type_} X{x:.3f} Y{y:.3f} Z{z:.3f}"
    return tekst + (f" F{fart * 60:.1f}" if fart is not None else "")


def punkter():
    xs = [X_START]
    if FLERE_PUNKTER:
        xs += [X_START + i * PUNKTAVSTAND
               for i in range(1, ceil(LENGDE / PUNKTAVSTAND))]
    return xs + [X_START + LENGDE]


linjer = ["; Rett WAAM-vegg. Absolutte koordinater i mm.", "G90",
          bevegelse("G0", *STARTPOS)]

for lag in range(ANTALL_LAG):
    xs = punkter()
    if VEKSLENDE and lag % 2:
        xs.reverse()
    z = Z_START + lag * LAGHOYDE
    linjer.append(f"; LAG {lag + 1}")

    if lag == 0:
        # Flytt over starten og deretter ned til første sveisehøyde.
        linjer.append(bevegelse("G0", xs[0], Y_START, STARTPOS[2]))
        linjer.append(bevegelse("G0", xs[0], Y_START, z))
    elif ARC_AV_MELLOM_LAG:
        if not VEKSLENDE:
            # Returner til samme ende i fri luft (uten egen LOFT-parameter).
            linjer.append(bevegelse("G0", forrige_slutt, Y_START, STARTPOS[2]))
            linjer.append(bevegelse("G0", xs[0], Y_START, STARTPOS[2]))
        # Ved vekslende retning står brenneren allerede over neste start.
        linjer.append(bevegelse("G0", xs[0], Y_START, z))
    else:
        # Buen beholdes på; denne vertikale overgangen blir også sveiset.
        linjer.append(bevegelse("G1", xs[0], Y_START, z, SVEISEHASTIGHET))

    if lag == 0 or ARC_AV_MELLOM_LAG:
        linjer.append("M101")
    for x in xs[1:]:
        linjer.append(bevegelse("G1", x, Y_START, z, SVEISEHASTIGHET))
    if ARC_AV_MELLOM_LAG or lag == ANTALL_LAG - 1:
        linjer.append("M103")
    forrige_slutt = xs[-1]

# Buen er av. Løft rett opp før parkering.
linjer += [bevegelse("G0", forrige_slutt, Y_START, STARTPOS[2]),
           bevegelse("G0", *SLUTTPOS)]

fil = Path("G-code") / f"{JOBBNAVN}.gcode"
fil.write_text("\n".join(linjer) + "\n", encoding="utf-8")
print(f"Laget {fil.name}: {ANTALL_LAG} lag, {len(punkter())} punkter per lag")
print("Obs: kontroller klaring og overgang mellom lag før robotkjøring.")
