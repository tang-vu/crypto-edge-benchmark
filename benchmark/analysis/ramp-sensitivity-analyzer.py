"""
Ramp-rate sensitivity analysis for Phase 8 Task A.
Computes per-cell stats from burst-slow and burst-fast JSON results,
compares against normal burst (existing r1-revision burst runs).
Outputs: r1-ramp-sensitivity.csv, r1-tables/ramp-sensitivity.tex, figures/fig-ramp-sensitivity.{pdf,png}
"""

import json
import os
import glob
import csv
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# ── paths ──────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT  = os.path.dirname(os.path.dirname(SCRIPT_DIR))
BASE_DIR   = os.path.join(REPO_ROOT, "benchmark", "results", "r1-revision", "local")
OUT_DIR    = os.path.join(REPO_ROOT, "benchmark", "analysis", "output")
TABLES_DIR = os.path.join(OUT_DIR, "r1-tables")
FIGS_DIR   = os.path.join(OUT_DIR, "figures")
os.makedirs(TABLES_DIR, exist_ok=True)
os.makedirs(FIGS_DIR,   exist_ok=True)


def load_json_metrics(filepath):
    """Extract http_req_duration stats from a k6 JSON summary file."""
    with open(filepath) as f:
        d = json.load(f)
    m = d.get("metrics", {}).get("http_req_duration", {})
    v = m.get("values", {})
    return {
        "avg": v.get("avg"),
        "p95": v.get("p(95)"),
        "p90": v.get("p(90)"),
        "min": v.get("min"),
        "max": v.get("max"),
        "med": v.get("med"),
    }


def collect_ramp_variant(platform_dir_name, ramp_label, pattern):
    """
    Collect stats from burst variant runs for one platform + ramp rate.
    pattern: glob pattern relative to BASE_DIR/platform_dir_name/
    Returns list of dicts with per-run stats.
    """
    runs = []
    search_path = os.path.join(BASE_DIR, platform_dir_name, pattern)
    files = sorted(glob.glob(search_path))
    json_files = [f for f in files if f.endswith(".json")]
    for fp in json_files:
        stats = load_json_metrics(fp)
        stats["platform"] = platform_dir_name
        stats["ramp"] = ramp_label
        stats["run_file"] = os.path.basename(fp)
        runs.append(stats)
    return runs


def bootstrap_ci(values, n_boot=5000, ci=0.95, seed=42):
    """Compute bootstrap percentile CI for mean of values."""
    rng = np.random.default_rng(seed)
    arr = np.array(values, dtype=float)
    boot_means = np.array([np.mean(rng.choice(arr, size=len(arr), replace=True))
                           for _ in range(n_boot)])
    lo = np.percentile(boot_means, (1 - ci) / 2 * 100)
    hi = np.percentile(boot_means, (1 + ci) / 2 * 100)
    return lo, hi


def aggregate_runs(runs):
    """Aggregate list-of-run-dicts → mean/std/p95_mean over runs."""
    avgs = [r["avg"] for r in runs if r["avg"] is not None]
    p95s = [r["p95"] for r in runs if r["p95"] is not None]
    if not avgs:
        return None
    ci_lo, ci_hi = bootstrap_ci(avgs) if len(avgs) >= 2 else (None, None)
    return {
        "n":       len(avgs),
        "avg_mean": np.mean(avgs),
        "avg_std":  np.std(avgs, ddof=1) if len(avgs) > 1 else 0.0,
        "p95_mean": np.mean(p95s),
        "p95_std":  np.std(p95s, ddof=1) if len(p95s) > 1 else 0.0,
        "ci_lo":   ci_lo,
        "ci_hi":   ci_hi,
    }


def main():
    # ── 1. Collect ramp variants ────────────────────────────────────────────
    cells = []

    # Normal burst (existing): cloudflare/burst/ and vercel/burst/
    for plat_dir, plat_label in [("cloudflare", "CF Workers"), ("vercel", "Vercel Edge")]:
        runs = collect_ramp_variant(plat_dir, "normal", "burst/*.json")
        for r in runs:
            r["platform_label"] = plat_label
        cells.append(("normal", plat_label, runs))

    # Slow burst: burst-slow/
    for plat_dir, plat_label in [("cloudflare", "CF Workers"), ("vercel", "Vercel Edge")]:
        runs = collect_ramp_variant(plat_dir, "slow", "burst-slow/*.json")
        for r in runs:
            r["platform_label"] = plat_label
        cells.append(("slow", plat_label, runs))

    # Fast burst: burst-fast/
    for plat_dir, plat_label in [("cloudflare", "CF Workers"), ("vercel", "Vercel Edge")]:
        runs = collect_ramp_variant(plat_dir, "fast", "burst-fast/*.json")
        for r in runs:
            r["platform_label"] = plat_label
        cells.append(("fast", plat_label, runs))

    # ── 2. Build aggregated table ───────────────────────────────────────────
    rows = []
    for ramp, plat_label, runs in cells:
        if not runs:
            print(f"  WARNING: no runs for {plat_label} / {ramp}")
            agg = {"n": 0, "avg_mean": None, "avg_std": None,
                   "p95_mean": None, "p95_std": None, "ci_lo": None, "ci_hi": None}
        else:
            agg = aggregate_runs(runs)
        rows.append({
            "ramp": ramp,
            "platform": plat_label,
            **agg,
        })

    # ── 3. Compute variance differential (CF std / Vercel std) per ramp ────
    summary = {}
    for ramp in ["normal", "slow", "fast"]:
        cf_row = next((r for r in rows if r["ramp"] == ramp and "CF" in r["platform"]), None)
        vc_row = next((r for r in rows if r["ramp"] == ramp and "Vercel" in r["platform"]), None)
        if cf_row and vc_row and cf_row["avg_std"] and vc_row["avg_std"]:
            ratio = cf_row["avg_std"] / vc_row["avg_std"] if vc_row["avg_std"] > 0 else float("inf")
        else:
            ratio = None
        summary[ramp] = {"cf": cf_row, "vc": vc_row, "variance_ratio": ratio}

    # ── 4. Write CSV ────────────────────────────────────────────────────────
    csv_path = os.path.join(OUT_DIR, "r1-ramp-sensitivity.csv")
    fieldnames = ["ramp", "platform", "n", "avg_mean", "avg_std", "p95_mean", "p95_std", "ci_lo", "ci_hi"]
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            w.writerow({k: (f"{row[k]:.3f}" if isinstance(row[k], float) else row[k])
                        for k in fieldnames})
    print(f"Wrote: {csv_path}")

    # ── 5. Write LaTeX table ────────────────────────────────────────────────
    tex_path = os.path.join(TABLES_DIR, "ramp-sensitivity.tex")
    _write_latex_table(rows, summary, tex_path)
    print(f"Wrote: {tex_path}")

    # ── 6. Generate figure ──────────────────────────────────────────────────
    fig_base = os.path.join(FIGS_DIR, "fig-ramp-sensitivity")
    _generate_figure(rows, summary, fig_base)
    print(f"Wrote: {fig_base}.pdf and .png")

    # ── 7. Print summary ────────────────────────────────────────────────────
    print("\n=== Ramp Sensitivity Summary ===")
    for ramp, info in summary.items():
        cf, vc = info["cf"], info["vc"]
        ratio = info["variance_ratio"]
        if cf and vc:
            print(f"  {ramp:6s}: CF avg={cf['avg_mean']:.1f}ms std={cf['avg_std']:.2f}ms | "
                  f"VC avg={vc['avg_mean']:.1f}ms std={vc['avg_std']:.2f}ms | "
                  f"variance_ratio(CF/VC)={ratio:.2f}" if ratio else f"  {ramp}: data missing")
        else:
            print(f"  {ramp}: missing data")


def _write_latex_table(rows, summary, tex_path):
    ramp_labels = {"normal": "Normal (90s)", "slow": "Slow (5min)", "fast": "Fast (15s)"}
    lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        r"\small",
        r"\caption{Ramp-rate sensitivity analysis: Cloudflare Workers vs.\ Vercel Edge Functions "
        r"across three ramp rates (local/VN client, mock mode, $n=3$ runs/cell). "
        r"Values in milliseconds. Variance differential = CF\,std / Vercel\,std; "
        r"ratio $>$1 means CF has wider avg spread across runs.}",
        r"\label{tab:ramp-sensitivity}",
        r"\begin{tabular}{llrrrr}",
        r"\toprule",
        r"Ramp Rate & Platform & $n$ & Avg (ms) & Std (ms) & P95 (ms) \\",
        r"\midrule",
    ]

    prev_ramp = None
    for row in rows:
        ramp = row["ramp"]
        rl = ramp_labels.get(ramp, ramp)
        plat = row["platform"]
        n    = row.get("n") or "—"
        avg  = f"{row['avg_mean']:.1f}" if row.get("avg_mean") is not None else "—"
        std  = f"{row['avg_std']:.2f}"  if row.get("avg_std")  is not None else "—"
        p95  = f"{row['p95_mean']:.1f}" if row.get("p95_mean") is not None else "—"
        ramp_col = rl if ramp != prev_ramp else ""
        prev_ramp = ramp
        lines.append(fr"{ramp_col} & {plat} & {n} & {avg} & {std} & {p95} \\")
        # add midline between ramp groups
        if ramp != prev_ramp:
            pass

    lines.append(r"\midrule")
    # variance differential summary
    lines.append(r"\multicolumn{6}{l}{\footnotesize Variance differential (CF\,std / Vercel\,std):} \\")
    for ramp, info in summary.items():
        rl = ramp_labels.get(ramp, ramp)
        ratio = info["variance_ratio"]
        ratio_str = f"{ratio:.2f}" if ratio is not None else "—"
        lines.append(fr"\multicolumn{{6}}{{l}}{{\quad {rl}: {ratio_str}}} \\")

    lines += [
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table}",
    ]
    with open(tex_path, "w") as f:
        f.write("\n".join(lines) + "\n")


def _generate_figure(rows, summary, fig_base):
    """
    Two-panel figure:
      Left: grouped bar chart of avg latency by ramp × platform
      Right: bar chart of std (variance) by ramp × platform
    """
    ramp_order  = ["normal", "slow", "fast"]
    ramp_labels = ["Normal\n(90s)", "Slow\n(5 min)", "Fast\n(15s)"]
    cf_color    = "#2196F3"
    vc_color    = "#FF5722"

    cf_avgs, vc_avgs = [], []
    cf_stds, vc_stds = [], []
    cf_p95s, vc_p95s = [], []

    for ramp in ramp_order:
        cf = next((r for r in rows if r["ramp"] == ramp and "CF" in r["platform"]), {})
        vc = next((r for r in rows if r["ramp"] == ramp and "Vercel" in r["platform"]), {})
        cf_avgs.append(cf.get("avg_mean") or 0.0)
        vc_avgs.append(vc.get("avg_mean") or 0.0)
        cf_stds.append(cf.get("avg_std") or 0.0)
        vc_stds.append(vc.get("avg_std") or 0.0)
        cf_p95s.append(cf.get("p95_mean") or 0.0)
        vc_p95s.append(vc.get("p95_mean") or 0.0)

    x = np.arange(len(ramp_order))
    w = 0.35

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4.5))

    # Panel 1: Average latency
    ax1.bar(x - w/2, cf_avgs, w, label="CF Workers",   color=cf_color, alpha=0.85)
    ax1.bar(x + w/2, vc_avgs, w, label="Vercel Edge",  color=vc_color, alpha=0.85)
    ax1.bar(x - w/2, cf_p95s, w, color=cf_color, alpha=0.35, hatch="//")
    ax1.bar(x + w/2, vc_p95s, w, color=vc_color, alpha=0.35, hatch="//")
    ax1.set_xticks(x); ax1.set_xticklabels(ramp_labels)
    ax1.set_ylabel("Latency (ms)")
    ax1.set_title("(a) Average Latency by Ramp Rate\n(solid=avg, hatch=p95)")
    ax1.legend(fontsize=8)
    ax1.grid(axis="y", alpha=0.3)

    # Panel 2: Standard deviation (variance differential)
    ax2.bar(x - w/2, cf_stds, w, label="CF Workers (std)",  color=cf_color, alpha=0.85)
    ax2.bar(x + w/2, vc_stds, w, label="Vercel Edge (std)", color=vc_color, alpha=0.85)
    ax2.set_xticks(x); ax2.set_xticklabels(ramp_labels)
    ax2.set_ylabel("Std Dev of Avg Latency (ms)")
    ax2.set_title("(b) Variance Differential by Ramp Rate\n(run-to-run std dev)")
    ax2.legend(fontsize=8)
    ax2.grid(axis="y", alpha=0.3)

    # Annotate variance ratios
    for i, ramp in enumerate(ramp_order):
        ratio = summary[ramp].get("variance_ratio")
        if ratio is not None:
            ax2.text(i, max(cf_stds[i], vc_stds[i]) + 0.05,
                     f"ratio\n{ratio:.2f}×",
                     ha="center", va="bottom", fontsize=7, color="black")

    plt.suptitle("Ramp-Rate Sensitivity: Burst Variance Differential Across Ramp Rates\n"
                 "(local/VN client, mock mode, n=3 runs/cell)",
                 fontsize=9, y=1.02)
    plt.tight_layout()
    plt.savefig(fig_base + ".pdf", bbox_inches="tight")
    plt.savefig(fig_base + ".png", dpi=150, bbox_inches="tight")
    plt.close()


if __name__ == "__main__":
    main()
