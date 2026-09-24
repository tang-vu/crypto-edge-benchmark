"""
Cohen's d aggregation-level comparison module.

Addresses Reviewer 3 concern R3.2: "Cohen's d > 17 is unusual and suggests
an aggregation artifact."

ROOT CAUSE:
  The original analysis computes Cohen's d on n=runs per-run mean values
  (n=5-7). When each run averages 1000 requests, the variance of run-means
  is compressed by ~sqrt(1000) relative to the request-level variance.
  This inflates d dramatically: d_run >> d_request.

  Example intuition:
    Per-run means: CF=[39.9, 40.2, 40.1, 39.8, 40.3] ms (tiny variance, n=5)
                   VC=[96.2, 96.4, 96.0, 95.9, 96.3] ms (tiny variance, n=5)
    pooled_std ~ 0.2 ms → d ~ (96.2-40.0)/0.2 ~ 280   (extreme!)

    Per-request approx: both platforms have request-level std ~10-20ms
    pooled_std ~ 15 ms → d ~ (96.2-40.0)/15 ~ 3.7     (still large, honest)

APPROACH:
  Since rawLatencies[] is empty, we cannot directly sample per-request data.
  Instead we reconstruct a per-request pseudo-distribution for each run using
  the k6 summary statistics (avg, p50, p90, p95, p99, max) to fit a
  log-normal distribution, then draw synthetic samples from it.

  This is clearly labeled as "synthetic reconstruction" in all outputs.
  The reconstruction gives an ESTIMATE of d at request-level, sufficient
  to demonstrate the aggregation artifact to the reviewer.

  For absolute honesty: we report both, label both, and note the limitation.

AGGREGATION LEVELS PRODUCED:
  1. d_run_level:     Cohen's d on per-run avg values (n=runs, existing method)
  2. d_request_synth: Cohen's d on synthetic per-request samples (n~1000/run)
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
from scipy import stats as scipy_stats


def cohens_d(g1: np.ndarray, g2: np.ndarray) -> float:
    """
    Cohen's d using pooled standard deviation (same formula as statistical_analysis.py).
    Positive value means g2 > g1.
    """
    g1 = np.asarray(g1, dtype=float)
    g2 = np.asarray(g2, dtype=float)
    n1, n2 = len(g1), len(g2)
    if n1 < 2 or n2 < 2:
        return float("nan")
    var1 = np.var(g1, ddof=1)
    var2 = np.var(g2, ddof=1)
    pooled_std = np.sqrt(((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2))
    if pooled_std == 0:
        return 0.0
    return float((np.mean(g2) - np.mean(g1)) / pooled_std)


def interpret_cohens_d(d: float) -> str:
    """Map |d| to verbal label."""
    if np.isnan(d):
        return "N/A"
    abs_d = abs(d)
    if abs_d < 0.2:
        return "negligible"
    elif abs_d < 0.5:
        return "small"
    elif abs_d < 0.8:
        return "medium"
    else:
        return "large"


def fit_lognormal_from_percentiles(
    avg: float, p50: float, p90: float, p95: float
) -> Tuple[float, float]:
    """
    Fit log-normal parameters (mu, sigma) from summary percentiles.

    Strategy: use p50 (median) and p90 to fit the two log-normal parameters.
    ln(p50) = mu  (since median of log-normal = exp(mu))
    p90 = exp(mu + sigma * 1.282)  (z-score for 90th percentile)

    Falls back to avg-based estimate if p50/p90 unavailable.

    Returns: (mu, sigma) for scipy.stats.lognorm parameterization
             where loc=0, scale=exp(mu), s=sigma.
    """
    if p50 and p50 > 0 and p90 and p90 > p50:
        mu = np.log(p50)
        sigma = (np.log(p90) - mu) / 1.2816  # z(0.90)
        sigma = max(sigma, 0.01)  # clamp for numerical stability
    elif avg and avg > 0:
        # Rough: assume sigma~0.3 (typical for API latency), derive mu from mean
        sigma = 0.3
        mu = np.log(avg) - (sigma ** 2) / 2.0
    else:
        return float("nan"), float("nan")

    return float(mu), float(sigma)


def synthesize_request_samples(
    avg: Optional[float],
    p50: Optional[float],
    p90: Optional[float],
    p95: Optional[float],
    n_requests: int = 1000,
    seed: int = 42,
) -> np.ndarray:
    """
    Synthesize per-request latency samples from k6 summary percentiles
    using log-normal distribution fit.

    Returns array of n_requests synthetic latency values (ms).
    Clearly a reconstruction — not actual raw trace data.
    """
    mu, sigma = fit_lognormal_from_percentiles(avg, p50, p90, p95)
    if np.isnan(mu):
        return np.array([avg] * n_requests) if avg else np.array([])

    rng = np.random.default_rng(seed)
    samples = rng.lognormal(mean=mu, sigma=sigma, size=n_requests)

    # Soft-clamp: if p95 known, cap 99th percentile of samples at ~3*p95
    # to prevent unrealistic tails from the fit
    if p95 and p95 > 0:
        cap = p95 * 3.0
        samples = np.clip(samples, 0, cap)

    return samples


def compute_aggregation_comparison(
    run_level_cf: np.ndarray,
    run_level_vercel: np.ndarray,
    cf_run_metrics: List[Dict],
    vercel_run_metrics: List[Dict],
    scenario: str,
    group_label: str = "",
) -> Dict:
    """
    Compute Cohen's d at both run-level and synthetic request-level.

    Args:
        run_level_cf: Per-run avg latency values for Cloudflare (n=runs).
        run_level_vercel: Per-run avg latency values for Vercel (n=runs).
        cf_run_metrics: List of metric dicts (avg, p50, p90, p95) per CF run.
        vercel_run_metrics: List of metric dicts per Vercel run.
        scenario: Scenario name for labeling.
        group_label: Optional group label (client/mode).

    Returns:
        Dict with d_run_level, d_request_synth, inflation_factor, and metadata.
    """
    run_level_cf = np.asarray(run_level_cf, dtype=float)
    run_level_vercel = np.asarray(run_level_vercel, dtype=float)

    # 1. Run-level Cohen's d (existing method — what reviewer flagged)
    d_run = cohens_d(run_level_cf, run_level_vercel)

    # 2. Synthetic per-request samples — concatenate across all runs in group
    all_cf_samples = []
    for i, m in enumerate(cf_run_metrics):
        seed_i = 42 + i
        samp = synthesize_request_samples(
            m.get("avg"), m.get("p50"), m.get("p90"), m.get("p95"),
            n_requests=1000, seed=seed_i,
        )
        all_cf_samples.append(samp)

    all_vercel_samples = []
    for i, m in enumerate(vercel_run_metrics):
        seed_i = 100 + i
        samp = synthesize_request_samples(
            m.get("avg"), m.get("p50"), m.get("p90"), m.get("p95"),
            n_requests=1000, seed=seed_i,
        )
        all_vercel_samples.append(samp)

    if all_cf_samples and all_vercel_samples:
        cf_request = np.concatenate(all_cf_samples)
        vercel_request = np.concatenate(all_vercel_samples)
        d_request = cohens_d(cf_request, vercel_request)
        n_req_cf = len(cf_request)
        n_req_vercel = len(vercel_request)
    else:
        d_request = float("nan")
        n_req_cf = 0
        n_req_vercel = 0

    # Inflation factor: how much run-level overstates effect vs request-level
    inflation = abs(d_run) / abs(d_request) if not np.isnan(d_request) and d_request != 0 else float("nan")

    return {
        "scenario": scenario,
        "group": group_label,
        "n_runs_cf": len(run_level_cf),
        "n_runs_vercel": len(run_level_vercel),
        "n_requests_cf_synth": n_req_cf,
        "n_requests_vercel_synth": n_req_vercel,
        "cf_mean_run": float(np.mean(run_level_cf)) if len(run_level_cf) else None,
        "vercel_mean_run": float(np.mean(run_level_vercel)) if len(run_level_vercel) else None,
        "d_run_level": float(d_run),
        "d_run_level_interp": interpret_cohens_d(d_run),
        "d_request_synth": float(d_request),
        "d_request_synth_interp": interpret_cohens_d(d_request),
        "inflation_factor": float(inflation),
        "artifact_confirmed": (
            bool(not np.isnan(inflation) and inflation > 2.0)
        ),
        "synth_note": (
            "d_request_synth uses log-normal reconstruction from k6 summary "
            "percentiles (rawLatencies[]=empty). Demonstrates aggregation "
            "artifact; not a substitute for raw trace analysis."
        ),
    }


def build_aggregation_comparison_table(df: pd.DataFrame) -> pd.DataFrame:
    """
    Build full aggregation comparison table from r1-revision DataFrame.

    Groups by (scenario, client, mode) and computes run-level vs
    synthetic request-level Cohen's d for CF vs Vercel.

    Returns DataFrame suitable for CSV export and LaTeX rendering.
    """
    rows = []

    for (scenario, client, mode), grp in df.groupby(["scenario", "client", "mode"]):
        cf_grp = grp[grp["platform"] == "cloudflare"].sort_values("run_num")
        vc_grp = grp[grp["platform"] == "vercel"].sort_values("run_num")

        if len(cf_grp) < 2 or len(vc_grp) < 2:
            continue

        cf_avgs = cf_grp["avg"].dropna().values
        vc_avgs = vc_grp["avg"].dropna().values

        cf_metrics = cf_grp[["avg", "p50", "p90", "p95"]].to_dict("records")
        vc_metrics = vc_grp[["avg", "p50", "p90", "p95"]].to_dict("records")

        result = compute_aggregation_comparison(
            cf_avgs, vc_avgs, cf_metrics, vc_metrics,
            scenario=scenario,
            group_label=f"{client}/{mode}",
        )
        rows.append(result)

    return pd.DataFrame(rows)


def build_jan2026_comparison(results: Dict) -> pd.DataFrame:
    """
    Build aggregation comparison for Jan 2026 baseline data.

    Args:
        results: Output of load_benchmark_results() from statistical_analysis.py
                 Format: {scenario: {platform: [run_data, ...]}}

    Returns DataFrame with run-level vs synthetic request-level Cohen's d.
    """
    from benchmark.analysis.statistical_analysis import extract_latency_metrics  # type: ignore

    rows = []
    for scenario in ["warm-performance", "load-test", "burst-test"]:
        cf_data = results.get(scenario, {}).get("cloudflare", [])
        vc_data = results.get(scenario, {}).get("vercel", [])

        if len(cf_data) < 2 or len(vc_data) < 2:
            continue

        cf_metrics_list = [extract_latency_metrics(d) for d in cf_data]
        vc_metrics_list = [extract_latency_metrics(d) for d in vc_data]

        cf_avgs = np.array([m.get("avg") for m in cf_metrics_list if m.get("avg") is not None])
        vc_avgs = np.array([m.get("avg") for m in vc_metrics_list if m.get("avg") is not None])

        result = compute_aggregation_comparison(
            cf_avgs, vc_avgs,
            cf_metrics_list, vc_metrics_list,
            scenario=scenario,
            group_label="jan2026-baseline",
        )
        rows.append(result)

    return pd.DataFrame(rows)


if __name__ == "__main__":
    # Smoke test: verify inflation artifact is reproduced
    rng = np.random.default_rng(42)

    # Simulate 5 CF runs: each is mean of 1000 requests from N(40, 10)
    n_requests = 1000
    cf_run_means = np.array([np.mean(rng.normal(40, 10, n_requests)) for _ in range(5)])
    vc_run_means = np.array([np.mean(rng.normal(90, 10, n_requests)) for _ in range(5)])

    d_run = cohens_d(cf_run_means, vc_run_means)
    print(f"d at run level (n=5 run means): {d_run:.2f}")

    # Per-request: draw all 5000 samples
    cf_all = rng.normal(40, 10, n_requests * 5)
    vc_all = rng.normal(90, 10, n_requests * 5)
    d_req = cohens_d(cf_all, vc_all)
    print(f"d at request level (n=5000 requests): {d_req:.2f}")
    print(f"Inflation factor: {abs(d_run) / abs(d_req):.1f}x")
    assert abs(d_run) > abs(d_req) * 3, "Expected significant inflation at run level"
    print("cohens-d-aggregation-comparison.py smoke test passed.")
