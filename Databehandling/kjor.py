#!/usr/bin/env python3
"""Kjor databehandlingen. Ett sted aa starte alt fra.

Fra terminal (i Databehandling-mappen):
    python kjor.py alt 11/09              # alle tre steg for 11/09
    python kjor.py etterbehandle 11/09    # bare Ubehandlet -> Behandlet
    python kjor.py etterbehandle 11/09 --forhandsvis   # vis hva som ville skjedd
    python kjor.py etterbehandle 11/09 --overskriv     # erstatt eksisterende filer
    python kjor.py hjorner 11             # hjorneanalyse for hele november
    python kjor.py rapport                # Sveiserapport.xlsx for alle data

Eller trykk "Run" i VS Code: da brukes STEG og MAPPE under.

Mappen er relativ til Ubehandlet/Behandlet/Analyse_L_U, f.eks. "11/09",
"10/PL_test" eller "" (alt).
"""
import argparse

from etterbehandling import etterbehandle
from hjorneanalyse import hjorneanalyse
from rapport import rapport

# ==== Brukes naar skriptet kjores uten argumenter (Run-knappen) ====
STEG = "alt"        # "etterbehandle", "hjorner", "rapport" eller "alt"
MAPPE = "11/09"
# ==================================================================


def main():
    p = argparse.ArgumentParser(description="WAAM databehandling")
    p.add_argument("steg", nargs="?", default=STEG, choices=["etterbehandle", "hjorner", "rapport", "alt"])
    p.add_argument("mappe", nargs="?", default=MAPPE, help='f.eks. "11/09" eller "" for alt')
    p.add_argument("--forhandsvis", action="store_true", help="etterbehandling: ikke skriv filer")
    p.add_argument("--overskriv", action="store_true", help="etterbehandling: erstatt eksisterende filer")
    a = p.parse_args()

    if a.steg in ("etterbehandle", "alt"):
        print("=" * 20, "1/3 ETTERBEHANDLING", "=" * 20)
        etterbehandle(a.mappe, skriv=not a.forhandsvis, overskriv=a.overskriv)
    if a.steg in ("hjorner", "alt"):
        print("\n" + "=" * 20, "2/3 HJORNEANALYSE", "=" * 20)
        hjorneanalyse(a.mappe)
    if a.steg in ("rapport", "alt"):
        print("\n" + "=" * 20, "3/3 RAPPORT (alle data)", "=" * 20)
        rapport("")   # rapporten samler alltid alle tester


if __name__ == "__main__":
    main()
