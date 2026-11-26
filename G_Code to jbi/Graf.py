import sys
import numpy as np
import matplotlib.pyplot as plt

# Read the MTS text file (tab-separated, decimal comma, header lines)
from pathlib import Path
folder = Path(__file__).parent
txt_files = list(folder.glob("*.txt"))
print("Found:", [f.name for f in txt_files])
file = txt_files[0]
x, F = [], []
with open(file, encoding="utf-8", errors="ignore") as fh:
    for line in fh:
        parts = line.replace(",", ".").split()
        try:
            x.append(float(parts[0]))
            F.append(float(parts[1]) * 1000)   # kN -> N
        except (ValueError, IndexError):
            continue

x, F = np.array(x), np.array(F)
i = np.argmax(F)
print(f"Max force: {F[i]:.1f} N at {x[i]:.2f} mm")

# Plot
plt.figure(figsize=(7, 4.3))
plt.plot(x, F, color="tab:blue")
plt.plot(x[i], F[i], "o", color="tab:blue")
plt.annotate(f"Max force = {F[i]:.0f} N", (x[i], F[i]),
             xytext=(10, 8), textcoords="offset points")
plt.xlabel("Crosshead displacement [mm]")
plt.ylabel("Force [N]")
plt.ylim(0, F.max() * 1.15)
plt.grid(alpha=0.3)
plt.tight_layout()
plt.savefig("force_displacement.png", dpi=300)
plt.show()