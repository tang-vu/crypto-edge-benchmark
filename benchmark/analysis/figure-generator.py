"""
8.9 Publication figure generator for Springer Computing R1 revision.

Produces 5 figures (PDF + PNG each) for manuscript §5:
  1. fig-multiregion-warm       — avg warm latency by region, CF vs Vercel
  2. fig-burst-per-stage        — p95 by burst stage per (platform, mode)
  3. fig-cold-start-cross-region — cold-start avg by region CF vs Vercel (n=3)
  4. fig-ecdf-warm-multiregion  — ECDF per-request latency by region+platform
  5. fig-cost-perf-scatter      — already exists; verified and listed

Figure 6 (ramp-sensitivity) is skipped: ramp variant pipeline still running.

Output: benchmark/analysis/output/figures/
Usage:
    python figure-generator.py \\
        --output-dir   benchmark/analysis/output \\
        --revision-dir benchmark/results/r1-revision
"""

import argparse
import importlib.util
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # non-interactive backend for server/CI
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D

# ---------------------------------------------------------------------------
# Style constants — Springer-compatible
# ---------------------------------------------------------------------------
SERIF_FONT   = "DejaVu Serif"
SANS_FONT    = "DejaVu Sans"
BASE_SIZE    = 10
LABEL_SIZE   = 11
TITLE_SIZE   = 11
FIG_W_SINGLE = 3.5     # inches — single-column Springer
FIG_W_DOUBLE = 7.0     # inches — double-column Springer
FIG_H        = 3.2     # inches — comfortable height
DPI_PNG      = 300

PLT_DEFAULTS = {
    "font.size":        BASE_SIZE,
    "font.family":      "serif",
    "font.serif":       [SERIF_FONT, "Times New Roman", "serif"],
    "axes.labelsize":   LABEL_SIZE,
    "axes.titlesize":   TITLE_SIZE,
    "xtick.labelsize":  BASE_SIZE,
    "ytick.labelsize":  BASE_SIZE,
    "legend.fontsize":  BASE_SIZE - 1,
    "figure.dpi":       100,
    "axes.spines.top":  False,
    "axes.spines.right": False,
    "axes.grid":        True,
    "grid.alpha":       0.35,
    "grid.linestyle":   "--",
    "lines.linewidth":  1.5,
}
plt.rcParams.update(PLT_DEFAULTS)

# Platform colours — colourblind-safe (Wong palette)
CF_COLOR   = "#0072B2"   # blue  — Cloudflare
VC_COLOR   = "#D55E00"   # red-orange — Vercel
CF_COLOR2  = "#56B4E9"   # light blue — CF live variant
VC_COLOR2  = "#E69F00"   # orange — Vercel live variant

HATCH_MOCK = ""
HATCH_LIVE = "//"

# Region display order + labels
REGION_ORDER  = ["local", "us-east-1", "eu-west-1", "ap-southeast-1"]
REGION_LABELS = {
    "local":          "VN (local)",
    "us-east-1":      "US-East",
    "eu-west-1":      "EU-West",
    "ap-southeast-1": "AP-SE",
}

STAGE_ORDER  = ["ramp_up", "spike", "peak_hold", "ramp_down", "cooldown"]
STAGE_LABELS = {
    "ramp_up":   "Ramp-up\n(0-30s)",
    "spike":     "Spike\n(30-90s)",
    "peak_hold": "Peak\n(90-120s)",
    "ramp_down": "Ramp-down\n(120-180s)",
    "cooldown":  "Cooldown\n(180-210s)",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_THIS_DIR = Path(__file__).parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))


def _load_local(filename: str):
    path = _THIS_DIR / filename
    spec = importlib.util.spec_from_file_location(
        filename.replace("-", "_").replace(".py", ""), path
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _save(fig, out_dir: Path, stem: str) -> None:
    """Save figure as PDF (primary) and PNG (preview)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / f"{stem}.pdf"
    png_path = out_dir / f"{stem}.png"
    fig.savefig(str(pdf_path), format="pdf", bbox_inches="tight")
    fig.savefig(str(png_path), format="png", dpi=DPI_PNG, bbox_inches="tight")
    plt.close(fig)
    print(f"[fig] {stem}.pdf + .png")


def _add_value_labels(ax, bars, fmt="{:.1f}", fontsize=7, color="black"):
    """Annotate bar chart with value labels above each bar."""
    for bar in bars:
        h = bar.get_height()
        if not np.isnan(h) and h > 0:
            ax.text(
                bar.get_x() + bar.get_width() / 2.0,
                h + ax.get_ylim()[1] * 0.01,
                fmt.format(h),
                ha="center", va="bottom",
                fontsize=fontsize, color=color
            )


# ---------------------------------------------------------------------------
# Figure 1: Multi-region warm latency bar chart
# ---------------------------------------------------------------------------
def fig_multiregion_warm(rev_stats_csv: Path, out_dir: Path) -> None:
    """
    Dual-bar chart: x=region, y=avg warm latency ms,
    CF vs Vercel, mock mode only (live omitted for cleanliness).
    Error bars: bootstrap 95% CI half-width.
    """
    df = pd.read_csv(rev_stats_csv)
    warm = df[(df["scenario"] == "warm") & (df["mode"] == "mock")].copy()
    if warm.empty:
        print("[fig] fig-multiregion-warm: no warm/mock data, skipping")
        return

    cf  = warm[warm["platform"] == "cloudflare"].set_index("client")
    vc  = warm[warm["platform"] == "vercel"].set_index("client")

    regions = [r for r in REGION_ORDER if r in cf.index or r in vc.index]
    x       = np.arange(len(regions))
    width   = 0.35

    fig, ax = plt.subplots(figsize=(FIG_W_DOUBLE, FIG_H))

    cf_means = [cf.loc[r, "avg_mean_ms"] if r in cf.index else np.nan for r in regions]
    cf_errs  = [
        (cf.loc[r, "avg_mean_ms"] - cf.loc[r, "avg_ci95_low"],
         cf.loc[r, "avg_ci95_high"] - cf.loc[r, "avg_mean_ms"])
        if r in cf.index else (0, 0)
        for r in regions
    ]
    vc_means = [vc.loc[r, "avg_mean_ms"] if r in vc.index else np.nan for r in regions]
    vc_errs  = [
        (vc.loc[r, "avg_mean_ms"] - vc.loc[r, "avg_ci95_low"],
         vc.loc[r, "avg_ci95_high"] - vc.loc[r, "avg_mean_ms"])
        if r in vc.index else (0, 0)
        for r in regions
    ]

    cf_yerr = np.array(cf_errs).T  # shape (2, n_regions)
    vc_yerr = np.array(vc_errs).T

    bars_cf = ax.bar(x - width/2, cf_means, width,
                     label="Cloudflare Workers", color=CF_COLOR,
                     yerr=cf_yerr, capsize=3, error_kw={"elinewidth": 1})
    bars_vc = ax.bar(x + width/2, vc_means, width,
                     label="Vercel Functions", color=VC_COLOR,
                     yerr=vc_yerr, capsize=3, error_kw={"elinewidth": 1})

    ax.set_xticks(x)
    ax.set_xticklabels([REGION_LABELS.get(r, r) for r in regions])
    ax.set_ylabel("Avg warm latency (ms)")
    ax.set_xlabel("Client region")
    ax.set_title("Warm-path latency by region (mock mode, bootstrap 95 % CI)")
    ax.legend(loc="upper left", framealpha=0.8)
    ax.set_ylim(bottom=0)

    _add_value_labels(ax, bars_cf, fontsize=6.5)
    _add_value_labels(ax, bars_vc, fontsize=6.5)

    fig.tight_layout()
    _save(fig, out_dir, "fig-multiregion-warm")


# ---------------------------------------------------------------------------
# Figure 2: Per-stage burst p95 line chart
# ---------------------------------------------------------------------------
def fig_burst_per_stage(stage_csv: Path, out_dir: Path) -> None:
    """
    Line chart: x=stage, y=p95 latency ms, one line per (platform, mode).
    Uses TRUE per-stage data from CSV traces.
    """
    df = pd.read_csv(stage_csv)
    if df.empty:
        print("[fig] fig-burst-per-stage: no data, skipping")
        return

    # Aggregate across regions (mean over clients)
    agg = df.groupby(["platform", "mode", "stage"])["p95_ms"].mean().reset_index()

    stage_order_map = {s: i for i, (_, _, s, _) in enumerate(
        [("","","ramp_up",""), ("","","spike",""), ("","","peak_hold",""),
         ("","","ramp_down",""), ("","","cooldown","")]
    )}
    agg["_ord"] = agg["stage"].map(stage_order_map).fillna(99)
    agg = agg.sort_values("_ord")

    fig, ax = plt.subplots(figsize=(FIG_W_DOUBLE, FIG_H))

    styles = {
        ("cloudflare", "mock"): dict(color=CF_COLOR,  linestyle="-",  marker="o"),
        ("cloudflare", "live"): dict(color=CF_COLOR2, linestyle="--", marker="s"),
        ("vercel",     "mock"): dict(color=VC_COLOR,  linestyle="-",  marker="^"),
        ("vercel",     "live"): dict(color=VC_COLOR2, linestyle="--", marker="D"),
    }

    for (platform, mode), grp in agg.groupby(["platform", "mode"]):
        grp_sorted = grp.sort_values("_ord")
        stages_present = [s for s in STAGE_ORDER if s in grp_sorted["stage"].values]
        y_vals = [grp_sorted[grp_sorted["stage"] == s]["p95_ms"].values[0]
                  for s in stages_present]
        x_pos = [i for i, s in enumerate(STAGE_ORDER) if s in stages_present]
        label = f"{platform.capitalize()} ({mode})"
        kwargs = styles.get((platform, mode), {})
        ax.plot(x_pos, y_vals, label=label, markersize=5, **kwargs)

    ax.set_xticks(range(len(STAGE_ORDER)))
    ax.set_xticklabels([STAGE_LABELS[s] for s in STAGE_ORDER], fontsize=8)
    ax.set_ylabel("p95 latency (ms)")
    ax.set_xlabel("Burst stage")
    ax.set_title("Per-stage p95 latency during burst test (TRUE from k6 CSV traces)")
    ax.legend(loc="upper right", framealpha=0.8, ncol=2, fontsize=8)
    ax.set_ylim(bottom=0)

    fig.tight_layout()
    _save(fig, out_dir, "fig-burst-per-stage")


# ---------------------------------------------------------------------------
# Figure 3: Cold-start cross-region bar chart
# ---------------------------------------------------------------------------
def fig_cold_start_cross_region(cold_csv: Path, out_dir: Path) -> None:
    """
    Dual-bar chart: x=region, y=avg cold-start ms, CF vs Vercel, n=3 CIs.
    """
    df = pd.read_csv(cold_csv)
    mock = df[df["mode"] == "mock"].copy()
    if mock.empty:
        print("[fig] fig-cold-start-cross-region: no data, skipping")
        return

    cf = mock[mock["platform"] == "cloudflare"].set_index("client")
    vc = mock[mock["platform"] == "vercel"].set_index("client")

    regions = [r for r in REGION_ORDER if r in cf.index or r in vc.index]
    x       = np.arange(len(regions))
    width   = 0.35

    fig, ax = plt.subplots(figsize=(FIG_W_DOUBLE, FIG_H))

    def _get_val(tbl, col, r):
        return float(tbl.loc[r, col]) if r in tbl.index else np.nan

    cf_means = [_get_val(cf, "avg_mean_ms", r) for r in regions]
    vc_means = [_get_val(vc, "avg_mean_ms", r) for r in regions]
    cf_yerr  = np.array([[
        max(0, _get_val(cf, "avg_mean_ms", r) - _get_val(cf, "ci95_low_ms", r)),
        max(0, _get_val(cf, "ci95_high_ms", r) - _get_val(cf, "avg_mean_ms", r)),
    ] for r in regions]).T
    vc_yerr  = np.array([[
        max(0, _get_val(vc, "avg_mean_ms", r) - _get_val(vc, "ci95_low_ms", r)),
        max(0, _get_val(vc, "ci95_high_ms", r) - _get_val(vc, "avg_mean_ms", r)),
    ] for r in regions]).T

    ax.bar(x - width/2, cf_means, width, label="Cloudflare Workers",
           color=CF_COLOR, yerr=cf_yerr, capsize=3, error_kw={"elinewidth": 1})
    ax.bar(x + width/2, vc_means, width, label="Vercel Functions",
           color=VC_COLOR, yerr=vc_yerr, capsize=3, error_kw={"elinewidth": 1})

    ax.set_xticks(x)
    ax.set_xticklabels([REGION_LABELS.get(r, r) for r in regions])
    ax.set_ylabel("Avg cold-start latency (ms)")
    ax.set_xlabel("Client region")
    ax.set_title("Cold-start latency by region (n=3 runs/cell, bootstrap 95 % CI)")
    ax.legend(loc="upper left", framealpha=0.8)
    ax.set_ylim(bottom=0)

    fig.tight_layout()
    _save(fig, out_dir, "fig-cold-start-cross-region")


# ---------------------------------------------------------------------------
# Figure 4: ECDF of per-request latency by region + platform
# ---------------------------------------------------------------------------
def fig_ecdf_warm_multiregion(rev_dir: Path, out_dir: Path) -> None:
    """
    ECDF of per-request latency from burst CSV traces (mock mode only,
    filtered to ramp_up + spike stages for warm-ish traffic).
    One ECDF line per (region, platform) combination.
    Truncated at 99th percentile to avoid long-tail distortion.
    """
    csv_mod = _load_local("ingest-csv-traces.py")

    print("[fig] Loading burst CSV traces for ECDF (this may take ~30s) …")
    traces = csv_mod.ingest_csv_traces(str(rev_dir), scenario_filter="burst")
    if traces.empty:
        print("[fig] fig-ecdf-warm-multiregion: no trace data, skipping")
        return

    # Use ramp_up + spike stages as proxy for warm traffic (low VU count)
    warm_stages = traces[
        (traces["mode"] == "mock") &
        (traces["stage"].isin(["ramp_up", "spike"]))
    ]

    fig, axes = plt.subplots(
        1, len(REGION_ORDER),
        figsize=(FIG_W_DOUBLE * 1.3, FIG_H),
        sharey=True,
    )

    for ax, region in zip(axes, REGION_ORDER):
        for platform, color, ls in [
            ("cloudflare", CF_COLOR, "-"),
            ("vercel",     VC_COLOR, "--"),
        ]:
            sub = warm_stages[
                (warm_stages["client"] == region) &
                (warm_stages["platform"] == platform)
            ]["latency_ms"].values

            if len(sub) < 10:
                continue

            # Truncate at 99th percentile
            p99 = np.percentile(sub, 99)
            sub = sub[sub <= p99]

            sorted_vals = np.sort(sub)
            ecdf_y      = np.arange(1, len(sorted_vals) + 1) / len(sorted_vals)
            label       = platform.capitalize()
            ax.plot(sorted_vals, ecdf_y,
                    color=color, linestyle=ls,
                    linewidth=1.2, alpha=0.85,
                    label=label)

        ax.set_title(REGION_LABELS.get(region, region), fontsize=9)
        ax.set_xlabel("Latency (ms)", fontsize=8)
        ax.set_xlim(left=0)
        ax.set_ylim(0, 1.02)
        ax.tick_params(labelsize=7)
        ax.grid(True, alpha=0.3, linestyle="--")

    axes[0].set_ylabel("Empirical CDF")
    # Shared legend on last axis
    axes[-1].legend(loc="lower right", fontsize=7)

    fig.suptitle(
        "ECDF of per-request latency (burst mock, ramp-up+spike stages, ≤p99)",
        fontsize=9, y=1.01
    )
    fig.tight_layout()
    _save(fig, out_dir, "fig-ecdf-warm-multiregion")


# ---------------------------------------------------------------------------
# Figure 5: Cost-performance scatter (verify existing)
# ---------------------------------------------------------------------------
def verify_cost_perf_scatter(out_dir: Path) -> bool:
    """Confirm cost-perf-scatter.{pdf,png} exists; no re-generation needed."""
    pdf = out_dir / "cost-perf-scatter.pdf"
    png = out_dir / "cost-perf-scatter.png"
    if pdf.exists() and png.exists():
        print(f"[fig] cost-perf-scatter.pdf + .png  (already exists, verified)")
        return True
    print(f"[fig] WARNING: cost-perf-scatter missing at {out_dir}")
    return False


# ---------------------------------------------------------------------------
# figures-list.tex emitter
# ---------------------------------------------------------------------------
def emit_figures_list_tex(out_dir: Path, figures_tex_dir: Path) -> None:
    """
    Write r1-tables/figures-list.tex: one \item per figure with caption hint.
    """
    entries = [
        ("fig-multiregion-warm",
         r"Average warm-path latency by client region (mock mode). "
         r"Dual bars: Cloudflare Workers (CF) and Vercel Functions (VC). "
         r"Error bars: bootstrap 95\,\% CI. Highlights F-PIVOT regional dependency."),
        ("fig-burst-per-stage",
         r"Per-stage p95 latency during burst test (TRUE per-request, from k6 CSV "
         r"traces). Stages: ramp-up, spike, peak hold, ramp-down, cooldown. "
         r"Identifies the burst stage driving latency variance."),
        ("fig-cold-start-cross-region",
         r"Cold-start latency by region (n=3 runs per cell, bootstrap 95\,\% CI). "
         r"Replaces the n=1 descriptive table from the original submission."),
        ("fig-ecdf-warm-multiregion",
         r"Empirical CDF of per-request latency (burst mock, ramp-up + spike "
         r"stages, truncated at p99). Shows full distribution beyond summary "
         r"statistics; one panel per client region."),
        ("cost-perf-scatter",
         r"Cost-performance scatter plot: x = estimated monthly cost (USD), "
         r"y = mean warm latency (ms). Quadrant annotation highlights "
         r"Pareto-optimal platform per scenario."),
    ]

    lines = [
        r"\begin{itemize}",
    ]
    for stem, caption in entries:
        lines.append(
            rf"  \item \textbf{{\texttt{{{stem}.pdf}}}}: {caption}"
        )
    lines.append(r"\end{itemize}")

    tex_path = figures_tex_dir / "figures-list.tex"
    tex_path.parent.mkdir(parents=True, exist_ok=True)
    tex_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[tex] Written {tex_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="8.9 Publication figure generator")
    parser.add_argument("--output-dir",   default="benchmark/analysis/output")
    parser.add_argument("--revision-dir", default="benchmark/results/r1-revision")
    args = parser.parse_args()

    out_dir    = Path(args.output_dir)
    fig_dir    = out_dir / "figures"
    tables_dir = out_dir / "r1-tables"
    rev_dir    = Path(args.revision_dir)

    # Input CSVs
    rev_stats_csv = out_dir / "r1-revision-stats.csv"
    stage_csv     = out_dir / "r1-burst-per-stage-true.csv"
    cold_csv      = out_dir / "r1-cold-stats-n3.csv"

    print("=" * 60)
    print("8.9  Publication figure generation")
    print("=" * 60)

    # Fig 1: Multi-region warm
    print("\n[1/5] fig-multiregion-warm …")
    fig_multiregion_warm(rev_stats_csv, fig_dir)

    # Fig 2: Per-stage burst
    print("\n[2/5] fig-burst-per-stage …")
    if stage_csv.exists():
        fig_burst_per_stage(stage_csv, fig_dir)
    else:
        print(f"      SKIP: {stage_csv} not found (run 8.7 first)")

    # Fig 3: Cold-start cross-region
    print("\n[3/5] fig-cold-start-cross-region …")
    if cold_csv.exists():
        fig_cold_start_cross_region(cold_csv, fig_dir)
    else:
        print(f"      SKIP: {cold_csv} not found")

    # Fig 4: ECDF
    print("\n[4/5] fig-ecdf-warm-multiregion …")
    fig_ecdf_warm_multiregion(rev_dir, fig_dir)

    # Fig 5: Cost-perf scatter (verify)
    print("\n[5/5] cost-perf-scatter (verify) …")
    verify_cost_perf_scatter(fig_dir)

    # figures-list.tex
    print("\n[+] figures-list.tex …")
    emit_figures_list_tex(fig_dir, tables_dir)

    print("\n" + "=" * 60)
    print(f"Figures written to: {fig_dir.resolve()}")
    print("=" * 60)


if __name__ == "__main__":
    main()
