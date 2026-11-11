#!/usr/bin/env python3
"""Les Hjorneoversikt.csv og beregn materialøkning og hastighetsforslag.

Kun analyse/planlegging: skriver IKKE robotprogram og gjør ingen endringer i rådata.
"""

import csv
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

# ==========================================================
# INNSTILLINGER – ENDRE DISSE
# ==========================================================
BASE_DIR = Path(__file__).resolve().parent
INNFIL = BASE_DIR / "Analyse_L_U" / "Hjorneoversikt.csv"
UTMAPPE = BASE_DIR / "Analyse_L_U"
PROGRAMMERT_HASTIGHET_MM_S = 7.0

# Valgfritt konservativt tak for forslag til forsøksinnstilling.
# Hvis taket er aktivert, endres det beregnede forslaget KUN i kolonnen
# 'Begrenset_forsoksfart_mm_s'; ingen automatisk robotprogrammering.
MAKS_FORSLAG_MM_S = None  # f.eks. 8.0, eller None for ingen grense

# Ved mye ekstra materialtilførsel flagger vi forslaget som krevende
VARSEL_MATERIALOKNING_PCT = 10.0

# ==========================================================

def num(value):
    return float(str(value).strip().replace(",", "."))


def name_group(filename):
    name = Path(filename).name
    if name.startswith("L_"):
        return "L"
    if name.startswith("U_"):
        parts = name.split("_")
        # U_80_7_50pct_1mm_Lag_01.csv
        overlap = next((part for part in parts if part.lower().endswith("pct")), "ukjent")
        return f"U {overlap}"
    return "Annet"


def fmt(value, places=3):
    return f"{value:.{places}f}"


def write_csv(path, records, fieldnames):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(records)


def main():
    if not INNFIL.is_file():
        print(f"Fant ikke: {INNFIL}")
        print("Endre INNFIL øverst til plasseringen av Hjorneoversikt.csv")
        return

    with INNFIL.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        data = list(reader)

    resultater = []
    grupper = defaultdict(list)

    for rad in data:
        try:
            v_rett = num(rad["Rett_hastighet_mm_s"])
            v_hjorne = num(rad["Hjorne_hastighet_mm_s"])
            w_rett = num(rad["Rett_wfs_m_min"])
            w_hjorne = num(rad["Hjorne_wfs_m_min"])
            if min(v_rett, v_hjorne, w_rett, w_hjorne) <= 0:
                raise ValueError("Null/negativ verdi i fart eller trådmating")

            # Teoretisk tilført trådvolum per lengde er proporsjonalt med WFS / fart.
            forhold = (w_hjorne / v_hjorne) / (w_rett / v_rett)
            ekstra_pct = (forhold - 1) * 100

            # Den faktiske hastigheten som ville gitt samme tilførsel per lengde
            # som på rett strekning, med observert WFS i hjørnet.
            maal_faktisk = v_hjorne * forhold

            # EKSPERIMENTELT PROGRAMFORSLAG: antar faktisk hjørnefart skalerer
            # proporsjonalt med programmert fart. Dette kan feile ved akselerasjons-
            # begrensning eller bevegelsesplanlegging (MOVL/MOVC).
            forslag_prog = PROGRAMMERT_HASTIGHET_MM_S * forhold
            begrenset = (min(forslag_prog, MAKS_FORSLAG_MM_S)
                         if MAKS_FORSLAG_MM_S is not None else forslag_prog)
            gruppe = name_group(rad["Fil"])

            status = ("Sjekk manuelt – stor økning" if ekstra_pct > VARSEL_MATERIALOKNING_PCT
                      else "Foreløpig anslag")
            resultat = {
                "Fil": rad["Fil"],
                "Gruppe": gruppe,
                "Hjorne": rad.get("Hjorne", ""),
                "Rett_hastighet_mm_s": fmt(v_rett, 2),
                "Hjorne_hastighet_mm_s": fmt(v_hjorne, 2),
                "Materialendring_prosent": fmt(ekstra_pct, 1),
                "Onsket_faktisk_hjornefart_mm_s": fmt(maal_faktisk, 2),
                "Navaerende_programmert_fart_mm_s": fmt(PROGRAMMERT_HASTIGHET_MM_S, 2),
                "Eksperimentelt_programforslag_mm_s": fmt(forslag_prog, 2),
                "Begrenset_forsoksfart_mm_s": fmt(begrenset, 2),
                "Merknad": status,
            }
            resultater.append(resultat)
            grupper[gruppe].append((ekstra_pct, maal_faktisk, forslag_prog))
        except (ValueError, KeyError) as exc:
            print(f"Hopper over {rad.get('Fil','ukjent fil')}: {exc}")

    if not resultater:
        print("Ingen gyldige rader å analysere.")
        return

    UTMAPPE.mkdir(parents=True, exist_ok=True)
    felt = list(resultater[0].keys())
    write_csv(UTMAPPE / "Hjornehastighet_per_lag.csv", resultater, felt)

    oversikt = []
    for gruppe, values in sorted(grupper.items()):
        pcts = [x[0] for x in values]
        targets = [x[1] for x in values]
        proposals = [x[2] for x in values]
        oversikt.append({
            "Gruppe": gruppe,
            "Antall_lag": len(values),
            "Gjennomsnitt_materialendring_pct": fmt(mean(pcts), 1),
            "Median_materialendring_pct": fmt(median(pcts), 1),
            "Gjennomsnitt_onsket_faktisk_fart_mm_s": fmt(mean(targets), 2),
            "Gjennomsnitt_eksperimentelt_programforslag_mm_s": fmt(mean(proposals), 2),
            "Merknad": "Kun estimat – ikke validert på robot",
        })

    write_csv(UTMAPPE / "Hjornehastighet_oppsummering.csv", oversikt, list(oversikt[0].keys()))

    print("\nHJØRNEANALYSE (beregnet fra logger)")
    print("Materialendring: (WFS_hjørne/fart_hjørne) / (WFS_rett/fart_rett) - 1")
    print("Programmert forslag forutsetter proporsjonal respons og må testes.\n")
    for row in oversikt:
        print(f"{row['Gruppe']}: {row['Antall_lag']} lag | "
              f"ekstra materiale {row['Gjennomsnitt_materialendring_pct']} % | "
              f"ønsket faktisk fart {row['Gjennomsnitt_onsket_faktisk_fart_mm_s']} mm/s | "
              f"forsøksanslag programmert fart {row['Gjennomsnitt_eksperimentelt_programforslag_mm_s']} mm/s")

    print(f"\nSkrev: {UTMAPPE / 'Hjornehastighet_per_lag.csv'}")
    print(f"Skrev: {UTMAPPE / 'Hjornehastighet_oppsummering.csv'}")

if __name__ == "__main__":
    main()
