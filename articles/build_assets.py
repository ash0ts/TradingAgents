"""Regenerate the article's public figure from the frozen showcase payload."""

import csv
import hashlib
import json
import statistics
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / "notebooks/data/showcase.json"
PAYLOAD = json.loads(SOURCE.read_text())
EXPECTED = "f565efe5b288eaf93540484801b2f79e5f5bf8b2242ed9a3223428b797c10096"
assert PAYLOAD["public_data_sha256"] == EXPECTED
body = {key: value for key, value in PAYLOAD.items() if key != "public_data_sha256"}
encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
assert hashlib.sha256(encoded).hexdigest() == EXPECTED
ASSETS = ROOT / "did-it-beat-doing-nothing/assets"
METHODS = [
    ("equal-weight", "Equal-weight basket"),
    ("SPY", "SPY"),
    ("cash", "Cash (no interest)"),
    ("momentum-20", "Momentum (20)"),
    ("mean-reversion-5", "Mean reversion (5)"),
    ("AR-5", "AR(5)"),
    ("ridge", "Ridge"),
    ("XGBoost", "XGBoost"),
    ("DLinear", "DLinear"),
    ("chronos-bolt-small", "Chronos Bolt Small"),
    ("default-committee", "Luna/Sol committee"),
    ("luna-committee", "All-Luna committee"),
    ("single-luna", "Single Luna analyst"),
]
rows = []
for treatment, label in METHODS:
    selected = [
        row for row in PAYLOAD["portfolios"]
        if row["treatment"] == treatment
        and row["bps_per_side"] == 10
        and row["status"] == "matured"
    ]
    dates = {row["decision_date"] for row in selected}
    assert len(dates) == 8
    rows.append({
        "treatment": treatment,
        "label": label,
        "mean_trading_pnl_usd": statistics.mean(row["trading_pnl"] for row in selected),
        "mean_invested_exposure_pct": 100 * statistics.mean(row["exposure_at_entry"] for row in selected),
        "matured_decision_dates": len(dates),
        "scenario_count_including_trials": len(selected),
        "initial_cash_usd": 100000,
        "bps_per_side": 10,
        "horizon_sessions": 5,
    })

with (ASSETS / "portfolio-pnl.csv").open("w", newline="") as file:
    writer = csv.DictWriter(file, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 12, "svg.fonttype": "none"})
fig, ax = plt.subplots(figsize=(4.5, 9.1), dpi=160)
fig.patch.set_facecolor("#fcfaf6")
ax.set_facecolor("#fcfaf6")
fig.subplots_adjust(left=.45, right=.98, bottom=.10, top=.87)
fig.text(.025, .975, "Five-session trading P&L", va="top", fontsize=17, weight="bold", color="#172633")
fig.text(.025, .935, "$100,000 per independent scenario\nEight matured dates · fees included", va="top", fontsize=12, linespacing=1.5, color="#46535d")
for i, row in enumerate(rows):
    value = row["mean_trading_pnl_usd"]
    color = "#226d86" if i >= 10 else "#8c9799"
    ax.barh(i, value, color=color, height=.57)
    if abs(value) < .00001:
        ax.plot(0, i, marker="|", color="#46535d", markersize=13)
    label = ("−" if value < 0 else "") + f"${abs(value):,.2f}"
    ax.text(max(value, 0) + 22, i, label, va="center", fontsize=12.5, color="#172633")
ax.set_yticks(range(len(rows)), [row["label"] for row in rows], fontsize=12.5)
ax.set_xlim(-110, 1100)
ax.set_ylim(len(rows)-.35, -.65)
ax.axvline(0, color="#67757a", linewidth=.9, zorder=0)
ax.set_xticks([0, 400, 800])
ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"${value:,.0f}"))
ax.tick_params(axis="both", length=0, pad=8, labelcolor="#33464e")
ax.grid(axis="x", color="#dce0de", linewidth=.6)
ax.set_axisbelow(True)
for spine in ax.spines.values():
    spine.set_visible(False)
for y in [2.6, 9.6]:
    ax.axhline(y, color="#dce0de", linewidth=.6)
fig.text(.025, .025, "Two agent trials/date; others one.\nModel costs excluded; exposure differs.", fontsize=11.5, color="#46535d", linespacing=1.5)
for suffix in ["png", "svg"]:
    fig.savefig(ASSETS / f"portfolio-pnl.{suffix}", facecolor=fig.get_facecolor())
plt.close(fig)
receipt = {
    "source": "notebooks/data/showcase.json",
    "public_data_sha256": EXPECTED,
    "source_file_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
    "matplotlib_version": matplotlib.__version__,
    "question": "How much did each method earn under the specified portfolio rule?",
    "limits": "Descriptive independent-scenario means; unequal exposure; no significance or compounded performance claim.",
    "assets": {
        file.name: hashlib.sha256(file.read_bytes()).hexdigest()
        for file in ASSETS.glob("portfolio-pnl.*")
    },
}
(ROOT / "did-it-beat-doing-nothing/figure-provenance.json").write_text(json.dumps(receipt, indent=2) + "\n")
print(f"Rendered {len(rows)} methods from {EXPECTED}")
