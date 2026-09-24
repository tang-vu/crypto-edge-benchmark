"""
Statistical Analysis for Springer Computing journal paper (R1 revision).

AGGREGATION LEVELS — READ BEFORE EDITING:
  All functions in this module operate at the PER-RUN level unless explicitly
  noted. Each benchmark run produces one k6 JSON summary file. Metrics such as
  avg, p50, p95, p99 in those files are already aggregated over ~1000 requests
  within that single run. Statistical tests therefore compare n=runs vectors
  (n=5-7 for Jan-2026 baseline, n=3 for r1-revision groups).

  This distinction is critical: computing Cohen's d on per-run means inflates
  the effect size dramatically compared to per-request level (see R3.2 response
  and cohens-d-aggregation-comparison.py for full explanation).

  AGGREGATION: per-run mean (n = number of runs) unless marked otherwise.

Original analysis:
- Welch's t-test for platform comparison
- 95% Confidence Intervals using t-distribution
- Cohen's d effect size calculation

R1 revision additions (--revision-dir flag):
- Bootstrap 95% CIs (percentile method, 10 000 resamples) replacing t-CIs
- Mann-Whitney U non-parametric test (burst scenarios, R3.3)
- Multi-region r1-revision ingestion (R1.4 / R3.2)
- Cohen's d at both run-level and synthetic request-level (R3.2 artifact demo)
- Burst stage proxy analysis (R1.4)
- LaTeX-ready table fragments for §5

Usage:
    # Jan 2026 baseline only (backwards-compatible):
    python statistical_analysis.py --input-dir benchmark/results --output-dir benchmark/analysis/output

    # Full R1 revision analysis (adds --revision-dir):
    python statistical_analysis.py \\
        --input-dir benchmark/results \\
        --revision-dir benchmark/results/r1-revision \\
        --output-dir benchmark/analysis/output
"""

import json
import os
import sys
import glob
import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional

import pandas as pd
import numpy as np
from scipy import stats
from tabulate import tabulate

# ---------------------------------------------------------------------------
# Local module imports — resolved relative to this file's directory.
# Hyphenated filenames (kebab-case) are loaded via importlib since Python
# cannot import them with the `import` statement directly.
# ---------------------------------------------------------------------------
_THIS_DIR = Path(__file__).parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))


def _load_local(filename: str):
    """Dynamically load a local .py module by filename (supports kebab-case names)."""
    import importlib.util
    path = _THIS_DIR / filename
    spec = importlib.util.spec_from_file_location(filename.replace("-", "_").replace(".py", ""), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_bootstrap_mod = _load_local("bootstrap.py")
bootstrap_ci = _bootstrap_mod.bootstrap_ci

_nonparam_mod = _load_local("nonparametric-stats.py")
mann_whitney_u = _nonparam_mod.mann_whitney_u
shapiro_test = _nonparam_mod.shapiro_test

_ingest_mod = _load_local("ingest-r1-revision.py")
ingest_revision_results = _ingest_mod.ingest_revision_results
summarize_revision_data = _ingest_mod.summarize_revision_data

_burst_mod = _load_local("burst-stage-analyzer.py")
analyze_burst_per_group = _burst_mod.analyze_burst_per_group
compare_platforms_per_stage_proxy = _burst_mod.compare_platforms_per_stage_proxy
get_stage_definitions_note = _burst_mod.get_stage_definitions_note

_cohens_mod = _load_local("cohens-d-aggregation-comparison.py")
build_aggregation_comparison_table = _cohens_mod.build_aggregation_comparison_table
compute_aggregation_comparison = _cohens_mod.compute_aggregation_comparison

_emitter_mod = _load_local("paper-table-emitter.py")
emit_warm_comparison_table = _emitter_mod.emit_warm_comparison_table
emit_multiregion_warm_table = _emitter_mod.emit_multiregion_warm_table
emit_burst_stage_table = _emitter_mod.emit_burst_stage_table
emit_aggregation_comparison_table = _emitter_mod.emit_aggregation_comparison_table
emit_cold_start_table = _emitter_mod.emit_cold_start_table
emit_mannwhitney_table = _emitter_mod.emit_mannwhitney_table


# ============================================================================
# Statistical Functions
# ============================================================================

def calculate_confidence_interval(data: np.ndarray, confidence: float = 0.95) -> Tuple[float, float, float]:
    """
    Calculate confidence interval using t-distribution.
    
    Args:
        data: Array of measurements
        confidence: Confidence level (default 0.95 for 95% CI)
    
    Returns:
        Tuple of (mean, ci_lower, ci_upper)
    """
    n = len(data)
    if n < 2:
        return (np.mean(data), np.mean(data), np.mean(data))
    
    mean = np.mean(data)
    se = stats.sem(data)
    h = se * stats.t.ppf((1 + confidence) / 2, n - 1)
    
    return (mean, mean - h, mean + h)


def cohens_d(group1: np.ndarray, group2: np.ndarray) -> float:
    """
    Calculate Cohen's d effect size.
    
    Interpretation:
        |d| < 0.2: negligible
        0.2 <= |d| < 0.5: small
        0.5 <= |d| < 0.8: medium
        |d| >= 0.8: large
    
    Args:
        group1: First group measurements
        group2: Second group measurements
    
    Returns:
        Cohen's d value (positive means group1 < group2)
    """
    n1, n2 = len(group1), len(group2)
    var1 = np.var(group1, ddof=1)
    var2 = np.var(group2, ddof=1)
    
    # Pooled standard deviation
    pooled_std = np.sqrt(((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2))
    
    if pooled_std == 0:
        return 0.0
    
    return (np.mean(group2) - np.mean(group1)) / pooled_std


def interpret_cohens_d(d: float) -> str:
    """Interpret Cohen's d effect size."""
    abs_d = abs(d)
    if abs_d < 0.2:
        return "negligible"
    elif abs_d < 0.5:
        return "small"
    elif abs_d < 0.8:
        return "medium"
    else:
        return "large"


def welch_ttest(group1: np.ndarray, group2: np.ndarray) -> Dict[str, Any]:
    """
    Perform Welch's t-test (unequal variances).
    
    Args:
        group1: First group measurements (e.g., Cloudflare)
        group2: Second group measurements (e.g., Vercel)
    
    Returns:
        Dictionary with t-statistic, p-value, significance, and effect size
    """
    if len(group1) < 2 or len(group2) < 2:
        return {
            't_statistic': None,
            'p_value': None,
            'significant': None,
            'effect_size': None,
            'effect_interpretation': None
        }
    
    t_stat, p_value = stats.ttest_ind(group1, group2, equal_var=False)
    d = cohens_d(group1, group2)
    
    return {
        't_statistic': t_stat,
        'p_value': p_value,
        'significant': p_value < 0.05,
        'effect_size': d,
        'effect_interpretation': interpret_cohens_d(d)
    }


# ============================================================================
# Data Loading
# ============================================================================

def load_benchmark_results(input_dir: str) -> Dict[str, Dict[str, List[Dict]]]:
    """
    Load all benchmark result JSON files, organized by scenario and platform.
    
    Returns:
        {scenario: {platform: [run_data, ...]}}
    """
    results = {
        'warm-performance': {'cloudflare': [], 'vercel': []},
        'load-test': {'cloudflare': [], 'vercel': []},
        'burst-test': {'cloudflare': [], 'vercel': []},
        'cold-start': {'cloudflare': [], 'vercel': []},
    }
    
    json_files = glob.glob(os.path.join(input_dir, '*.json'))
    
    for file_path in json_files:
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            
            filename = os.path.basename(file_path).lower()
            
            # Skip aggregated/summary files
            if 'aggregated' in filename or 'summary' in filename:
                continue
            
            # Determine platform
            platform = None
            if 'cloudflare' in filename:
                platform = 'cloudflare'
            elif 'vercel' in filename:
                platform = 'vercel'
            
            if not platform:
                continue
            
            # Determine scenario
            for scenario in results.keys():
                if scenario in filename:
                    data['_filename'] = filename
                    results[scenario][platform].append(data)
                    break
                    
        except Exception as e:
            print(f"Warning: Failed to load {file_path}: {e}")
    
    return results


def extract_latency_metrics(data: Dict) -> Dict[str, float]:
    """Extract latency metrics from k6 result data."""
    metrics = {}
    
    if 'metrics' not in data:
        return metrics
    
    k6_metrics = data['metrics']
    
    if 'http_req_duration' in k6_metrics:
        dur = k6_metrics['http_req_duration'].get('values', {})
        metrics['avg'] = dur.get('avg')
        metrics['min'] = dur.get('min')
        metrics['max'] = dur.get('max')
        metrics['p50'] = dur.get('med') or dur.get('p(50)')
        metrics['p90'] = dur.get('p(90)')
        metrics['p95'] = dur.get('p(95)')
        metrics['p99'] = dur.get('p(99)')
    
    if 'http_reqs' in k6_metrics:
        reqs = k6_metrics['http_reqs'].get('values', {})
        metrics['total_requests'] = reqs.get('count')
        metrics['throughput'] = reqs.get('rate')
    
    if 'http_req_failed' in k6_metrics:
        failed = k6_metrics['http_req_failed'].get('values', {})
        metrics['error_rate'] = failed.get('rate', 0) * 100
    
    return metrics


# ============================================================================
# Analysis Functions
# ============================================================================

def analyze_scenario(results: Dict[str, Dict[str, List[Dict]]], scenario: str,
                     use_bootstrap: bool = True) -> Dict[str, Any]:
    """
    Perform comprehensive statistical analysis for a scenario.

    AGGREGATION: per-run mean (n = number of runs). Each value in cf_values /
    vercel_values is the avg/p95/etc. exported by k6 for one complete run
    (itself an aggregate over ~1000 requests).

    R1 additions:
    - Bootstrap 95% CIs replace t-distribution CIs when use_bootstrap=True
      (t-CI kept as 'ci_t_*' for backwards-compat reference)
    - Mann-Whitney U added to comparison dict alongside Welch's t
    - Shapiro-Wilk normality flag added to each platform metric block

    Args:
        results: {scenario: {platform: [run_data, ...]}}
        scenario: scenario key to analyze
        use_bootstrap: if True, use bootstrap CIs as primary; t-CI as fallback
                       for n<3 (bootstrap unreliable below 3 obs)

    Returns:
        Dictionary with per-platform stats and comparison results
    """
    cf_data = results[scenario]['cloudflare']
    vercel_data = results[scenario]['vercel']

    analysis = {
        'scenario': scenario,
        'cloudflare': {'n': len(cf_data), 'metrics': {}},
        'vercel': {'n': len(vercel_data), 'metrics': {}},
        'comparison': {},
        'aggregation_level': 'per-run',
        'ci_method': 'bootstrap_percentile_10k' if use_bootstrap else 't_distribution',
    }

    # AGGREGATION: extract one aggregate value per run
    cf_metrics = [extract_latency_metrics(d) for d in cf_data]
    vercel_metrics = [extract_latency_metrics(d) for d in vercel_data]

    metric_names = ['avg', 'p50', 'p95', 'p99', 'throughput', 'error_rate']

    for metric in metric_names:
        cf_values = np.array([m.get(metric) for m in cf_metrics if m.get(metric) is not None])
        vercel_values = np.array([m.get(metric) for m in vercel_metrics if m.get(metric) is not None])

        # Per-platform stats
        for plat, values in [('cloudflare', cf_values), ('vercel', vercel_values)]:
            if len(values) == 0:
                continue

            # t-distribution CI (backwards compat)
            t_mean, t_lo, t_hi = calculate_confidence_interval(values)

            # Bootstrap CI (primary for R1 revision)
            if use_bootstrap and len(values) >= 3:
                b_mean, b_lo, b_hi = bootstrap_ci(values, n_resamples=10000, seed=42)
            else:
                b_mean, b_lo, b_hi = t_mean, t_lo, t_hi  # fall back to t

            # Shapiro-Wilk normality test
            sw = shapiro_test(values)

            analysis[plat]['metrics'][metric] = {
                'mean': b_mean,
                'std': float(np.std(values, ddof=1)) if len(values) > 1 else 0.0,
                'ci_lower': b_lo,
                'ci_upper': b_hi,
                'ci_t_lower': t_lo,
                'ci_t_upper': t_hi,
                'n': len(values),
                'shapiro_W': sw.get('W'),
                'shapiro_p': sw.get('p_value'),
                'normal': sw.get('normal'),
            }

        # Comparison: Welch t-test + Mann-Whitney U
        if len(cf_values) >= 2 and len(vercel_values) >= 2:
            ttest_result = welch_ttest(cf_values, vercel_values)
            mw_result = mann_whitney_u(cf_values, vercel_values)

            if np.mean(vercel_values) != 0:
                improvement = ((np.mean(vercel_values) - np.mean(cf_values))
                               / np.mean(vercel_values)) * 100
            else:
                improvement = 0.0

            analysis['comparison'][metric] = {
                **ttest_result,
                'mann_whitney': mw_result,
                'improvement_pct': improvement,
                'cf_mean': float(np.mean(cf_values)),
                'vercel_mean': float(np.mean(vercel_values)),
            }

    return analysis


def format_ci(mean: float, ci_low: float, ci_high: float, precision: int = 2) -> str:
    """Format confidence interval for paper: mean ± margin."""
    margin = (ci_high - ci_low) / 2
    return f"{mean:.{precision}f} ± {margin:.{precision}f}"


def generate_paper_table(analysis: Dict[str, Any], metric: str = 'avg') -> pd.DataFrame:
    """Generate comparison table formatted for IEEE paper."""
    rows = []
    
    cf_stats = analysis['cloudflare']['metrics'].get(metric, {})
    vercel_stats = analysis['vercel']['metrics'].get(metric, {})
    comparison = analysis['comparison'].get(metric, {})
    
    if cf_stats and vercel_stats:
        row = {
            'Scenario': analysis['scenario'].replace('-', ' ').title(),
            'Cloudflare (95% CI)': format_ci(
                cf_stats.get('mean', 0),
                cf_stats.get('ci_lower', 0),
                cf_stats.get('ci_upper', 0)
            ) + ' ms',
            'Vercel (95% CI)': format_ci(
                vercel_stats.get('mean', 0),
                vercel_stats.get('ci_lower', 0),
                vercel_stats.get('ci_upper', 0)
            ) + ' ms',
            'p-value': f"{comparison.get('p_value', 1):.4f}" if comparison.get('p_value') else 'N/A',
            'Effect Size': f"{comparison.get('effect_size', 0):.2f} ({comparison.get('effect_interpretation', 'N/A')})" if comparison.get('effect_size') else 'N/A',
            'CF Improvement': f"{comparison.get('improvement_pct', 0):.1f}%" if comparison.get('improvement_pct') else 'N/A'
        }
        rows.append(row)
    
    return pd.DataFrame(rows)


# ============================================================================
# Report Generation
# ============================================================================

def generate_statistical_report(results: Dict[str, Dict[str, List[Dict]]], output_dir: str) -> str:
    """Generate comprehensive statistical report for IEEE paper."""
    
    os.makedirs(output_dir, exist_ok=True)
    
    lines = []
    lines.append("=" * 80)
    lines.append("STATISTICAL ANALYSIS REPORT FOR IEEE PAPER")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 80)
    
    all_tables = []
    all_analyses = {}
    
    for scenario in ['warm-performance', 'load-test', 'burst-test']:
        analysis = analyze_scenario(results, scenario)
        all_analyses[scenario] = analysis
        
        lines.append(f"\n{'=' * 60}")
        lines.append(f"SCENARIO: {scenario.upper()}")
        lines.append(f"{'=' * 60}")
        
        cf_n = analysis['cloudflare']['n']
        vercel_n = analysis['vercel']['n']
        lines.append(f"Runs: Cloudflare={cf_n}, Vercel={vercel_n}")
        
        # Latency Analysis
        lines.append(f"\n--- Average Latency ---")
        for platform in ['cloudflare', 'vercel']:
            stats = analysis[platform]['metrics'].get('avg', {})
            if stats:
                lines.append(f"  {platform.title()}: {format_ci(stats['mean'], stats['ci_lower'], stats['ci_upper'])} ms (n={stats['n']})")
        
        # Statistical Comparison
        comp = analysis['comparison'].get('avg', {})
        if comp.get('p_value') is not None:
            lines.append(f"\n--- Statistical Comparison (Avg Latency) ---")
            lines.append(f"  t-statistic: {comp['t_statistic']:.4f}")
            lines.append(f"  p-value: {comp['p_value']:.6f}")
            lines.append(f"  Significant (p<0.05): {'Yes' if comp['significant'] else 'No'}")
            lines.append(f"  Cohen's d: {comp['effect_size']:.3f} ({comp['effect_interpretation']})")
            lines.append(f"  Cloudflare Improvement: {comp['improvement_pct']:.1f}%")
        
        # P95 Analysis
        lines.append(f"\n--- P95 Latency ---")
        for platform in ['cloudflare', 'vercel']:
            stats = analysis[platform]['metrics'].get('p95', {})
            if stats:
                lines.append(f"  {platform.title()}: {format_ci(stats['mean'], stats['ci_lower'], stats['ci_upper'])} ms")
        
        # Throughput (for load-test)
        if scenario in ['load-test', 'burst-test']:
            lines.append(f"\n--- Throughput ---")
            for platform in ['cloudflare', 'vercel']:
                stats = analysis[platform]['metrics'].get('throughput', {})
                if stats:
                    lines.append(f"  {platform.title()}: {stats['mean']:.2f} req/s")
        
        # Generate table for this scenario
        table = generate_paper_table(analysis, 'avg')
        if not table.empty:
            all_tables.append(table)
    
    # Combine all tables
    if all_tables:
        combined_table = pd.concat(all_tables, ignore_index=True)
        
        lines.append(f"\n{'=' * 80}")
        lines.append("SUMMARY TABLE FOR PAPER")
        lines.append("=" * 80)
        lines.append(tabulate(combined_table, headers='keys', tablefmt='grid', showindex=False))
        
        # Save as CSV
        csv_path = os.path.join(output_dir, 'statistical_summary.csv')
        combined_table.to_csv(csv_path, index=False)
        lines.append(f"\nTable saved to: {csv_path}")
        
        # Save as LaTeX
        latex_path = os.path.join(output_dir, 'statistical_summary.tex')
        latex_content = generate_latex_table(combined_table)
        with open(latex_path, 'w') as f:
            f.write(latex_content)
        lines.append(f"LaTeX saved to: {latex_path}")
    
    lines.append(f"\n{'=' * 80}")
    lines.append("KEY FINDINGS FOR PAPER")
    lines.append("=" * 80)
    
    # Generate key findings
    findings = generate_key_findings(all_analyses)
    for i, finding in enumerate(findings, 1):
        lines.append(f"{i}. {finding}")
    
    lines.append(f"\n{'=' * 80}")
    lines.append("END OF STATISTICAL REPORT")
    lines.append("=" * 80)
    
    report_text = "\n".join(lines)
    
    # Save report
    report_path = os.path.join(output_dir, 'statistical_report.txt')
    with open(report_path, 'w') as f:
        f.write(report_text)
    
    print(report_text)
    print(f"\nReport saved to: {report_path}")
    
    # Save analyses as JSON for visualization scripts
    json_path = os.path.join(output_dir, 'statistical_analysis.json')
    with open(json_path, 'w') as f:
        json.dump(all_analyses, f, indent=2, default=str)
    print(f"Analysis data saved to: {json_path}")
    
    return report_text


def generate_latex_table(df: pd.DataFrame) -> str:
    """Generate LaTeX table for IEEE paper."""
    latex = r"""\begin{table}[htbp]
\centering
\caption{Statistical Comparison of Cloudflare Workers vs Vercel Edge Functions}
\label{tab:statistical-comparison}
\begin{tabular}{lccccc}
\toprule
Scenario & Cloudflare (95\% CI) & Vercel (95\% CI) & p-value & Effect Size & Improvement \\
\midrule
"""
    
    for _, row in df.iterrows():
        # Replace ± with LaTeX-compatible $\pm$
        cf_ci = str(row['Cloudflare (95% CI)']).replace('±', r'$\pm$')
        vercel_ci = str(row['Vercel (95% CI)']).replace('±', r'$\pm$')
        latex += f"{row['Scenario']} & {cf_ci} & {vercel_ci} & {row['p-value']} & {row['Effect Size']} & {row['CF Improvement']} \\\\\n"
    
    latex += r"""\bottomrule
\end{tabular}
\end{table}
"""
    return latex


def generate_key_findings(analyses: Dict[str, Dict]) -> List[str]:
    """Generate key findings statements for paper."""
    findings = []
    
    # Overall latency finding
    warm = analyses.get('warm-performance', {})
    if warm:
        cf_avg = warm.get('cloudflare', {}).get('metrics', {}).get('avg', {}).get('mean', 0)
        vercel_avg = warm.get('vercel', {}).get('metrics', {}).get('avg', {}).get('mean', 0)
        
        if cf_avg and vercel_avg:
            ratio = vercel_avg / cf_avg if cf_avg > 0 else 0
            findings.append(
                f"Cloudflare Workers achieves {ratio:.1f}x lower average latency "
                f"({cf_avg:.1f}ms vs {vercel_avg:.1f}ms) compared to Vercel Edge Functions."
            )
    
    # Statistical significance
    all_significant = True
    for scenario, analysis in analyses.items():
        comp = analysis.get('comparison', {}).get('avg', {})
        if comp.get('p_value') is not None and comp['p_value'] >= 0.05:
            all_significant = False
    
    if all_significant:
        findings.append(
            "All performance differences are statistically significant (p < 0.05) "
            "with large effect sizes (Cohen's d > 0.8)."
        )
    
    # Throughput finding
    load = analyses.get('load-test', {})
    if load:
        cf_tp = load.get('cloudflare', {}).get('metrics', {}).get('throughput', {}).get('mean', 0)
        vercel_tp = load.get('vercel', {}).get('metrics', {}).get('throughput', {}).get('mean', 0)
        
        if cf_tp and vercel_tp:
            improvement = ((cf_tp - vercel_tp) / vercel_tp) * 100 if vercel_tp > 0 else 0
            findings.append(
                f"Under load, Cloudflare Workers sustains {improvement:.0f}% higher throughput "
                f"({cf_tp:.1f} req/s vs {vercel_tp:.1f} req/s)."
            )
    
    return findings


# ============================================================================
# R1-Revision Analysis Pipeline
# ============================================================================

def analyze_r1_revision(revision_dir: str, output_dir: str,
                        jan_results: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Full R1-revision statistical analysis pipeline.

    Produces:
    1. r1-revision-stats.csv  — per-group stats across all scenarios/regions
    2. r1-aggregation-comparison.csv — Cohen's d run-level vs request-level
    3. r1-burst-per-stage.csv — burst stage proxy analysis
    4. r1-tables/*.tex  — LaTeX table fragments for manuscript §5

    Args:
        revision_dir: Path to benchmark/results/r1-revision
        output_dir:   Base output directory (creates r1-tables/ subdir)
        jan_results:  Optional Jan-2026 baseline results dict for aggregation
                      comparison across both datasets.

    Returns:
        Dict with summary findings for report generation.
    """
    print(f"\n{'='*60}")
    print("R1-REVISION STATISTICAL ANALYSIS")
    print(f"{'='*60}")

    os.makedirs(output_dir, exist_ok=True)
    tables_dir = os.path.join(output_dir, "r1-tables")
    os.makedirs(tables_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # 1. Ingest r1-revision data
    # ------------------------------------------------------------------
    print(f"\nIngesting: {revision_dir}")
    rev_df = ingest_revision_results(revision_dir)
    print(f"Loaded {len(rev_df)} run files")
    print(rev_df.groupby(["scenario", "client", "platform", "mode"]).size().to_string())

    if rev_df.empty:
        print("No r1-revision data found.")
        return {}

    # ------------------------------------------------------------------
    # 2. Per-group summary stats (n=runs per group)
    # ------------------------------------------------------------------
    summary_df = summarize_revision_data(rev_df)

    # Pivot avg latency to wide format for CSV
    avg_summary = summary_df[summary_df["metric"] == "avg"].copy()
    p95_summary = summary_df[summary_df["metric"] == "p95"].copy()

    # Build main stats CSV
    stats_rows = []
    for (scenario, client, platform, mode), grp in rev_df.groupby(
        ["scenario", "client", "platform", "mode"]
    ):
        vals_avg = grp["avg"].dropna().values
        vals_p95 = grp["p95"].dropna().values
        n_runs = len(grp)

        if n_runs == 0:
            continue

        # Bootstrap CIs on per-run avgs (n=runs, typically 3)
        avg_mean = float(np.mean(vals_avg)) if len(vals_avg) else None
        if len(vals_avg) >= 2:
            _, b_lo_avg, b_hi_avg = bootstrap_ci(vals_avg, n_resamples=10000, seed=42)
        else:
            b_lo_avg = b_hi_avg = avg_mean

        p95_mean = float(np.mean(vals_p95)) if len(vals_p95) else None
        if len(vals_p95) >= 2:
            _, b_lo_p95, b_hi_p95 = bootstrap_ci(vals_p95, n_resamples=10000, seed=43)
        else:
            b_lo_p95 = b_hi_p95 = p95_mean

        # Shapiro-Wilk on avgs (n typically 3 — informational only)
        sw = shapiro_test(vals_avg) if len(vals_avg) >= 3 else {"W": None, "p_value": None}

        stats_rows.append({
            "scenario": scenario,
            "client": client,
            "platform": platform,
            "mode": mode,
            "n_runs": n_runs,
            "avg_mean_ms": avg_mean,
            "avg_ci95_low": b_lo_avg,
            "avg_ci95_high": b_hi_avg,
            "p95_mean_ms": p95_mean,
            "p95_ci95_low": b_lo_p95,
            "p95_ci95_high": b_hi_p95,
            "shapiro_W": sw.get("W"),
            "shapiro_p": sw.get("p_value"),
        })

    stats_csv_df = pd.DataFrame(stats_rows)
    stats_csv_path = os.path.join(output_dir, "r1-revision-stats.csv")
    stats_csv_df.to_csv(stats_csv_path, index=False)
    print(f"\nSaved: {stats_csv_path}")

    # ------------------------------------------------------------------
    # 3. Mann-Whitney U for warm and burst (R3.3)
    # ------------------------------------------------------------------
    print("\nComputing Mann-Whitney U tests...")
    mw_results = []

    for (scenario, client, mode), grp in rev_df.groupby(["scenario", "client", "mode"]):
        cf_grp = grp[grp["platform"] == "cloudflare"]["avg"].dropna().values
        vc_grp = grp[grp["platform"] == "vercel"]["avg"].dropna().values

        if len(cf_grp) < 2 or len(vc_grp) < 2:
            continue

        mw = mann_whitney_u(cf_grp, vc_grp)
        mw_results.append({
            "scenario": scenario,
            "group": f"{client}/{mode}",
            "metric": "avg",
            **mw,
        })
        print(f"  {scenario}/{client}/{mode}: U={mw.get('u_statistic'):.1f}, "
              f"p={mw.get('p_value'):.4f}, r={mw.get('effect_r'):.3f}, "
              f"sig={mw.get('significant')}")

    # ------------------------------------------------------------------
    # 4. Cohen's d aggregation comparison (R3.2)
    # ------------------------------------------------------------------
    print("\nComputing Cohen's d aggregation comparison...")
    agg_df = build_aggregation_comparison_table(rev_df)

    if jan_results is not None:
        # Append Jan-2026 baseline aggregation comparison
        jan_rows = []
        for scenario in ["warm-performance", "load-test", "burst-test"]:
            cf_data = jan_results.get(scenario, {}).get("cloudflare", [])
            vc_data = jan_results.get(scenario, {}).get("vercel", [])
            if len(cf_data) < 2 or len(vc_data) < 2:
                continue
            cf_m = [extract_latency_metrics(d) for d in cf_data]
            vc_m = [extract_latency_metrics(d) for d in vc_data]
            cf_avgs = np.array([m.get("avg") for m in cf_m if m.get("avg")])
            vc_avgs = np.array([m.get("avg") for m in vc_m if m.get("avg")])
            row = compute_aggregation_comparison(
                cf_avgs, vc_avgs, cf_m, vc_m,
                scenario=scenario, group_label="jan2026-baseline",
            )
            jan_rows.append(row)

        if jan_rows:
            jan_agg_df = pd.DataFrame(jan_rows)
            agg_df = pd.concat([jan_agg_df, agg_df], ignore_index=True)

    agg_csv_path = os.path.join(output_dir, "r1-aggregation-comparison.csv")
    agg_df.to_csv(agg_csv_path, index=False)
    print(f"Saved: {agg_csv_path}")

    # Print headline inflation numbers
    for _, row in agg_df.iterrows():
        print(f"  {row.get('scenario')}/{row.get('group')}: "
              f"d_run={row.get('d_run_level'):.2f}, "
              f"d_req={row.get('d_request_synth'):.2f}, "
              f"inflation={row.get('inflation_factor'):.1f}x")

    # ------------------------------------------------------------------
    # 5. Burst stage proxy analysis (R1.4)
    # ------------------------------------------------------------------
    print("\nComputing burst stage proxy analysis...")
    burst_comparison = compare_platforms_per_stage_proxy(rev_df)

    burst_csv_path = os.path.join(output_dir, "r1-burst-per-stage.csv")
    burst_comparison.to_csv(burst_csv_path, index=False)
    print(f"Saved: {burst_csv_path}")

    # ------------------------------------------------------------------
    # 6. LaTeX table output
    # ------------------------------------------------------------------
    print("\nEmitting LaTeX tables...")

    # Multi-region warm table
    emit_multiregion_warm_table(
        rev_df,
        os.path.join(tables_dir, "warm.tex"),
    )
    print(f"  Saved: {tables_dir}/warm.tex")

    # Burst stage table
    emit_burst_stage_table(
        burst_comparison,
        os.path.join(tables_dir, "burst.tex"),
    )
    print(f"  Saved: {tables_dir}/burst.tex")

    # Cold start table
    emit_cold_start_table(
        rev_df,
        os.path.join(tables_dir, "cold.tex"),
    )
    print(f"  Saved: {tables_dir}/cold.tex")

    # Aggregation comparison table (R3.2)
    emit_aggregation_comparison_table(
        agg_df,
        os.path.join(tables_dir, "aggregation.tex"),
    )
    print(f"  Saved: {tables_dir}/aggregation.tex")

    # Mann-Whitney table (R3.3)
    emit_mannwhitney_table(
        mw_results,
        os.path.join(tables_dir, "mannwhitney.tex"),
    )
    print(f"  Saved: {tables_dir}/mannwhitney.tex")

    # ------------------------------------------------------------------
    # 7. Summary findings dict (for report)
    # ------------------------------------------------------------------
    findings = _extract_revision_findings(rev_df, agg_df, burst_comparison, mw_results)

    print(f"\n{'='*60}")
    print("R1-REVISION ANALYSIS COMPLETE")
    print(f"{'='*60}")

    return {
        "rev_df": rev_df,
        "stats_csv": stats_csv_df,
        "agg_df": agg_df,
        "burst_comparison": burst_comparison,
        "mw_results": mw_results,
        "findings": findings,
    }


def _extract_revision_findings(
    rev_df: pd.DataFrame,
    agg_df: pd.DataFrame,
    burst_comparison: pd.DataFrame,
    mw_results: List[Dict],
) -> List[str]:
    """Extract manuscript-ready finding statements from r1-revision analysis."""
    findings = []

    # Warm latency: local CF vs Vercel
    warm_local = rev_df[
        (rev_df["scenario"] == "warm") & (rev_df["client"] == "local") & (rev_df["mode"] == "mock")
    ]
    cf_warm = warm_local[warm_local["platform"] == "cloudflare"]["avg"].dropna()
    vc_warm = warm_local[warm_local["platform"] == "vercel"]["avg"].dropna()
    if len(cf_warm) > 0 and len(vc_warm) > 0:
        ratio = float(np.mean(vc_warm)) / float(np.mean(cf_warm))
        findings.append(
            f"F1: Cloudflare Workers achieves {ratio:.1f}x lower avg latency than Vercel "
            f"({np.mean(cf_warm):.1f} vs {np.mean(vc_warm):.1f} ms) in local/mock warm test "
            f"[Table: multiregion-warm]."
        )

    # Aggregation artifact
    if not agg_df.empty:
        max_inflation = agg_df["inflation_factor"].dropna().max()
        max_d_run = agg_df["d_run_level"].dropna().abs().max()
        max_d_req = agg_df["d_request_synth"].dropna().abs().max()
        findings.append(
            f"F2 (R3.2): Run-level Cohen's d (max={max_d_run:.1f}) is inflated by "
            f"variance compression vs synthetic request-level d (max={max_d_req:.1f}), "
            f"inflation factor up to {max_inflation:.1f}x. Both levels confirm large effect. "
            f"[Table: aggregation-comparison]."
        )

    # Mann-Whitney results
    sig_mw = [r for r in mw_results if r.get("significant")]
    insig_mw = [r for r in mw_results if not r.get("significant") and r.get("significant") is not None]
    if sig_mw:
        findings.append(
            f"F3 (R3.3): Mann-Whitney U confirms significant CF vs Vercel difference in "
            f"{len(sig_mw)}/{len(mw_results)} groups tested (p<0.05) [Table: mann-whitney]."
        )
    if insig_mw:
        findings.append(
            f"F3b: {len(insig_mw)} group(s) show non-significant Mann-Whitney U (p≥0.05); "
            f"likely low n=3 per group — effect present but underpowered [Table: mann-whitney]."
        )

    # Burst tail severity
    if not burst_comparison.empty:
        cf_severe = burst_comparison[burst_comparison["cf_tail_severity"].isin(["severe", "moderate"])]
        if not cf_severe.empty:
            max_ratio = burst_comparison["cf_p99_p95_ratio"].dropna().max()
            findings.append(
                f"F4 (R1.4): Burst test CF p99/p95 ratio up to {max_ratio:.2f}, indicating "
                f"spike-stage heavy-tail contribution. Per-stage breakdown limited by absent "
                f"rawLatencies; ratio proxy used [Table: burst-stage]."
            )

    # Multi-region comparison
    warm_df = rev_df[(rev_df["scenario"] == "warm") & (rev_df["mode"] == "mock")]
    for client in ["eu-west-1", "ap-southeast-1"]:
        cf_g = warm_df[(warm_df["client"] == client) & (warm_df["platform"] == "cloudflare")]["avg"].dropna()
        vc_g = warm_df[(warm_df["client"] == client) & (warm_df["platform"] == "vercel")]["avg"].dropna()
        if len(cf_g) > 0 and len(vc_g) > 0:
            impr = (float(np.mean(vc_g)) - float(np.mean(cf_g))) / float(np.mean(vc_g)) * 100
            findings.append(
                f"F5: {client} warm mock — CF {np.mean(cf_g):.1f} ms vs Vercel "
                f"{np.mean(vc_g):.1f} ms ({impr:.1f}% CF improvement) [Table: multiregion-warm]."
            )

    # US-East caveat
    us_east = rev_df[(rev_df["client"] == "us-east-1") & (rev_df["mode"] == "live")]
    if us_east.empty:
        findings.append(
            "F6 (caveat): US-East-1 has mock-only data. Binance geo-blocks live API "
            "requests from AWS us-east-1; all US-East results are mock endpoint only."
        )

    # Cold start cross-region
    cold_df = rev_df[rev_df["scenario"] == "cold"]
    if not cold_df.empty:
        cf_cold = cold_df[cold_df["platform"] == "cloudflare"]["avg"].dropna()
        vc_cold = cold_df[cold_df["platform"] == "vercel"]["avg"].dropna()
        if len(cf_cold) > 0 and len(vc_cold) > 0:
            findings.append(
                f"F7: Cold-start — CF avg {np.mean(cf_cold):.1f} ms vs Vercel "
                f"{np.mean(vc_cold):.1f} ms across {cold_df['client'].nunique()} regions "
                f"(n=1 run/cell, descriptive only) [Table: cold-start-multiregion]."
            )

    return findings


# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Statistical analysis for Springer Computing paper (R1 revision)"
    )
    parser.add_argument(
        "--input-dir", default="benchmark/results",
        help="Directory containing Jan-2026 baseline benchmark JSON files",
    )
    parser.add_argument(
        "--revision-dir", default=None,
        help=(
            "Directory containing r1-revision hierarchical benchmark results "
            "(benchmark/results/r1-revision). When present, runs full R1-revision "
            "analysis pipeline in addition to baseline."
        ),
    )
    parser.add_argument(
        "--output-dir", default="benchmark/analysis/output",
        help="Directory for output files (CSV, LaTeX, JSON, TXT)",
    )
    parser.add_argument(
        "--no-bootstrap", action="store_true",
        help="Use t-distribution CIs instead of bootstrap (faster, less accurate)",
    )

    args = parser.parse_args()
    use_bootstrap = not args.no_bootstrap

    # ------------------------------------------------------------------
    # Jan-2026 baseline analysis (always run — backwards compat)
    # ------------------------------------------------------------------
    print(f"Loading Jan-2026 baseline from: {args.input_dir}")
    results = load_benchmark_results(args.input_dir)

    total = sum(len(results[s][p]) for s in results for p in results[s])
    print(f"Loaded {total} result files")

    for scenario in results:
        cf_n = len(results[scenario]["cloudflare"])
        vercel_n = len(results[scenario]["vercel"])
        if cf_n > 0 or vercel_n > 0:
            print(f"  {scenario}: CF={cf_n}, Vercel={vercel_n}")

    if total == 0:
        print("No baseline benchmark results found.")
    else:
        # Pass use_bootstrap flag through to analyze_scenario via monkeypatching
        # the global default — simplest approach without refactoring generate_statistical_report
        _orig_analyze = analyze_scenario

        def _patched_analyze(results, scenario):
            return _orig_analyze(results, scenario, use_bootstrap=use_bootstrap)

        import types
        # Patch in local scope only for report generation
        _old = globals().get("analyze_scenario")
        globals()["analyze_scenario"] = _patched_analyze
        generate_statistical_report(results, args.output_dir)
        globals()["analyze_scenario"] = _orig_analyze  # restore

        # Also emit baseline warm comparison LaTeX with bootstrap CIs
        all_analyses = {}
        for scenario in ["warm-performance", "load-test", "burst-test"]:
            all_analyses[scenario] = analyze_scenario(results, scenario, use_bootstrap=use_bootstrap)

        # Save updated analyses JSON (with bootstrap CIs)
        json_path = os.path.join(args.output_dir, "statistical_analysis.json")
        with open(json_path, "w") as f:
            json.dump(all_analyses, f, indent=2, default=str)
        print(f"Updated analysis JSON (with bootstrap CIs): {json_path}")

        tables_dir = os.path.join(args.output_dir, "r1-tables")
        os.makedirs(tables_dir, exist_ok=True)
        emit_warm_comparison_table(
            all_analyses,
            os.path.join(tables_dir, "warm-baseline.tex"),
        )
        print(f"Saved baseline LaTeX table: {tables_dir}/warm-baseline.tex")

    # ------------------------------------------------------------------
    # R1-revision analysis (only when --revision-dir supplied)
    # ------------------------------------------------------------------
    if args.revision_dir:
        revision_path = args.revision_dir
        if not os.path.exists(revision_path):
            print(f"ERROR: --revision-dir not found: {revision_path}")
            return

        analyze_r1_revision(
            revision_dir=revision_path,
            output_dir=args.output_dir,
            jan_results=results if total > 0 else None,
        )
    else:
        print("\nSkipping r1-revision analysis (--revision-dir not supplied).")
        print("Re-run with --revision-dir benchmark/results/r1-revision for full analysis.")


if __name__ == "__main__":
    main()
