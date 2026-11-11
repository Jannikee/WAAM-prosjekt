#!/usr/bin/env python3
"""Behandle hele mapper med PL-tørrkjøringer (én rålogg per test, flere lag).

Konverterer loggerens S/W/R/K/J-hendelser til samme 38-kolonners CSV-format
som Post_process.py, og deler S-posisjonene i lag etter tidsrekkefølge og Z.
Lager KUN behandlete CSV-filer, ingen analysefiler eller grafer.
"""

import csv
from datetime import datetime
from math import hypot
from pathlib import Path
from statistics import median

# ============================================================
# ENDRBARE VERDIER
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
RAAMAPPE = BASE_DIR / "Ubehandlet" / "10" / "PL_test"
UTMAPPE = BASE_DIR / "Behandlet_PL_test"

ANTALL_LAG = 15
LAGHOYDE_MM = 1.8
Z_RETNING = 1  # 1 = større logget Z for hvert nytt lag; -1 = mindre

# Z-posisjoner i RÅLOGGENS koordinatsystem (S_z), ikke Z i robotprogrammet.
# Fyll ut MAKSIMALT ÉN av disse, eller behold begge None for automatisk søk.
Z_LAG1_LOGG = None
Z_TOPP_LOGG = None

# Et lag kan variere litt i Z langs banen. Dette velger målingene som hører
# til nærmeste lag (under halvparten av laghøyden 1,8 mm).
Z_TOLERANSE_MM = 0.85

# Kontroller at hvert lag dekker omtrent hele L-banen på 120 mm.
FORVENTET_BANELENGDE_MM = 120.0
BANELENGDE_MIN_MM = 105.0
BANELENGDE_MAX_MM = 135.0
MIN_S_PUNKTER_PER_LAG = 40

# Beskytter eksisterende filer. Sett True når du vil erstatte gamle feilaktige lagfiler.
OVERSKRIV = False

# ============================================================
# FAST 38-KOLONNERS FORMAT (som eksisterende Post_process.py)
# ============================================================

HEADER = [
    "time", "c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8",
    "S_x", "S_y", "S_z", "S_nx", "S_ny", "S_nz", "S_v", "S_i", "S_wfs",
    "W_I", "W_V", "W_WFS", "W_kW", "W_kJ",
    "R_1", "R_2", "R_3", "R_4", "R_5", "R_6",
    "K_1", "K_2", "K_3", "K_4", "K_5", "K_6",
    "J_job", "word", "rule_log",
]
COL_S, COL_W, COL_R, COL_K, COL_J, COL_WORD, COL_RULE = 9, 18, 23, 29, 35, 36, 37


def scale(raw, factor, fmt):
    try:
        value = float(raw) * factor
    except (ValueError, TypeError):
        return raw
    result = format(value, fmt)
    return result.rstrip("0").rstrip(".") if "." in result else result


def timestamp(date_part, time_of_day):
    return f"{date_part}T{time_of_day}" if date_part and time_of_day else time_of_day


def split_body(sample):
    parts = sample.strip().split(" ", 1)
    return (parts[0], parts[1]) if len(parts) == 2 else ("", parts[0])


def parse_dt(value):
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def to_float(value):
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def raw_to_static_rows(path):
    """Samme radstruktur og S/W-skala som Post_process.py."""
    rows = []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames or "stream" not in reader.fieldnames:
            raise ValueError(f"Mangler 'stream'-kolonne: {path}")

        c_names = [f"c{i}" for i in range(1, 9)]
        for record in reader:
            logger_time = (record.get("timestamp") or "").strip()
            date_part = logger_time[:10]

            for sample in (record.get("stream") or "").split(";"):
                if not sample.strip():
                    continue
                clock, body = split_body(sample)
                parts = body.split(",")
                kind = parts[0].upper()
                row = [""] * len(HEADER)
                row[0] = timestamp(date_part, clock)

                if kind == "S":
                    for j, value in enumerate(parts[1:10]):
                        row[COL_S + j] = value
                    row[COL_S + 6] = scale(row[COL_S + 6], 0.01, ".2f")
                    row[COL_S + 7] = scale(row[COL_S + 7], 0.1, ".1f")
                    row[COL_S + 8] = scale(row[COL_S + 8], 0.01, ".2f")
                elif kind == "W":
                    for j, value in enumerate(parts[1:6]):
                        row[COL_W + j] = value
                else:
                    row[COL_WORD] = body
                rows.append(row)

            for event in (record.get("events") or "").split(";"):
                if not event.strip():
                    continue
                clock, body = split_body(event)
                row = [""] * len(HEADER)
                row[0] = timestamp(date_part, clock)
                if body.startswith("RX:"):
                    payload = body[3:]
                    parts = payload.split(",")
                    kind = parts[0].upper()
                    if kind in ("R", "K"):
                        start = COL_R if kind == "R" else COL_K
                        for j, value in enumerate(parts[1:7]):
                            row[start + j] = value
                    elif kind.startswith("J"):
                        row[COL_J] = payload[1:]
                    row[COL_WORD] = body
                elif body.startswith("R:"):
                    row[COL_RULE] = body[2:]
                else:
                    row[COL_WORD] = body
                rows.append(row)

            # Loggerens eventuelle c1...c8-verdier
            tick = [""] * len(HEADER)
            tick[0] = logger_time
            has_c = False
            for j, col in enumerate(c_names):
                value = record.get(col) or ""
                if value:
                    tick[1 + j] = value
                    has_c = True
            if has_c:
                rows.append(tick)

    rows.sort(key=lambda r: r[0])
    return rows


def find_first_level_auto(samples):
    """Finn første lange, horisontale L-strekning, ikke park-/Z-flytting.

    Ser etter 20 påfølgende målinger med betydelig XY-bevegelse og nesten
    konstant Z. Median-Z fra disse blir ankeret for lag 1.
    """
    n = 20
    for start in range(len(samples) - n + 1):
        part = samples[start:start + n]
        moves = [
            (hypot(b["x"] - a["x"], b["y"] - a["y"]), abs(b["z"] - a["z"]))
            for a, b in zip(part, part[1:])
        ]
        xy_total = sum(dxy for dxy, _ in moves)
        if (
            xy_total >= 25.0
            and max(dxy for dxy, _ in moves) <= 4.0
            and max(dz for _, dz in moves) <= 0.12
        ):
            return median(s["z"] for s in part)
    raise ValueError(
        "Fant ingen stabil horisontal startbane automatisk. "
        "Sett Z_LAG1_LOGG eller Z_TOPP_LOGG fra S_z i råloggen."
    )


def contiguous_runs(indices):
    if not indices:
        return []
    runs = []
    current = [indices[0]]
    for index in indices[1:]:
        if index == current[-1] + 1:
            current.append(index)
        else:
            runs.append(current)
            current = [index]
    runs.append(current)
    return runs


def xy_length(samples, run):
    return sum(
        hypot(samples[b]["x"] - samples[a]["x"],
              samples[b]["y"] - samples[a]["y"])
        for a, b in zip(run, run[1:])
    )


def split_into_layers(rows):
    samples = []
    for row in rows:
        if row[COL_S] == "" or row[COL_S + 1] == "" or row[COL_S + 2] == "":
            continue
        t = parse_dt(row[0])
        x, y, z = (to_float(row[COL_S + j]) for j in range(3))
        if t is not None and all(v is not None for v in (x, y, z)):
            samples.append({"t": t, "x": x, "y": y, "z": z})

    if len(samples) < ANTALL_LAG * MIN_S_PUNKTER_PER_LAG:
        raise ValueError(f"For få S-posisjonsmålinger: {len(samples)}")
    if Z_LAG1_LOGG is not None and Z_TOPP_LOGG is not None:
        raise ValueError("Sett bare én av Z_LAG1_LOGG og Z_TOPP_LOGG")
    if Z_LAG1_LOGG is not None:
        z_first = float(Z_LAG1_LOGG)
        z_source = "manuelt første lag"
    elif Z_TOPP_LOGG is not None:
        z_first = float(Z_TOPP_LOGG) - Z_RETNING * (ANTALL_LAG - 1) * LAGHOYDE_MM
        z_source = "manuelt topplag"
    else:
        z_first = find_first_level_auto(samples)
        z_source = "automatisk"

    target = [z_first + Z_RETNING * i * LAGHOYDE_MM for i in range(ANTALL_LAG)]
    selected = []
    previous_end = -1
    print(f"  Z for lag 1: {z_first:.3f} mm ({z_source})")

    for layer_idx, level in enumerate(target, 1):
        # De 15 lagene kan ikke være én sammenhengende fil her. Velg den
        # sammenhengende Z-sekvensen som faktisk dekker en hel L-bane.
        eligible = [i for i, s in enumerate(samples)
                    if i > previous_end and abs(s["z"] - level) <= Z_TOLERANSE_MM]
        runs = contiguous_runs(eligible)
        runs.sort(key=lambda run: xy_length(samples, run), reverse=True)
        if not runs:
            raise ValueError(f"Lag {layer_idx}: ingen S-punkter nær Z={level:.3f}")
        run = runs[0]
        distance = xy_length(samples, run)
        if len(run) < MIN_S_PUNKTER_PER_LAG or not BANELENGDE_MIN_MM <= distance <= BANELENGDE_MAX_MM:
            raise ValueError(
                f"Lag {layer_idx}: {len(run)} S-punkter, XY-lengde {distance:.1f} mm "
                f"(forventet ca. {FORVENTET_BANELENGDE_MM:.0f} mm). "
                "Ingen filer fra denne testen skrives. Kontroller Z-ankeret."
            )
        start_t, end_t = samples[run[0]]["t"], samples[run[-1]]["t"]
        if selected and start_t <= selected[-1][2]:
            raise ValueError(f"Lag {layer_idx}: overlapper med forrige lag i tid")
        selected.append((layer_idx, start_t, end_t, len(run), distance, level))
        previous_end = run[-1]
        print(f"  Lag {layer_idx:02}: Z={level:9.3f}, "
              f"S-punkter={len(run):3}, XY={distance:6.1f} mm")

    # Behold S- og W-målingene og eventuelle hendelser som tidsmessig faller
    # innenfor det enkelte lag. IKKE trekk sammen mellomlag og parkbevegelser.
    outputs = {}
    for idx, t0, t1, _, _, _ in selected:
        outputs[idx] = [row for row in rows
                        if (t := parse_dt(row[0])) is not None and t0 <= t <= t1]
    return outputs


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(HEADER)
        writer.writerows(rows)


def process_file(path):
    # Navnet på testmappen brukes uendret: L_7_AV_PL_8
    testname = path.parent.name
    print(f"\n=== {testname} ({path.name}) ===")
    rows = raw_to_static_rows(path)
    if not rows:
        raise ValueError("Råfilen inneholder ingen gyldige målinger")

    layers = split_into_layers(rows)  # Valider ALLE lag før noe skrives
    target_dir = UTMAPPE / testname
    output_paths = [target_dir / f"{testname}_Lag_{layer:02}.csv" for layer in layers]
    already = [p for p in output_paths if p.exists()]
    if already and not OVERSKRIV:
        print(f"  Hopper over test: {len(already)} filer finnes allerede. "
              "Sett OVERSKRIV=True når du vil regenerere.")
        return 0

    for layer, rows_for_layer in layers.items():
        output_path = target_dir / f"{testname}_Lag_{layer:02}.csv"
        write_csv(output_path, rows_for_layer)
    print(f"  Skrev {len(layers)} lagfiler til {target_dir}")
    return len(layers)


def main():
    if not RAAMAPPE.is_dir():
        raise SystemExit(f"Finner ikke rådatamappen: {RAAMAPPE}")
    files = sorted(RAAMAPPE.rglob("*.csv"))
    if not files:
        raise SystemExit(f"Fant ingen .csv-filer i {RAAMAPPE}")
    print(f"Rådatamappe: {RAAMAPPE}")
    print(f"Utmappe:     {UTMAPPE}")
    print(f"Fant {len(files)} råfiler")

    total, failed = 0, 0
    for path in files:
        try:
            total += process_file(path)
        except Exception as exc:
            failed += 1
            print(f"  FEIL i {path}: {exc}")
    print(f"\nFerdig: {total} lagfiler skrevet, {failed} råfiler feilet.")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
