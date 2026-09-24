"""
8.7 TRUE per-request statistical reanalysis.

Replaces synthetic d_request_synth (log-normal reconstruction) with ACTUAL
per-request Cohen's d computed from k6 --out csv= trace files.

Outputs:
  benchmark/analysis/output/r1-revision-stats.csv        (updated: adds d_request_true)
  benchmark/analysis/output/r1-aggregation-comparison.csv (updated: adds true d column)
  benchmark/analysis/output/r1-burst-per-stage-true.csv  (NEW: per-stage from CSV)
  benchmark/analysis/output/r1-tables/burst-per-stage-true.tex (NEW LaTeX)
  benchmark/analysis/output/r1-tables/cold.tex           (updated: n=3/cell)

Usage:
    python true-request-stats-reanalysis.py \\
        --revision-dir benchmark/results/r1-revision \\
        --output-dir   benchmark/analysis/output

AGGREGATION NOTE:
  All d_request_true values use n = actual per-request samples from CSV
  (typically 30k-50k per platform group). This is the R3.2 fix.
"""

import argparse
import importlib.util
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

# ---------------------------------------------------------------------------
# Local module loader (supports kebab-case filenames)
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


_csv_mod     = _load_local("ingest-csv-traces.py")
_ingest_mod  = _load_local("ingest-r1-revision.py")
_boot_mod    = _load_local("bootstrap.py")
_np_mod      = _load_local("nonparametric-stats.py")
_emit_mod    = _load_local("paper-table-emitter.py")

ingest_csv_traces  = _csv_mod.ingest_csv_traces
cohens_d_true      = _csv_mod.cohens_d_true
interpret_d        = _csv_mod.interpret_d
ingest_revision_results = _ingest_mod.ingest_revision_results
bootstrap_ci       = _boot_mod.bootstrap_ci
mann_whitney_u     = _np_mod.mann_whitney_u

BURST_STAGES       = _csv_mod.BURST_STAGES  # list of (start, end, label, desc)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BOOTSTRAP_N       = 10_000
# For per-request arrays (n >> 10k) we sub-sample before bootstrapping to
# avoid OOM. With n_subsample=5000 the CI is still very tight (CLT kicks in
# hard at these sample sizes). We use the sub-sample ONLY for CI, not for
# computing the actual mean/d which uses all data.
BOOTSTRAP_SUBSAMPLE = 5_000
STAGE_ORDER  = ["ramp_up", "spike", "peak_hold", "ramp_down", "cooldown"]
STAGE_LABELS = {
    "ramp_up":   "Ramp-up (0-30s)",
    "spike":     "Spike (30-90s)",
    "peak_hold": "Peak (90-120s)",
    "ramp_down": "Ramp-down (120-180s)",
    "cooldown":  "Cooldown (180-210s)",
}


# ---------------------------------------------------------------------------
# 8.7-A  Per-cell TRUE d_request from burst CSVs
# ---------------------------------------------------------------------------

def _bootstrap_ci_large(
    arr: np.ndarray,
    n_sub: int = BOOTSTRAP_SUBSAMPLE,
    n_resamples: int = BOOTSTRAP_N,
    seed: int = 42,
) -> Tuple[float, float]:
    """
    Memory-safe bootstrap CI for large arrays (n >> 10k).
    Sub-samples n_sub rows before bootstrapping. With n_sub=5000 the
    confidence interval is essentially indistinguishable from the full-data
    CI (standard error of the mean ∝ 1/sqrt(n), already negligible at 5000).
    Returns (ci_lower, ci_upper).
    """
    rng = np.random.default_rng(seed)
    if len(arr) > n_sub:
        arr = rng.choice(arr, size=n_sub, replace=False)
    _, lo, hi = bootstrap_ci(arr, n_resamples=n_resamples, seed=seed)
    return lo, hi


def compute_true_d_per_cell(
    trace_df: pd.DataFrame,
    scenario: str = "burst",
) -> pd.DataFrame:
    """
    For each (client, mode) cell, compute:
      - CF and Vercel per-request latency arrays (all runs concatenated)
      - TRUE Cohen's d (per-request, uses ALL samples)
      - Mann-Whitney U p-value (on sub-sample — exact MWU on 400k rows is slow)
      - Bootstrap 95% CI of mean for each platform (sub-sampled for memory safety)

    Returns DataFrame with one row per (client, mode) cell.
    """
    sub = trace_df[trace_df["scenario"] == scenario].copy()
    if sub.empty:
        return pd.DataFrame()

    cells = sub.groupby(["client", "mode"])
    rows = []
    rng = np.random.default_rng(42)

    for (client, mode), grp in cells:
        cf  = grp[grp["platform"] == "cloudflare"]["latency_ms"].values
        vc  = grp[grp["platform"] == "vercel"]["latency_ms"].values

        if len(cf) < 10 or len(vc) < 10:
            continue

        # TRUE Cohen's d on full per-request arrays
        d_true = cohens_d_true(cf, vc)

        # Memory-safe bootstrap CI (sub-sampled)
        cf_lo, cf_hi = _bootstrap_ci_large(cf, seed=42)
        vc_lo, vc_hi = _bootstrap_ci_large(vc, seed=43)

        # Mann-Whitney U on sub-sample of max 10k per group (exact test is O(n²))
        mw_n = min(10_000, len(cf), len(vc))
        cf_mw = rng.choice(cf, size=mw_n, replace=False)
        vc_mw = rng.choice(vc, size=mw_n, replace=False)
        mw = mann_whitney_u(cf_mw, vc_mw)

        rows.append({
            "scenario":              scenario,
            "client":                client,
            "mode":                  mode,
            "n_requests_cf":         len(cf),
            "n_requests_vercel":     len(vc),
            "cf_mean_ms":            float(np.mean(cf)),
            "cf_p95_ms":             float(np.percentile(cf, 95)),
            "cf_ci95_low":           float(cf_lo),
            "cf_ci95_high":          float(cf_hi),
            "vercel_mean_ms":        float(np.mean(vc)),
            "vercel_p95_ms":         float(np.percentile(vc, 95)),
            "vercel_ci95_low":       float(vc_lo),
            "vercel_ci95_high":      float(vc_hi),
            "d_request_true":        round(d_true, 4),
            "d_request_true_interp": interpret_d(d_true),
            "mw_p_value":            mw.get("p_value"),
            "mw_significant":        mw.get("significant"),
            "mw_effect_r":           mw.get("effect_r"),
        })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 8.7-B  Per-stage burst breakdown from CSV
# ---------------------------------------------------------------------------

def compute_per_stage_stats(trace_df: pd.DataFrame) -> pd.DataFrame:
    """
    For each burst stage × (client, platform, mode) combination, compute
    mean, p95, std from the true per-request latency samples.

    Returns DataFrame with per-stage stats suitable for the LaTeX table.
    """
    sub = trace_df[trace_df["scenario"] == "burst"].copy()
    if sub.empty:
        return pd.DataFrame()

    rows = []
    grouped = sub.groupby(["client", "platform", "mode", "stage"])

    for (client, platform, mode, stage), grp in grouped:
        lat = grp["latency_ms"].values
        if len(lat) < 2:
            continue

        rows.append({
            "client":        client,
            "platform":      platform,
            "mode":          mode,
            "stage":         stage,
            "n_requests":    len(lat),
            "mean_ms":       round(float(np.mean(lat)), 3),
            "p50_ms":        round(float(np.percentile(lat, 50)), 3),
            "p95_ms":        round(float(np.percentile(lat, 95)), 3),
            "p99_ms":        round(float(np.percentile(lat, 99)), 3),
            "std_ms":        round(float(np.std(lat, ddof=1)), 3),
            "max_ms":        round(float(np.max(lat)), 3),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # Sort by meaningful order
    stage_order_map = {s: i for i, (_, _, s, _) in enumerate(BURST_STAGES)}
    df["_stage_idx"] = df["stage"].map(stage_order_map).fillna(99)
    df = df.sort_values(["client", "platform", "mode", "_stage_idx"]).drop(
        columns=["_stage_idx"]
    )
    return df


def identify_variance_driver(stage_df: pd.DataFrame) -> Dict[str, str]:
    """
    For each (platform, mode), identify which stage has highest p95.
    Returns dict: key = 'platform/mode', value = stage label.
    """
    if stage_df.empty:
        return {}
    result = {}
    for (platform, mode), grp in stage_df.groupby(["platform", "mode"]):
        if grp.empty:
            continue
        max_row = grp.loc[grp["p95_ms"].idxmax()]
        result[f"{platform}/{mode}"] = max_row["stage"]
    return result


# ---------------------------------------------------------------------------
# 8.7-C  Update r1-aggregation-comparison.csv with true d column
# ---------------------------------------------------------------------------

def update_aggregation_comparison(
    agg_csv_path: Path,
    true_d_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Load existing r1-aggregation-comparison.csv, merge in d_request_true
    column, write updated file.
    """
    if not agg_csv_path.exists():
        print(f"[update-agg] WARNING: {agg_csv_path} not found, skipping")
        return pd.DataFrame()

    agg = pd.read_csv(agg_csv_path)

    # Build lookup from true_d_df: key = (client, mode) for burst rows
    burst_true = true_d_df[true_d_df["scenario"] == "burst"].copy()
    lookup: Dict[Tuple, float] = {}
    for _, row in burst_true.iterrows():
        key = (row["client"], row["mode"])
        lookup[key] = (row["d_request_true"], row["d_request_true_interp"])

    # Match agg rows of scenario=burst
    def _get_d_true(row):
        # group column format: "burst,client/mode" or "burst,client"
        g = str(row.get("group", ""))
        sc = str(row.get("scenario", ""))
        if sc != "burst":
            return (np.nan, "")
        # Try to parse client/mode from group: e.g. "ap-southeast-1/live"
        parts = g.split("/")
        if len(parts) == 2:
            client, mode = parts[0], parts[1]
        else:
            return (np.nan, "")
        return lookup.get((client, mode), (np.nan, ""))

    agg[["d_request_true", "d_request_true_interp"]] = agg.apply(
        lambda r: pd.Series(_get_d_true(r)), axis=1
    )

    return agg


# ---------------------------------------------------------------------------
# 8.7-D  Cold-start n=3 re-aggregation
# ---------------------------------------------------------------------------

def recompute_cold_stats(revision_df: pd.DataFrame) -> pd.DataFrame:
    """
    Re-aggregate cold-start runs at n=3 per cell using the ingested JSON stats.
    Returns tidy DataFrame for LaTeX cold table generation.
    """
    cold = revision_df[revision_df["scenario"] == "cold"].copy()
    if cold.empty:
        return pd.DataFrame()

    rows = []
    for (client, platform, mode), grp in cold.groupby(["client", "platform", "mode"]):
        avgs = grp["avg"].dropna().values
        p95s = grp["p95"].dropna().values
        n    = len(avgs)

        if n == 0:
            continue

        avg_mean = float(np.mean(avgs))
        p95_mean = float(np.mean(p95s)) if len(p95s) > 0 else np.nan

        if n >= 2:
            ci = bootstrap_ci(avgs, n_resamples=min(BOOTSTRAP_N, 1000))
        else:
            ci = (avg_mean, avg_mean)

        rows.append({
            "client":       client,
            "platform":     platform,
            "mode":         mode,
            "n_runs":       n,
            "avg_mean_ms":  round(avg_mean, 3),
            "ci95_low_ms":  round(float(ci[0]), 3),
            "ci95_high_ms": round(float(ci[1]), 3),
            "p95_mean_ms":  round(p95_mean, 3),
        })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# LaTeX emitters
# ---------------------------------------------------------------------------

def _fmt_ms(v, decimals=1) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return r"\textit{N/A}"
    return f"{v:.{decimals}f}"


def _fmt_p(p) -> str:
    if p is None or (isinstance(p, float) and np.isnan(p)):
        return "N/A"
    if p < 0.001:
        return r"$<$0.001"
    return f"{p:.3f}"


def emit_burst_per_stage_true_tex(
    stage_df: pd.DataFrame,
    output_path: Path,
    variance_drivers: Dict[str, str],
) -> None:
    """
    Emit LaTeX table for per-stage burst breakdown (TRUE from CSV traces).
    Shows mean ± std and p95 per stage for CF vs Vercel.
    Focuses on mock mode, aggregated across clients.
    """
    # Aggregate across clients for a compact global table; drop setup/teardown rows
    sub = stage_df[
        (stage_df["mode"] == "mock") &
        (stage_df["stage"] != "other")
    ].copy()
    if sub.empty:
        sub = stage_df[stage_df["stage"] != "other"].copy()

    agg = sub.groupby(["platform", "stage"]).agg(
        mean_ms=("mean_ms", "mean"),
        std_ms=("std_ms", "mean"),
        p95_ms=("p95_ms", "mean"),
        p99_ms=("p99_ms", "mean"),
        n_requests=("n_requests", "sum"),
    ).reset_index()

    stage_order_map = {s: i for i, (_, _, s, _) in enumerate(BURST_STAGES)}
    agg["_ord"] = agg["stage"].map(stage_order_map).fillna(99)
    agg = agg.sort_values(["_ord", "platform"]).drop(columns=["_ord"])

    lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        r"\caption{Per-stage burst latency breakdown (TRUE per-request, mock mode, "
        r"aggregated across all client regions). "
        r"Source: k6 \texttt{--out csv} per-request traces, n\,$\approx$\,14{,}000--19{,}000 "
        r"requests per run $\times$ 3 runs $\times$ 4 regions. "
        r"\textbf{Bold} = highest-p95 stage per platform (variance driver).}",
        r"\label{tab:burst-per-stage-true}",
        r"\begin{tabular}{llrrrrr}",
        r"\toprule",
        r"Stage & Platform & $n$ & Mean (ms) & Std (ms) & p95 (ms) & p99 (ms) \\",
        r"\midrule",
    ]

    prev_stage = None
    for _, row in agg.iterrows():
        stage   = row["stage"]
        plat    = row["platform"].capitalize()
        n       = int(row["n_requests"])
        mean_ms = _fmt_ms(row["mean_ms"])
        std_ms  = _fmt_ms(row["std_ms"])
        p95_ms  = _fmt_ms(row["p95_ms"])
        p99_ms  = _fmt_ms(row["p99_ms"])

        # Midrule between stages
        if prev_stage is not None and stage != prev_stage:
            lines.append(r"\midrule")
        prev_stage = stage

        stage_lbl = STAGE_LABELS.get(stage, stage)

        # Bold the stage label if it's the max-p95 stage for this platform
        is_driver = variance_drivers.get(
            f"{row['platform']}/mock", ""
        ) == stage
        p95_cell = rf"\textbf{{{p95_ms}}}" if is_driver else p95_ms

        lines.append(
            rf"{stage_lbl} & {plat} & {n:,} & {mean_ms} & {std_ms} "
            rf"& {p95_cell} & {p99_ms} \\"
        )

    lines += [
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table}",
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[tex] Written {output_path}")


def emit_cold_start_tex_n3(
    cold_df: pd.DataFrame,
    output_path: Path,
) -> None:
    """
    Emit updated cold-start LaTeX table at n=3 per cell.
    """
    lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        r"\caption{Cold-start latency by region and platform (n\,=\,3 runs per cell, "
        r"bootstrap 95\,\% CI). "
        r"Lower is better. Binance geo-block prevents us-east-1 live measurements.}",
        r"\label{tab:cold-start-n3}",
        r"\begin{tabular}{llllrr}",
        r"\toprule",
        r"Region & Platform & Mode & $n$ & Mean (ms) & 95\,\% CI (ms) \\",
        r"\midrule",
    ]

    prev_client = None
    for _, row in cold_df.sort_values(["client", "platform", "mode"]).iterrows():
        if prev_client is not None and row["client"] != prev_client:
            lines.append(r"\midrule")
        prev_client = row["client"]

        client   = row["client"]
        platform = row["platform"].capitalize()
        mode     = row["mode"]
        n        = int(row["n_runs"])
        avg      = _fmt_ms(row["avg_mean_ms"])
        ci_lo    = _fmt_ms(row["ci95_low_ms"])
        ci_hi    = _fmt_ms(row["ci95_high_ms"])
        ci_str   = f"[{ci_lo},\\ {ci_hi}]"

        lines.append(rf"{client} & {platform} & {mode} & {n} & {avg} & {ci_str} \\")

    lines += [
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table}",
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[tex] Written {output_path}")


def emit_updated_aggregation_tex(
    agg_df: pd.DataFrame,
    output_path: Path,
) -> None:
    """
    Emit updated aggregation-comparison LaTeX table showing
    d_run_level vs d_request_synth vs d_request_true.
    """
    lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        r"\caption{Cohen's d at three aggregation levels for burst scenario "
        r"(CF vs.\ Vercel, positive = Vercel slower). "
        r"\textit{d\textsubscript{run}} inflated by run-mean compression. "
        r"\textit{d\textsubscript{synth}} = log-normal reconstruction (Phase~4 artifact). "
        r"\textit{d\textsubscript{true}} = actual per-request samples from k6 CSV traces (R1 revision).}",
        r"\label{tab:aggregation-d-comparison}",
        r"\begin{tabular}{lllrrr}",
        r"\toprule",
        r"Group & $n_\mathrm{CF}$ & $n_\mathrm{VC}$ "
        r"& $d_\mathrm{run}$ & $d_\mathrm{synth}$ & $d_\mathrm{true}$ \\",
        r"\midrule",
    ]

    burst_rows = agg_df[agg_df["scenario"] == "burst"] if "scenario" in agg_df.columns \
        else agg_df[agg_df["group"].str.startswith("burst")]

    for _, row in burst_rows.iterrows():
        group   = row.get("group", "")
        n_cf    = int(row.get("n_runs_cf", 0))
        n_vc    = int(row.get("n_runs_vercel", 0))
        d_run   = row.get("d_run_level", np.nan)
        d_synth = row.get("d_request_synth", np.nan)
        d_true  = row.get("d_request_true", np.nan)

        def _fd(v):
            if isinstance(v, float) and np.isnan(v):
                return r"\textit{N/A}"
            return f"{v:.2f}"

        lines.append(
            rf"{group} & {n_cf} & {n_vc} & {_fd(d_run)} & {_fd(d_synth)} & {_fd(d_true)} \\"
        )

    lines += [
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table}",
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[tex] Written {output_path}")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="8.7 TRUE per-request stats reanalysis")
    parser.add_argument("--revision-dir", default="benchmark/results/r1-revision",
                        help="Root of r1-revision results")
    parser.add_argument("--output-dir",   default="benchmark/analysis/output",
                        help="Output directory for CSVs and LaTeX")
    args = parser.parse_args()

    rev_dir = Path(args.revision_dir)
    out_dir = Path(args.output_dir)
    tables_dir = out_dir / "r1-tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("8.7  TRUE per-request statistical reanalysis")
    print("=" * 60)

    # -----------------------------------------------------------------------
    # Step 1: Ingest CSV traces (burst only — large; cold has fewer rows)
    # -----------------------------------------------------------------------
    print("\n[1/5] Ingesting burst CSV traces …")
    burst_traces = ingest_csv_traces(str(rev_dir), scenario_filter="burst")
    print(f"      Burst rows loaded: {len(burst_traces):,}")
    if not burst_traces.empty:
        print(f"      Platforms: {burst_traces['platform'].unique()}")
        print(f"      Clients:   {burst_traces['client'].unique()}")
        print(f"      Stages:    {burst_traces['stage'].unique()}")

    # -----------------------------------------------------------------------
    # Step 2: Compute TRUE Cohen's d per (client, mode) cell
    # -----------------------------------------------------------------------
    print("\n[2/5] Computing TRUE Cohen's d per burst cell …")
    true_d_df = compute_true_d_per_cell(burst_traces, scenario="burst")
    if not true_d_df.empty:
        for _, row in true_d_df.iterrows():
            print(f"      {row['client']:20s} {row['mode']:4s} | "
                  f"CF={row['cf_mean_ms']:6.1f}ms  VC={row['vercel_mean_ms']:6.1f}ms | "
                  f"d_true={row['d_request_true']:+.3f} ({row['d_request_true_interp']}) | "
                  f"n_CF={row['n_requests_cf']:,}")
        true_d_path = out_dir / "r1-revision-stats-true-d.csv"
        true_d_df.to_csv(true_d_path, index=False)
        print(f"      Saved: {true_d_path}")

    # -----------------------------------------------------------------------
    # Step 3: Per-stage burst breakdown
    # -----------------------------------------------------------------------
    print("\n[3/5] Computing per-stage burst stats …")
    stage_df = compute_per_stage_stats(burst_traces)
    if not stage_df.empty:
        stage_path = out_dir / "r1-burst-per-stage-true.csv"
        stage_df.to_csv(stage_path, index=False)
        print(f"      Saved: {stage_path}")
        print("      Per-stage p95 summary (mock, CF vs Vercel, mean across regions):")
        mock_agg = stage_df[stage_df["mode"] == "mock"].groupby(
            ["platform", "stage"]
        )["p95_ms"].mean()
        print(mock_agg.to_string())

    variance_drivers = identify_variance_driver(stage_df)
    print(f"      Variance drivers: {variance_drivers}")

    # Emit LaTeX
    stage_tex_path = tables_dir / "burst-per-stage-true.tex"
    emit_burst_per_stage_true_tex(stage_df, stage_tex_path, variance_drivers)

    # -----------------------------------------------------------------------
    # Step 4: Update r1-aggregation-comparison.csv with true d column
    # -----------------------------------------------------------------------
    print("\n[4/5] Updating r1-aggregation-comparison.csv with d_request_true …")
    agg_csv_path = out_dir / "r1-aggregation-comparison.csv"
    updated_agg = update_aggregation_comparison(agg_csv_path, true_d_df)
    if not updated_agg.empty:
        updated_agg.to_csv(agg_csv_path, index=False)
        print(f"      Updated: {agg_csv_path}")
        agg_tex_path = tables_dir / "aggregation.tex"
        emit_updated_aggregation_tex(updated_agg, agg_tex_path)

    # -----------------------------------------------------------------------
    # Step 5: Cold-start n=3 re-aggregation from JSON stats
    # -----------------------------------------------------------------------
    print("\n[5/5] Re-aggregating cold-start at n=3 from JSON …")
    revision_df = ingest_revision_results(str(rev_dir))
    cold_df = recompute_cold_stats(revision_df)
    if not cold_df.empty:
        cold_path = out_dir / "r1-cold-stats-n3.csv"
        cold_df.to_csv(cold_path, index=False)
        print(f"      Saved: {cold_path}")
        cold_tex_path = tables_dir / "cold.tex"
        emit_cold_start_tex_n3(cold_df, cold_tex_path)

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    if not true_d_df.empty:
        d_vals = true_d_df["d_request_true"].dropna()
        print(f"  d_request_true range: {d_vals.min():.3f} … {d_vals.max():.3f}")
        print(f"  d_request_true mean:  {d_vals.mean():.3f}")
        print(f"  (Phase 4 d_synth reference: ~5.7 for warm, ~3.5-6.5 for burst)")

    if not stage_df.empty:
        mock_cf  = stage_df[(stage_df["mode"]=="mock") & (stage_df["platform"]=="cloudflare")]
        mock_vc  = stage_df[(stage_df["mode"]=="mock") & (stage_df["platform"]=="vercel")]
        if not mock_cf.empty:
            peak_cf  = mock_cf.groupby("stage")["p95_ms"].mean().idxmax()
            print(f"  Variance driver (CF  mock): {peak_cf}")
        if not mock_vc.empty:
            peak_vc  = mock_vc.groupby("stage")["p95_ms"].mean().idxmax()
            print(f"  Variance driver (VC  mock): {peak_vc}")


if __name__ == "__main__":
    main()
