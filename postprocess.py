#Mål med programmet: Oversette dtata fra sveisetester til lesbare notater
#Ny endringer ønsker å kunne bytte alle navn til sveiseparameter (strøm og fart) og hvilket lag det er på
# Ønaker og å legge til Dybde bredde og komentar fra excel skjema med fysiske notater fra oppsettet
# !/usr/bin/env python3
# postprocess.py - the welding-log static-column canonicalizer (the python
# twin of postprocess.exe, THE SAME CANON: 38 columns, one row per sample/
# event at its own moment, ALL timestamps sorted to the left, the raw words
# verbatim and QUOTED at the end. The presentation layer: the decimals IN
# the S-word's own columns (v x0.01 V, i x0.1 A, wfs x0.01 m/min); the
# original log = the raw vault, never touched; the output lands BESIDE the
# input (<name>_static.csv). Stdlib only - no installs, any python 3.
# Usage: python3 postprocess.py <file-or-folder>   (a folder = every *.csv)
import csv
import os
import sys

HEADER = ["time",
          "c1","c2","c3","c4","c5","c6","c7","c8",
          "S_x","S_y","S_z","S_nx","S_ny","S_nz","S_v","S_i","S_wfs",
          "W_I","W_V","W_WFS","W_kW","W_kJ",
          "R_1","R_2","R_3","R_4","R_5","R_6",
          "K_1","K_2","K_3","K_4","K_5","K_6",
          "J_job",
          "word", "rule_log"]
COL_TIME, COL_C1, COL_S, COL_W, COL_R, COL_K, COL_J, COL_WORD, COL_RULE = 0, 1, 9, 18, 23, 29, 35, 36, 37


def scale(raw, factor, fmt):
    # the decimal at its correct place: raw x factor, the malformed value
    # passes through verbatim (the honest fallback)
    try:
        v = float(raw) * factor
    except (TypeError, ValueError):
        return raw
    s = format(v, fmt)
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def iso(date_part, time_of_day):
    # the recv times carry no date: the date = the logger row's own day
    if not time_of_day:
        return ""
    if not date_part:
        return time_of_day
    return date_part + "T" + time_of_day


def split_body(sample):
    # "<HH:MM:SS.fff> <body>" -> (recv_time, body)
    sp = sample.find(" ")
    if sp > 0:
        return sample[:sp], sample[sp + 1:]
    return "", sample


def convert(path):
    out_path = os.path.join(os.path.dirname(path) or ".",
                            os.path.splitext(os.path.basename(path))[0] + "_static.csv")
    rows = []
    in_rows = 0
    c_count = 0
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for idx, fields in enumerate(csv.reader(fh)):
            if idx == 0:
                # the input header: timestamp[,c1..c8],stream,events - the map
                for i, f in enumerate(fields):
                    if f.strip().lower() == "stream":
                        c_count = i - 1
                        break
                continue
            if not any(f.strip() for f in fields):
                continue
            in_rows += 1
            line = ["" for _ in HEADER]
            logger_time = fields[0].strip()
            date_part = logger_time[:10] if len(logger_time) >= 10 else ""
            stream_cell = fields[1 + c_count] if len(fields) > 1 + c_count else ""
            events_cell = fields[2 + c_count] if len(fields) > 2 + c_count else ""

            # every stream sample = its own row at its own moment
            for sample in stream_cell.split(";"):
                body = sample.strip()
                if not body:
                    continue
                recv_time, body = split_body(body)
                line = ["" for _ in HEADER]
                line[COL_TIME] = iso(date_part, recv_time)
                w = body.split(",")
                t = w[0].strip().upper()
                if t == "S":
                    for k in range(1, min(len(w), 10)):
                        line[COL_S + k - 1] = w[k]     # x..wfs: NINE values
                    # the decimals in their correct places (the presentation layer)
                    line[COL_S + 6] = scale(line[COL_S + 6], 0.01, ".2f")   # v x0.01 V
                    line[COL_S + 7] = scale(line[COL_S + 7], 0.1, ".1f")    # i x0.1 A
                    line[COL_S + 8] = scale(line[COL_S + 8], 0.01, ".2f")  # wfs x0.01 m/min
                elif t == "W":
                    for k in range(1, min(len(w), 6)):
                        line[COL_W + k - 1] = w[k]
                elif t:
                    line[COL_WORD] = body
                rows.append(list(line))

            # every event = its own row at its own moment
            for ev in events_cell.split(";"):
                body = ev.strip()
                if not body:
                    continue
                recv_time, body = split_body(body)
                line = ["" for _ in HEADER]
                line[COL_TIME] = iso(date_part, recv_time)
                if body.startswith("RX:"):
                    word = body[3:]
                    w = word.split(",")
                    t = w[0].strip().upper()
                    if t == "K" and len(w) > 1:
                        for k in range(1, min(len(w), 7)):
                            line[COL_K + k - 1] = w[k]
                    elif len(t) > 1 and t[0] == "J":
                        line[COL_J] = word[1:]
                    elif t == "R" and len(w) > 1:
                        for k in range(1, min(len(w), 7)):
                            line[COL_R + k - 1] = w[k]
                    # (the E-word: parked - no column; the raw word rides verbatim)
                    line[COL_WORD] = body   # every RX word verbatim, the last columns
                elif body.startswith("R:"):
                    line[COL_RULE] = body[2:]   # the logger's own rule-firing log
                else:
                    line[COL_WORD] = body
                rows.append(list(line))

            # the logger tick row itself (the c-values): a row when any c is present
            line = ["" for _ in HEADER]
            line[COL_TIME] = logger_time
            any_c = False
            for c in range(min(c_count, 8)):
                v = fields[1 + c] if len(fields) > 1 + c else ""
                if v:
                    line[COL_C1 + c] = v
                    any_c = True
            if any_c:
                rows.append(list(line))

    # ONE time field, the rows SORTED by it (the sample's own moment, not
    # the logger's arrival order; the stable sort keeps the arrival order
    # of equals)
    rows.sort(key=lambda r: r[COL_TIME])
    # the output: BOM + CRLF + RFC 4180 minimal quoting (the raw words carry
    # commas - QUOTED, or they spill past the columns)
    with open(out_path, "w", newline="", encoding="utf-8-sig") as fh:
        wtr = csv.writer(fh, lineterminator="\r\n")
        wtr.writerow(HEADER)
        for r in rows:
            wtr.writerow(r)
    print(os.path.basename(path) + ": " + str(in_rows) + " log rows -> " +
          str(len(rows)) + " static rows (time-sorted) -> " + os.path.basename(out_path))


def main(argv):
    if len(argv) < 2:
        print("usage: python3 postprocess.py <file-or-folder>")
        return 1
    target = argv[1]
    files = []
    if os.path.isdir(target):
        for f in sorted(os.listdir(target)):
            # the glob quirk guard: only true .csv (never the LibreOffice .csv# locks)
            if f.lower().endswith(".csv"):
                files.append(os.path.join(target, f))
    elif os.path.isfile(target):
        files.append(target)
    else:
        print("not found: " + target)
        return 1
    ok = 0
    for f in files:
        if f.lower().endswith("_static.csv"):
            continue   # never re-eat our own output
        try:
            convert(f)
            ok += 1
        except Exception as ex:
            print("FAILED " + os.path.basename(f) + ": " + str(ex))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
