# Databehandling

Alt kjøres fra `kjor.py`, i tre steg:

| Steg | Fil | Fra → til |
|---|---|---|
| 1. Etterbehandling | `etterbehandling.py` | `Ubehandlet/` → `Behandlet/` (én rad per måling, metadata fra mappenavn og Excel) |
| 2. Hjørneanalyse | `hjorneanalyse.py` | `Behandlet/` → `Analyse_L_U/` (fart i hjørner, fartsreduksjon, hastighetsforslag) |
| 3. Rapport | `rapport.py` | `Behandlet/` → `Rapport/` (Sveiserapport.xlsx og figurer per test) |

`felles.py` har det som deles: mapper, kolonnenavn, tolking av mappenavn og innlesing av filer.

## Kjøring

```
python kjor.py alt 11/09                         # alle tre steg for nye data fra 11/09
python kjor.py etterbehandle 11/09 --forhandsvis # se hva som ville skjedd
python kjor.py etterbehandle 11/09 --overskriv   # lag Behandlet-filene på nytt
python kjor.py hjorner 11                        # hjørneanalyse for hele november
python kjor.py rapport                           # rapport for alle data
python kjor.py alt "" --overskriv                # gjør ALT på nytt
```

Trykker du bare «Run» i VS Code, brukes `STEG` og `MAPPE` øverst i `kjor.py`.

## Mappenavn

`[L_|U_]STRØM_FART[_overlapp][_tråd][_PL_x][_beskrivelse]`, f.eks. `130_8`, `L_80_7_1`,
`U_80_7_50_1`, `U_80_7_NoD_K`. Er første tall minst (`L_7_80`), tolkes det som fart_strøm.
`_AV_` i navnet (`L_7_AV_PL_8`) betyr tørrkjøring: én råfil som deles i lag etter Z-høyde.
Rette sveiser uten beskrivelse slås opp i `Vegg_test_str_målinger.xlsx`.

## Om målingene

* Loggfila har én rad per sekund, men hver rad inneholder ~4 robotmålinger (S) og ~4
  sveisemaskinmålinger (W) med egne tidsstempler. **Målefrekvensen er 4 Hz.**
* ~30 % av W-målingene er kopier av forrige verdi. Etter at buen slukker sender sveisemaskinen
  siste verdi (~78 A) i flere sekunder. `rapport.py` fjerner slike gjentakelser
  (`FJERN_GJENTATTE_W = True`), ellers blir buetid og energi ~20–25 % for høy.
* `W_kJ` er en energiteller som nullstilles ved hver buestart.

`Gammelt/` inneholder de tidligere skriptene som referanse.
