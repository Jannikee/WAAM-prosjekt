#!/usr/bin/env python3
"""Etterbehandling av sveise-CSV: behold 38 loggkolonner + testmetadata."""
import csv
import re
from datetime import datetime
from pathlib import Path

# =============== ENDRBARE INNSTILLINGER ===============
BASE_DIR = Path(__file__).resolve().parent
HOVEDMAPPE = BASE_DIR / 'Ubehandlet' / '11' / '09'
UTMAPPE = BASE_DIR / 'Behandlet' / '11' / '09'
EXCEL_FIL = BASE_DIR / 'Vegg_test_str_målinger.xlsx'
MAKS_PAUSE_MIN = 5
SKRIV_FILER = True            # Endres til True etter å ha sjekket utskriften
STANDARD_TRAD_MM = 1.2        # Gamle mapper uten tråddiameter
MAPPE_TIL_SVEIS = {}           # F.eks. {'130_10': 5} ved behov
# ======================================================

HEADER = ['time', 'c1','c2','c3','c4','c5','c6','c7','c8',
          'S_x','S_y','S_z','S_nx','S_ny','S_nz','S_v','S_i','S_wfs',
          'W_I','W_V','W_WFS','W_kW','W_kJ',
          'R_1','R_2','R_3','R_4','R_5','R_6',
          'K_1','K_2','K_3','K_4','K_5','K_6','J_job','word','rule_log']
EXTRA = ['Sveis','Lag','Testtype','Strom_settpunkt_A','Hastighet_settpunkt_mm_s',
         'Trad_mm','Overlapp_prosent','Beskrivelse','Dybde_mm','Bredde_mm',
         'Steghoyde_brukt_mm','Steghoyde_faktisk_mm','Kommentar']


def tall(v):
    if v is None or str(v).strip() == '':
        return None
    try:
        return float(str(v).replace(',', '.'))
    except ValueError:
        return None


def fmt(v):
    return f'{v:g}'


def les_mappenavn(navn):
    """Les mappenavn: STROM_FART[_overlapp][_trad][_PL..][_fri beskrivelse].

    Alt som ikke er tall (med valgfri enhet mm/pct/%) eller PL-kode regnes
    som beskrivelse og tas automatisk med i filnavn og metadata.

    Eksempler: L_80_7_1, L_80_7_1mm_PL8, U_80_7_50pct_1mm_PL0,
               U_80_7_NoD, U_80_7_50pct_1mm_NoD_ny_dyse.
    """
    deler = navn.split('_')
    type_ = 'Rett'
    if deler[0].upper() in {'L', 'U', 'TEMP', 'T'}:
        type_ = deler.pop(0).upper()
    if len(deler) < 2:
        return None

    strom, fart = tall(deler[0]), tall(deler[1])
    if strom is None or fart is None:
        return None

    rest = deler[2:]
    ovrige = []
    har_pl = False
    i = 0
    while i < len(rest):
        token = rest[i].upper()
        neste = rest[i + 1].upper() if i + 1 < len(rest) else ''

        # Eksempel: AV_PL_8, der AV beholdes som del av originalnavnet.
        if token in {'AV', 'UTEN'} and (neste == 'PL' or neste.startswith('PL')):
            har_pl = True
            i += 1
            continue
        # PL_0 / PL_8 / PL_AV / PL_OFF, eller bare PL.
        if token == 'PL':
            har_pl = True
            i += 1
            if i < len(rest) and re.fullmatch(r'[0-8]|AV|OFF|NONE|UTEN', rest[i], re.I):
                i += 1
            continue
        # PL0 / PL8 / PLOFF / PLAV / PLNONE.
        if re.fullmatch(r'PL(?:[0-8]|AV|OFF|NONE|UTEN)', token):
            har_pl = True
            i += 1
            continue
        ovrige.append(rest[i])
        i += 1

    # Skill tall (med/uten enhet) fra fri beskrivelse
    mm_verdier, pct_verdier, rene_tall, beskrivelse = [], [], [], []
    for tok in ovrige:
        m = re.fullmatch(r'(\d+(?:[.,]\d+)?)(mm|pct|%)?', tok, re.I)
        if not m:
            beskrivelse.append(tok)
            continue
        verdi = tall(m.group(1))
        enhet = (m.group(2) or '').lower()
        if enhet == 'mm':
            mm_verdier.append(verdi)
        elif enhet in {'pct', '%'}:
            pct_verdier.append(verdi)
        else:
            rene_tall.append(verdi)

    if len(mm_verdier) > 1 or len(pct_verdier) > 1:
        return None

    trad = mm_verdier[0] if mm_verdier else None
    overlapp = pct_verdier[0] if pct_verdier else None

    # Tall uten enhet fylles inn som før: U med to tall = overlapp, tråd
    if type_ == 'U':
        if len(rene_tall) == 2 and trad is None and overlapp is None:
            overlapp, trad = rene_tall
        elif len(rene_tall) == 1:
            if trad is None:
                trad = rene_tall[0]
            elif overlapp is None:
                overlapp = rene_tall[0]
            else:
                return None
        elif len(rene_tall) > 1:
            return None
    else:
        if len(rene_tall) == 1 and trad is None:
            trad = rene_tall[0]
        elif len(rene_tall) > 0:
            return None

    if trad is None:
        trad = STANDARD_TRAD_MM

    return dict(type=type_, strom=strom, fart=fart, trad=trad,
                overlapp=overlapp, har_pl=har_pl,
                beskrivelse='_'.join(beskrivelse),
                opprinnelig_navn=navn)


def les_excel():
    from openpyxl import load_workbook
    wb = load_workbook(EXCEL_FIL, read_only=True, data_only=True)
    ws = wb.active
    oversikt = []
    for cells in ws.iter_rows(min_row=2, max_col=9, values_only=True):
        sveis, trad, strom, fart, dybde, bredde, steg, faktisk, kommentar = cells
        if tall(sveis) is None or tall(strom) is None or tall(fart) is None:
            continue  # hopper over Dag 1, Dag 2, Dag 3 og tomme rader
        oversikt.append(dict(sveis=int(tall(sveis)), trad=tall(trad),
                             strom=tall(strom), fart=tall(fart),
                             dybde=dybde, bredde=bredde, steg=steg,
                             faktisk=faktisk, kommentar=kommentar))
    wb.close()
    return oversikt


def er_spesialtest(param):
    """Spesialtester og tester med fri beskrivelse hentes ikke fra Excel."""
    return param['type'] != 'Rett' or bool(param['beskrivelse'])


def finn_excelrad(mappe, param, oversikt):
    if er_spesialtest(param):
        return None, 'Spesialtest (uten Excel-verdier)'
    kandidater = [r for r in oversikt
                  if (r['strom'], r['fart'], r['trad']) ==
                     (param['strom'], param['fart'], param['trad'])]
    if mappe.name in MAPPE_TIL_SVEIS:
        nummer = MAPPE_TIL_SVEIS[mappe.name]
        kandidater = [r for r in kandidater if r['sveis'] == nummer]
    if len(kandidater) == 1:
        return kandidater[0], f"Sveis {kandidater[0]['sveis']}"
    if len(kandidater) > 1:
        return None, 'Flere mulige sveiser: ' + ', '.join(str(r['sveis']) for r in kandidater)
    return None, 'Ingen entydig match i Excel'


def les_logger_tidsrom(path):
    """Bruk råloggens timestamp-kolonne, ikke Windows-filens endringstid."""
    tider = []
    with path.open(newline='', encoding='utf-8-sig') as fh:
        reader = csv.reader(fh)
        next(reader, None)
        for fields in reader:
            if not fields or not fields[0].strip():
                continue
            try:
                tider.append(datetime.fromisoformat(fields[0].strip()))
            except ValueError:
                pass
    if not tider:
        raise ValueError(f'Mangler lesbare tidsstempler: {path.name}')
    return min(tider), max(tider)


def scale(raw, factor, fmt_):
    try:
        x = float(raw) * factor
    except (TypeError, ValueError):
        return raw
    s = format(x, fmt_)
    return s.rstrip('0').rstrip('.') if '.' in s else s


def split_body(sample):
    pos = sample.find(' ')
    return (sample[:pos], sample[pos+1:]) if pos > 0 else ('', sample)


def iso(date, tod):
    return (date + 'T' + tod) if date and tod else (tod or '')


def convert(kilde, destinasjon, metadata):
    """Uendret kjerne fra originalen: én rad per hendelse/sample og 38 kolonner."""
    rows = []
    with kilde.open(newline='', encoding='utf-8-sig') as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if not header:
            raise ValueError('Tom CSV-fil')
        matches = [i for i, name in enumerate(header) if name.strip().lower() == 'stream']
        if len(matches) != 1 or not 1 <= matches[0] <= 9:
            raise ValueError('Forventet én stream-kolonne etter 0–8 c-kolonner')
        c_count = matches[0] - 1
        for fields in reader:
            if not any(f.strip() for f in fields):
                continue
            logger_time = fields[0].strip()
            date_part = logger_time[:10] if len(logger_time) >= 10 else ''
            stream = fields[1+c_count] if len(fields) > 1+c_count else ''
            events = fields[2+c_count] if len(fields) > 2+c_count else ''

            for sample in stream.split(';'):
                body = sample.strip()
                if not body:
                    continue
                recv_time, body = split_body(body)
                line = [''] * len(HEADER)
                line[0] = iso(date_part, recv_time)
                w = body.split(',')
                t = w[0].strip().upper()
                if t == 'S':
                    for k in range(1, min(len(w), 10)):
                        line[9+k-1] = w[k]
                    line[15] = scale(line[15], .01, '.2f')
                    line[16] = scale(line[16], .1, '.1f')
                    line[17] = scale(line[17], .01, '.2f')
                elif t == 'W':
                    for k in range(1, min(len(w), 6)):
                        line[18+k-1] = w[k]
                elif t:
                    line[36] = body
                rows.append(line)

            for ev in events.split(';'):
                body = ev.strip()
                if not body:
                    continue
                recv_time, body = split_body(body)
                line = [''] * len(HEADER)
                line[0] = iso(date_part, recv_time)
                if body.startswith('RX:'):
                    word = body[3:]
                    w = word.split(',')
                    t = w[0].strip().upper()
                    if t == 'K' and len(w) > 1:
                        for k in range(1, min(len(w), 7)):
                            line[29+k-1] = w[k]
                    elif len(t) > 1 and t.startswith('J'):
                        line[35] = word[1:]
                    elif t == 'R' and len(w) > 1:
                        for k in range(1, min(len(w), 7)):
                            line[23+k-1] = w[k]
                    line[36] = body
                elif body.startswith('R:'):
                    line[37] = body[2:]
                else:
                    line[36] = body
                rows.append(line)

            line = [''] * len(HEADER)
            line[0] = logger_time
            any_c = False
            for c in range(min(c_count, 8)):
                v = fields[1+c] if len(fields) > 1+c else ''
                if v:
                    line[1+c] = v
                    any_c = True
            if any_c:
                rows.append(line)

    rows.sort(key=lambda row: row[0])
    with destinasjon.open('w', newline='', encoding='utf-8-sig') as fh:
        writer = csv.writer(fh, lineterminator='\r\n')
        writer.writerow(EXTRA + HEADER)
        writer.writerows(metadata + row for row in rows)
    return len(rows)


def lag_metadata(param, excelrad, lag):
    r = excelrad or {}
    return [r.get('sveis', ''), lag, param['type'], param['strom'],
            param['fart'], param['trad'],
            param['overlapp'] if param['overlapp'] is not None else '',
            param['beskrivelse'],
            r.get('dybde', ''), r.get('bredde', ''), r.get('steg', ''),
            r.get('faktisk', ''), r.get('kommentar', '')]


def lag_navn(param, excelrad, lag):
    a, f, d = fmt(param['strom']), fmt(param['fart']), fmt(param['trad'])
    if param.get('har_pl') or param.get('beskrivelse'):
        # Behold HELE originalnavnet: PL-varianter og fri beskrivelse blandes aldri.
        prefix = param['opprinnelig_navn']
    elif excelrad is not None:
        prefix = f"Sveis_{excelrad['sveis']}_{a}_{f}"
    else:
        prefix = f"{param['type']}_{a}_{f}"
        if param['overlapp'] is not None:
            prefix += f"_{fmt(param['overlapp'])}pct"
        prefix += f'_{d}mm'
    return f'{prefix}_Lag_{lag:02d}.csv'


def main():
    if not HOVEDMAPPE.is_dir():
        print('Fant ikke rådatamappen:', HOVEDMAPPE)
        return
    if not EXCEL_FIL.is_file():
        print('Fant ikke Excel-filen:', EXCEL_FIL)
        return
    try:
        oversikt = les_excel()
    except Exception as ex:
        print('Kunne ikke lese Excel:', ex)
        return

    print('MODUS:', 'LAGRE' if SKRIV_FILER else 'FORHÅNDSVISNING (skriver ingenting)')
    planlagte, hoppet_over = 0, 0
    for mappe in sorted(p for p in HOVEDMAPPE.rglob('*') if p.is_dir()):
        # Resultater skrives et annet sted og skal aldri mates inn igjen
        if mappe == UTMAPPE or UTMAPPE in mappe.parents:
            continue
        filer = [p for p in mappe.glob('*.csv') if not p.name.lower().endswith('_static.csv')]
        if not filer:
            continue
        print(f'\nMAPPE: {mappe.relative_to(HOVEDMAPPE)}')
        param = les_mappenavn(mappe.name)
        if param is None:
            print('  HOPPER OVER: Mappenavnet kan ikke tolkes')
            hoppet_over += len(filer)
            continue
        if param['beskrivelse']:
            print('  Beskrivelse:', param['beskrivelse'])

        excelrad, status = finn_excelrad(mappe, param, oversikt)
        print('  Excel:', status)
        if not er_spesialtest(param) and excelrad is None:
            print('  HOPPER OVER: Må identifisere riktig sveis først')
            hoppet_over += len(filer)
            continue

        try:
            tidsdata = [(p, *les_logger_tidsrom(p)) for p in filer]
            tidsdata.sort(key=lambda x: x[1])
            problemer = []
            for prev, curr in zip(tidsdata, tidsdata[1:]):
                pause = (curr[1] - prev[2]).total_seconds() / 60
                if pause > MAKS_PAUSE_MIN:
                    problemer.append(f'{prev[0].name} -> {curr[0].name}: {pause:.1f} min')
                elif pause < 0:
                    problemer.append(f'{prev[0].name} -> {curr[0].name}: overlappende tidsrom')
        except Exception as ex:
            print('  HOPPER OVER: Tidsproblem:', ex)
            hoppet_over += len(filer)
            continue
        if problemer:
            print('  HOPPER OVER: Mulig ny sveis / tidsproblem:')
            for p in problemer:
                print('   ', p)
            hoppet_over += len(filer)
            continue

        # Behold dagsmapper og andre relative undernivåer i utdata
        destmappe = UTMAPPE / mappe.relative_to(HOVEDMAPPE)
        planer = []
        for lag, (kilde, start, slutt) in enumerate(tidsdata, 1):
            navn = lag_navn(param, excelrad, lag)
            dest = destmappe / navn
            print(f'  {kilde.name} -> {navn}')
            planer.append((kilde, dest, lag_metadata(param, excelrad, lag)))

        # Først forhåndsjekk om én fil allerede finnes: ikke skriv delvis
        eksisterende = [dest for _, dest, _ in planer if dest.exists()]
        if eksisterende:
            print('  HOPPER OVER: Resultatfil finnes allerede:', ', '.join(p.name for p in eksisterende))
            hoppet_over += len(planer)
            continue
        planlagte += len(planer)
        if SKRIV_FILER:
            destmappe.mkdir(parents=True, exist_ok=True)
            for kilde, dest, metadata in planer:
                try:
                    n = convert(kilde, dest, metadata)
                    print(f'    Lagret {n} rader')
                except Exception as ex:
                    print(f'    FEIL ved {kilde.name}: {ex}')
                    # Fjern eventuell ufullstendig resultatfil
                    if dest.exists():
                        dest.unlink()
                    hoppet_over += 1

    print(f'\nFerdig. {planlagte} filer planlagt, {hoppet_over} hoppet over.')
    if not SKRIV_FILER:
        print('Kontroller navnene og endre SKRIV_FILER = True for å lagre.')


if __name__ == '__main__':
    main()
