from pathlib import Path
import csv
import re
import matplotlib.pyplot as plt

# ============================================================
# ENDRBARE VERDIER
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
INNFIL = BASE_DIR / "Analyse_L_U" / '11' / "Hjorneoversikt.csv"
UTMAPPE = BASE_DIR / "Analyse_L_U" / '11'

LAGRE_FILER = True
VIS_GRAFER = True

# ============================================================
# HJELPEFUNKSJONER
# ============================================================

def to_float(verdi):
    try:
        return float(str(verdi).replace(",", "."))
    except (ValueError, TypeError):
        return None


def finn_test_og_lag(filnavn):
    navn = Path(filnavn).stem

    # Eksempel:
    # L_7_AV_PL_8_Lag_13 -> ("L_7_AV_PL_8", 13)
    match = re.fullmatch(
        r"(.+)_Lag_(\d+)",
        navn,
        re.IGNORECASE
    )

    if not match:
        raise ValueError(f"Ukjent filnavn: {filnavn}")

    testnavn = match.group(1)
    lagnummer = int(match.group(2))

    return testnavn, lagnummer


# ============================================================
# LES DATA
# ============================================================

rader = []
grupper = {}
brukte_filer = set()

with open(INNFIL, newline="", encoding="utf-8-sig") as fh:
    reader = csv.DictReader(fh)

    for rad in reader:

        filnavn = rad["Fil"].strip()

        testnavn, lagnummer = finn_test_og_lag(filnavn)

        rett = to_float(rad["Rett_hastighet_mm_s"])
        hjorne = to_float(rad["Hjorne_hastighet_mm_s"])

        if rett is None or hjorne is None or rett == 0:
            print(f"Hopper over ugyldige data: {filnavn}")
            continue

        # Unngå at samme fil telles flere ganger
        nokkel = (testnavn, lagnummer)

        if nokkel in brukte_filer:
            raise ValueError(
                f"Duplikat for test {testnavn}, lag {lagnummer}. "
                f"Kontroller Hjorneoversikt.csv."
            )

        brukte_filer.add(nokkel)

        reduksjon_pct = (1 - hjorne / rett) * 100

        ny_rad = {
            "Fil": filnavn,
            "Test": testnavn,
            "Lag": lagnummer,
            "Rett_hastighet_mm_s": rett,
            "Hjorne_hastighet_mm_s": hjorne,
            "Fartsreduksjon_pct": reduksjon_pct,
            "Volumforhold_hjorne_rett":
                to_float(rad["Volumforhold_hjorne_rett"]),
            "Beregnet_hastighet_for_lik_tilforsel_mm_s":
                to_float(rad["Beregnet_hastighet_for_lik_tilforsel_mm_s"]),
        }

        rader.append(ny_rad)

        # Grupper etter HELE testnavnet
        grupper.setdefault(testnavn, []).append(ny_rad)


if not rader:
    raise SystemExit("Fant ingen gyldige data.")

UTMAPPE.mkdir(parents=True, exist_ok=True)

# ============================================================
# LAG NY CSV
# ============================================================

rader.sort(key=lambda rad: (rad["Test"], rad["Lag"]))

utcsv = UTMAPPE / "Hjorneoversikt_med_fartsreduksjon.csv"

with open(utcsv, "w", newline="", encoding="utf-8-sig") as fh:

    writer = csv.DictWriter(
        fh,
        fieldnames=[
            "Fil",
            "Test",
            "Lag",
            "Rett_hastighet_mm_s",
            "Hjorne_hastighet_mm_s",
            "Fartsreduksjon_pct",
            "Volumforhold_hjorne_rett",
            "Beregnet_hastighet_for_lik_tilforsel_mm_s",
        ],
    )

    writer.writeheader()
    writer.writerows(rader)

print(f"Lagret: {utcsv}")

# ============================================================
# GRAFER: EN PER TEST
# ============================================================

for testnavn, data in sorted(grupper.items()):

    data.sort(key=lambda rad: rad["Lag"])

    lag = [rad["Lag"] for rad in data]
    reduksjon = [rad["Fartsreduksjon_pct"] for rad in data]

    print(f"\nTest: {testnavn}")
    print(f"Antall lag: {len(lag)}")
    print(f"Lagnummer: {lag}")

    fig, ax = plt.subplots(figsize=(11, 5))

    stolper = ax.bar(lag, reduksjon, width=0.65)

    # Prosentverdi ved hver stolpe
    for stolpe, verdi in zip(stolper, reduksjon):

        offset = 4 if verdi >= 0 else -4
        vertikal = "bottom" if verdi >= 0 else "top"

        ax.annotate(
            f"{verdi:.1f} %",
            (
                stolpe.get_x() + stolpe.get_width() / 2,
                stolpe.get_height()
            ),
            xytext=(0, offset),
            textcoords="offset points",
            ha="center",
            va=vertikal,
            fontsize=9
        )

    ax.axhline(0, color="black", linewidth=0.8)

    ax.set_title(f"{testnavn} – fartsreduksjon per lag")
    ax.set_xlabel("Lagnummer")
    ax.set_ylabel("Fartsreduksjon (%)")

    ax.set_xticks(lag)
    ax.set_xticklabels([f"{nr:02d}" for nr in lag])

    laveste = min(0, min(reduksjon))
    hoyeste = max(0, max(reduksjon))

    margin = max(0.3, (hoyeste - laveste) * 0.2)

    ax.set_ylim(
        laveste - margin,
        hoyeste + margin
    )

    ax.grid(axis="y", alpha=0.2)
    ax.set_axisbelow(True)

    fig.tight_layout()

    utfil = UTMAPPE / f"Fartsreduksjon_{testnavn}.png"

    if LAGRE_FILER:
        fig.savefig(utfil, dpi=200)
        print(f"Lagret: {utfil}")

    if VIS_GRAFER:
        plt.show()

    plt.close(fig)

print("\nFerdig.")