"""
Burst stage breakdown analyzer.

The k6 burst-test ramps VUs through stages:
  0→10→100→200→50→0 VUs over 30s+60s+30s+60s+30s = 3.5 min total

Since rawLatencies[] is empty in all result files, we derive per-stage
statistics from the available k6 aggregate metrics (avg, p50, p90, p95, p99,
max) combined across runs within each (client, platform) group.

The aggregate k6 output represents the WHOLE-RUN distribution. To get a
per-stage breakdown we use the p-values hierarchy to infer variance structure:
  - p95 vs p99 vs max gap indicates tail behavior (spike/peak stages)
  - avg vs median gap indicates skew (ramp-up stages)
  - We annotate each run's overall stats with the stage-implied properties.

For true per-stage breakdown a rawLatencies trace is needed; since that
data is absent, we produce the best-effort analysis from available statistics
and clearly annotate this limitation in output tables.

AGGREGATION LEVEL: n = runs per (client, platform) group, typically 3.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Any


# Burst test VU ramp schedule (seconds from test start)
# Derived from k6 burst-test.js: rampup 30s, spike 60s, peak200 30s, rampdown 60s, cooldown 30s
BURST_STAGES = [
    (0,   30,  "ramp_up",   "0→200 VU ramp-up"),
    (30,  90,  "spike",     "200 VU sustained spike"),
    (90,  120, "peak_hold", "200 VU peak hold"),
    (120, 180, "ramp_down", "200→0 VU ramp-down"),
    (180, 210, "cooldown",  "0 VU cooldown"),
]

# Thresholds for classifying tail severity from k6 aggregates
# These are heuristics based on p99/p95 ratios typical in burst tests
TAIL_SEVERITY_THRESHOLDS = {
    "mild":     (1.0, 1.5),   # p99/p95 ratio range
    "moderate": (1.5, 3.0),
    "severe":   (3.0, float("inf")),
}


def classify_tail_severity(p95: float, p99: float, max_val: float) -> str:
    """
    Classify tail severity from k6 percentile metrics.
    Uses p99/p95 ratio as proxy for spike-stage variance.
    """
    if p95 is None or p99 is None or p95 == 0:
        return "unknown"
    ratio = p99 / p95
    for label, (lo, hi) in TAIL_SEVERITY_THRESHOLDS.items():
        if lo <= ratio < hi:
            return label
    return "severe"


def classify_skew(avg: float, median: float) -> str:
    """
    Classify distribution skew from avg vs median gap.
    Positive skew (avg > median) indicates heavy right tail (spike stage effect).
    """
    if avg is None or median is None or median == 0:
        return "unknown"
    ratio = avg / median
    if ratio < 1.05:
        return "symmetric"
    elif ratio < 1.20:
        return "mildly_right_skewed"
    elif ratio < 1.50:
        return "right_skewed"
    else:
        return "heavily_right_skewed"


def compute_burst_aggregate_stats(grp: pd.DataFrame) -> Dict[str, Any]:
    """
    Compute whole-run aggregate stats for a burst test group (across n runs).

    AGGREGATION LEVEL: per-run aggregate metrics, n=number of runs in group.
    Returns dict of mean/std/min/max for key percentiles.
    """
    stats_out = {}
    for metric in ["avg", "p50", "p90", "p95", "p99", "max", "throughput"]:
        vals = grp[metric].dropna().values if metric in grp.columns else np.array([])
        if len(vals) == 0:
            stats_out[metric] = {"mean": None, "std": None, "min": None, "max": None, "n": 0}
        else:
            stats_out[metric] = {
                "mean": float(np.mean(vals)),
                "std": float(np.std(vals, ddof=1)) if len(vals) > 1 else 0.0,
                "min": float(np.min(vals)),
                "max": float(np.max(vals)),
                "n": len(vals),
            }
    return stats_out


def analyze_burst_per_group(df: pd.DataFrame) -> pd.DataFrame:
    """
    Analyze burst test data grouped by (client, platform, mode).

    For each group compute:
    - Whole-run aggregate statistics (mean/std of per-run metrics)
    - Tail severity classification (proxy for spike-stage behavior)
    - Distribution skew classification (proxy for ramp-stage contribution)
    - Inferred stage-impact annotations

    Returns DataFrame with one row per (client, platform, mode) group.
    """
    burst_df = df[df["scenario"] == "burst"].copy()
    if burst_df.empty:
        return pd.DataFrame()

    rows = []
    for (client, platform, mode), grp in burst_df.groupby(["client", "platform", "mode"]):
        agg = compute_burst_aggregate_stats(grp)
        n_runs = len(grp)

        # Tail severity from mean p95/p99/max
        p95_mean = agg["p95"]["mean"]
        p99_mean = agg["p99"]["mean"] if "p99" in agg else None
        max_mean = agg["max"]["mean"]
        avg_mean = agg["avg"]["mean"]
        p50_mean = agg["p50"]["mean"]

        tail_sev = classify_tail_severity(p95_mean, p99_mean, max_mean)
        skew_cls = classify_skew(avg_mean, p50_mean)

        # p99/p95 ratio (key reviewer metric)
        p99_p95_ratio = None
        if p95_mean and p99_mean and p95_mean > 0:
            p99_p95_ratio = p99_mean / p95_mean

        # avg/p50 ratio (skew indicator)
        avg_p50_ratio = None
        if p50_mean and avg_mean and p50_mean > 0:
            avg_p50_ratio = avg_mean / p50_mean

        # max/p95 ratio (extreme outlier indicator — spike stage proxy)
        max_p95_ratio = None
        if p95_mean and max_mean and p95_mean > 0:
            max_p95_ratio = max_mean / p95_mean

        rows.append({
            "client": client,
            "platform": platform,
            "mode": mode,
            "n_runs": n_runs,
            "avg_mean_ms": avg_mean,
            "avg_std_ms": agg["avg"]["std"],
            "p50_mean_ms": p50_mean,
            "p90_mean_ms": agg["p90"]["mean"],
            "p95_mean_ms": p95_mean,
            "p99_mean_ms": p99_mean,
            "max_mean_ms": max_mean,
            "throughput_mean_rps": agg["throughput"]["mean"],
            "p99_p95_ratio": p99_p95_ratio,
            "avg_p50_ratio": avg_p50_ratio,
            "max_p95_ratio": max_p95_ratio,
            "tail_severity": tail_sev,
            "skew_class": skew_cls,
            # Stage inference note
            "stage_note": (
                f"Tail severity: {tail_sev} (p99/p95={p99_p95_ratio:.2f}); "
                f"Skew: {skew_cls} (avg/p50={avg_p50_ratio:.2f})"
                if p99_p95_ratio and avg_p50_ratio
                else "Insufficient data for stage inference"
            ),
            "data_limitation": (
                "rawLatencies[] empty — per-stage breakdown estimated from "
                "whole-run aggregate percentiles only"
            ),
        })

    return pd.DataFrame(rows)


def compare_platforms_per_stage_proxy(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compare Cloudflare vs Vercel within each (client, mode) group
    using whole-run aggregate metrics as stage proxies.

    Returns DataFrame with CF vs Vercel comparison per group including:
    - avg, p95, p99, max comparisons
    - relative improvement percentages
    - tail severity comparison
    """
    burst_stats = analyze_burst_per_group(df)
    if burst_stats.empty:
        return pd.DataFrame()

    rows = []
    cf = burst_stats[burst_stats["platform"] == "cloudflare"].set_index(["client", "mode"])
    vc = burst_stats[burst_stats["platform"] == "vercel"].set_index(["client", "mode"])

    common_idx = cf.index.intersection(vc.index)
    for idx in common_idx:
        client, mode = idx
        cf_row = cf.loc[idx]
        vc_row = vc.loc[idx]

        def pct_diff(cf_val, vc_val):
            if cf_val and vc_val and vc_val != 0:
                return (vc_val - cf_val) / vc_val * 100.0
            return None

        rows.append({
            "client": client,
            "mode": mode,
            "n_runs_cf": cf_row["n_runs"],
            "n_runs_vercel": vc_row["n_runs"],
            # avg comparison
            "cf_avg_ms": cf_row["avg_mean_ms"],
            "vercel_avg_ms": vc_row["avg_mean_ms"],
            "avg_cf_improvement_pct": pct_diff(cf_row["avg_mean_ms"], vc_row["avg_mean_ms"]),
            # p95 comparison
            "cf_p95_ms": cf_row["p95_mean_ms"],
            "vercel_p95_ms": vc_row["p95_mean_ms"],
            "p95_cf_improvement_pct": pct_diff(cf_row["p95_mean_ms"], vc_row["p95_mean_ms"]),
            # p99 comparison
            "cf_p99_ms": cf_row["p99_mean_ms"],
            "vercel_p99_ms": vc_row["p99_mean_ms"],
            "p99_cf_improvement_pct": pct_diff(cf_row["p99_mean_ms"], vc_row["p99_mean_ms"]),
            # max comparison (spike-stage proxy)
            "cf_max_ms": cf_row["max_mean_ms"],
            "vercel_max_ms": vc_row["max_mean_ms"],
            "max_cf_improvement_pct": pct_diff(cf_row["max_mean_ms"], vc_row["max_mean_ms"]),
            # tail severity
            "cf_tail_severity": cf_row["tail_severity"],
            "vercel_tail_severity": vc_row["tail_severity"],
            "cf_p99_p95_ratio": cf_row["p99_p95_ratio"],
            "vercel_p99_p95_ratio": vc_row["p99_p95_ratio"],
            "data_limitation": cf_row["data_limitation"],
        })

    return pd.DataFrame(rows)


def get_stage_definitions_note() -> str:
    """Return documentation note on burst stages for paper footnote."""
    lines = [
        "Burst test VU schedule: "
        + " → ".join(f"{name}({lo}-{hi}s)" for lo, hi, name, _ in BURST_STAGES),
        "Per-stage latency breakdown unavailable (rawLatencies[]=empty in k6 output).",
        "Stage behavior inferred from whole-run p95/p99/max ratios and avg/median skew.",
        "p99/p95 ratio >1.5 indicates spike-stage heavy-tail contribution.",
        "avg/p50 ratio >1.2 indicates right-skewed distribution from ramp-up stage.",
    ]
    return " ".join(lines)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
    from ingest_r1_revision import ingest_revision_results  # type: ignore
    base = sys.argv[1] if len(sys.argv) > 1 else "benchmark/results/r1-revision"
    df = ingest_revision_results(base)
    burst_analysis = analyze_burst_per_group(df)
    print(burst_analysis.to_string())
    comparison = compare_platforms_per_stage_proxy(df)
    print("\nPlatform comparison:")
    print(comparison.to_string())
