#Oversett vegg.gcode til JBI + lesbar tekst. Kjør etter lag_gcode.py
from pathlib import Path
from datetime import datetime

# Endrbare verdier
JOBBNAVN = "VEGG15"
USER = 6
TOOL = 1
RX, RY, RZ = 0.0, 0.0, -50.0
FLYTTHASTIGHET = 11.0       # mm/s, uten sveising
LEDDHASTIGHET = 0.78        # VJ (%), kun til første posisjon
SVEISING = True             # False: lag JBI uten ARCON/ARCOF (tørrkjøring)
MAKRO = "MACRO1 MJ#(0) ARGF205"   # MÅ kontrolleres på roboten

if not 1 <= len(JOBBNAVN) <= 8 or not JOBBNAVN.isalnum():
    raise ValueError("JOBBNAVN må ha 1–8 bokstaver/tall.")
if not 0 <= USER <= 63 or not 0 <= TOOL <= 63:
    raise ValueError("Kontroller USER og TOOL mot robotens faktiske oppsett.")
if FLYTTHASTIGHET <= 0 or LEDDHASTIGHET <= 0:
    raise ValueError("Hastighetene må være positive.")

mappe = Path(__file__).parent
linjer = (mappe / f"{JOBBNAVN}.gcode").read_text(encoding="utf-8").splitlines()
posisjoner, instruksjoner = [], ["NOP"]
oversikt = [f"JOBB {JOBBNAVN} | USER {USER} | TOOL {TOOL}",
            f"ARCON/ARCOF i JBI: {SVEISING}", ""]
bue = False

for nummer, raw in enumerate(linjer, 1):
    rad = raw.strip()
    if rad.startswith("; LAG "):
        oversikt.extend(["", rad[2:].upper(), "-" * 42])
        continue
    if not rad or rad.startswith(";") or rad == "G90":
        continue

    deler = rad.split()
    kommando = deler[0]
    if kommando in ("M101", "M103"):
        if len(deler) != 1:
            raise ValueError(f"Ugyldig kommando på linje {nummer}: {rad}")
        if kommando == "M101" and bue:
            raise ValueError(f"Buen er allerede på (linje {nummer}).")
        if kommando == "M103" and not bue:
            raise ValueError(f"Buen er allerede av (linje {nummer}).")
        bue = kommando == "M101"
        if SVEISING:
            if bue:
                if MAKRO:
                    instruksjoner.append(MAKRO)
                instruksjoner.append("ARCON")
            else:
                instruksjoner.append("ARCOF")
        oversikt.append("  ARCON" if bue else "  ARCOF")
        continue

    if kommando not in ("G0", "G1") or (kommando == "G0" and bue) or (kommando == "G1" and not bue):
        raise ValueError(f"Uventet bevegelse på linje {nummer}: {rad}")
    try:
        verdier = {felt[0]: float(felt[1:]) for felt in deler[1:]}
        if set(verdier) - {"X", "Y", "Z", "F"} or not {"X", "Y", "Z"} <= set(verdier):
            raise ValueError("X, Y og Z kreves; bare F er valgfri")
    except ValueError as feil:
        raise ValueError(f"Ugyldig koordinat på linje {nummer}: {rad}") from feil

    x, y, z = (verdier[akse] for akse in "XYZ")
    fart = verdier.get("F", 0) / 60 if kommando == "G1" else FLYTTHASTIGHET
    if kommando == "G1" and fart <= 0:
        raise ValueError(f"G1 mangler gyldig hastighet på linje {nummer}")

    nr = len(posisjoner)
    navn = f"C{nr:05d}"
    posisjoner.append(f"{navn}={x:.3f},{y:.3f},{z:.3f},{RX:.4f},{RY:.4f},{RZ:.4f}")
    if nr == 0:
        instruksjoner.append(f"MOVJ {navn} VJ={LEDDHASTIGHET:.2f}")
        farttekst = f"VJ={LEDDHASTIGHET:.2f}%"
    else:
        instruksjoner.append(f"MOVL {navn} V={fart:.1f}")
        farttekst = f"V={fart:.1f} mm/s"
    oversikt.append(f"  {'SVEIS' if bue else 'FLYTT'} {navn}: "
                    f"X={x:.1f} Y={y:.1f} Z={z:.1f} | {farttekst}")

if bue or not posisjoner:
    raise ValueError("Mangler M103 ved slutten, eller ingen posisjoner.")

hode = ["/JOB", f"//NAME {JOBBNAVN}", "//POS",
        f"///NPOS {len(posisjoner)},0,0,0,0,0", f"///USER {USER}",
        f"///TOOL {TOOL}", "///POSTYPE USER", "///RECTAN",
        "///RCONF 1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0"]
fot = ["//INST", f"///DATE {datetime.now():%Y/%m/%d %H:%M}",
       "///ATTR SC,RW,RJ", f"////FRAME USER {USER}", "///GROUP1 RB1"]

ut = Path("Jbi") / f"{JOBBNAVN}.JBI"
ut.write_bytes(("\r\n".join(hode + posisjoner + fot + instruksjoner + ["END"])
                + "\r\n").encode("utf-8"))
(mappe / f"{JOBBNAVN}_oversikt.txt").write_text("\n".join(oversikt) + "\n", encoding="utf-8")
print(f"Laget {ut.name} med {len(posisjoner)} posisjoner + lesbar oversikt.")
print("JBI må gjennomgås, simuleres og tørrkjøres med godkjent robotoppsett.")
