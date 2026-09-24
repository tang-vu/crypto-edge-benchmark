"""
LaTeX table emitter for Springer Computing journal manuscript.

Produces booktabs-format LaTeX table fragments for direct \input{} inclusion
in manuscript §5. All tables are self-contained (include \begin{table}...\end{table}).

Formatting conventions:
- p-values: shown as exact to 3 sig-figs, or <0.001 if below threshold
- CIs: mean ± half-width format, e.g. "42.3 ± 1.2 ms"
- Cohen's d: two decimal places with verbal label in parentheses
- Effect r: two decimal places with verbal label
- Percentages: one decimal place with % sign
- n=: shown in column headers as "(n=X runs)"
"""

import os
import numpy as np
import pandas as pd
from typing import Optional


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def fmt_p_value(p: Optional[float]) -> str:
    """Format p-value: '<0.001' for very small, otherwise 3 sig-figs."""
    if p is None or (isinstance(p, float) and np.isnan(p)):
        return "N/A"
    if p < 0.001:
        return "$<$0.001"
    if p < 0.01:
        return f"{p:.4f}"
    return f"{p:.3f}"


def fmt_ci(mean: Optional[float], ci_low: Optional[float], ci_high: Optional[float],
           unit: str = "ms", precision: int = 1) -> str:
    """Format confidence interval as 'mean ± margin unit'."""
    if mean is None or ci_low is None or ci_high is None:
        return "N/A"
    if np.isnan(mean):
        return "N/A"
    margin = (ci_high - ci_low) / 2.0
    return f"{mean:.{precision}f} $\\pm$ {margin:.{precision}f} {unit}".strip()


def fmt_cohens_d(d: Optional[float], interp: str = "") -> str:
    """Format Cohen's d with verbal interpretation."""
    if d is None or (isinstance(d, float) and np.isnan(d)):
        return "N/A"
    label = interp if interp else _interp_d(abs(d))
    return f"{d:.2f} ({label})"


def fmt_effect_r(r: Optional[float]) -> str:
    """Format rank-biserial correlation r with verbal label."""
    if r is None or (isinstance(r, float) and np.isnan(r)):
        return "N/A"
    label = _interp_r(abs(r))
    return f"{r:.2f} ({label})"


def fmt_pct(value: Optional[float], precision: int = 1) -> str:
    """Format percentage value."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "N/A"
    return f"{value:.{precision}f}\\%"


def fmt_ms(value: Optional[float], precision: int = 1) -> str:
    """Format millisecond value."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "N/A"
    return f"{value:.{precision}f}"


def _interp_d(abs_d: float) -> str:
    if abs_d < 0.2:
        return "negligible"
    elif abs_d < 0.5:
        return "small"
    elif abs_d < 0.8:
        return "medium"
    return "large"


def _interp_r(abs_r: float) -> str:
    if abs_r < 0.1:
        return "negligible"
    elif abs_r < 0.3:
        return "small"
    elif abs_r < 0.5:
        return "medium"
    return "large"


# ---------------------------------------------------------------------------
# Core LaTeX scaffold
# ---------------------------------------------------------------------------

def _wrap_table(body: str, caption: str, label: str,
                position: str = "htbp", fontsize: str = "\\small") -> str:
    """Wrap table body in standard Springer-compatible table environment."""
    return (
        f"\\begin{{table}}[{position}]\n"
        f"\\centering\n"
        f"{fontsize}\n"
        f"\\caption{{{caption}}}\n"
        f"\\label{{tab:{label}}}\n"
        f"{body}\n"
        f"\\end{{table}}\n"
    )


def _tabular(col_spec: str, header: str, rows: list[str],
             midrule_after: list[int] = None) -> str:
    """Build tabular environment with booktabs rules."""
    lines = [
        f"\\begin{{tabular}}{{{col_spec}}}",
        "\\toprule",
        header + " \\\\",
        "\\midrule",
    ]
    for i, row in enumerate(rows):
        lines.append(row + " \\\\")
        if midrule_after and i in midrule_after:
            lines.append("\\midrule")
    lines += ["\\bottomrule", "\\end{tabular}"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Table generators
# ---------------------------------------------------------------------------

def emit_warm_comparison_table(stats_json: dict, output_path: str) -> str:
    """
    Table: Warm-performance CF vs Vercel comparison with bootstrap CIs.
    Columns: Scenario | CF (95% CI) | Vercel (95% CI) | p-value | Cohen's d | CF Improvement
    """
    scenarios_display = {
        "warm-performance": "Warm Performance",
        "load-test": "Load Test",
        "burst-test": "Burst Test",
    }

    col_spec = "lccccr"
    header = (
        "Scenario & Cloudflare (95\\% CI) & Vercel (95\\% CI) "
        "& $p$-value & Cohen's $d$ & CF Improvement"
    )
    rows = []

    for scenario, display in scenarios_display.items():
        if scenario not in stats_json:
            continue
        s = stats_json[scenario]
        cf_m = s.get("cloudflare", {}).get("metrics", {}).get("avg", {})
        vc_m = s.get("vercel", {}).get("metrics", {}).get("avg", {})
        comp = s.get("comparison", {}).get("avg", {})

        cf_ci = fmt_ci(cf_m.get("mean"), cf_m.get("ci_lower"), cf_m.get("ci_upper"))
        vc_ci = fmt_ci(vc_m.get("mean"), vc_m.get("ci_lower"), vc_m.get("ci_upper"))
        p_str = fmt_p_value(comp.get("p_value"))
        d_str = fmt_cohens_d(comp.get("effect_size"), comp.get("effect_interpretation", ""))
        impr = fmt_pct(comp.get("improvement_pct"))
        n_cf = cf_m.get("n", "?")

        rows.append(
            f"{display} (n={n_cf} runs) & {cf_ci} & {vc_ci} & {p_str} & {d_str} & {impr}"
        )

    body = _tabular(col_spec, header, rows)
    caption = (
        "Cloudflare Workers vs.\\ Vercel Edge Functions: latency comparison "
        "(January 2026 baseline, $n$=runs per platform). "
        "CIs are 95\\% bootstrap percentile intervals (10{,}000 resamples). "
        "$p$-values from Welch's $t$-test on per-run means."
    )
    tex = _wrap_table(body, caption, "warm-comparison")
    _write_tex(tex, output_path)
    return tex


def emit_multiregion_warm_table(revision_df: pd.DataFrame,
                                output_path: str) -> str:
    """
    Table: Multi-region warm latency (CF vs Vercel, mock mode).
    Rows: client region. Columns: CF avg±CI | Vercel avg±CI | CF p95 | Vercel p95 | Δ avg%
    """
    warm = revision_df[
        (revision_df["scenario"] == "warm") & (revision_df["mode"] == "mock")
    ].copy()

    if warm.empty:
        tex = "% No warm mock data found for multi-region table\n"
        _write_tex(tex, output_path)
        return tex

    col_spec = "lrrrrc"
    header = (
        "Region & CF avg (ms) & Vercel avg (ms) & CF p95 (ms) "
        "& Vercel p95 (ms) & CF Improvement"
    )
    rows = []

    clients_order = ["local", "eu-west-1", "us-east-1", "ap-southeast-1"]
    client_display = {
        "local": "VN (local)",
        "eu-west-1": "EU-West-1",
        "us-east-1": "US-East-1\\textsuperscript{*}",
        "ap-southeast-1": "AP-SE-1",
    }

    for client in clients_order:
        cf_grp = warm[(warm["client"] == client) & (warm["platform"] == "cloudflare")]
        vc_grp = warm[(warm["client"] == client) & (warm["platform"] == "vercel")]

        if cf_grp.empty and vc_grp.empty:
            continue

        cf_avg = float(np.mean(cf_grp["avg"].dropna())) if not cf_grp.empty else None
        vc_avg = float(np.mean(vc_grp["avg"].dropna())) if not vc_grp.empty else None
        cf_p95 = float(np.mean(cf_grp["p95"].dropna())) if not cf_grp.empty else None
        vc_p95 = float(np.mean(vc_grp["p95"].dropna())) if not vc_grp.empty else None

        impr_pct = None
        if cf_avg and vc_avg and vc_avg > 0:
            impr_pct = (vc_avg - cf_avg) / vc_avg * 100.0

        n_cf = len(cf_grp)
        n_vc = len(vc_grp)
        label = client_display.get(client, client)

        rows.append(
            f"{label} (n={n_cf}/{n_vc}) & "
            f"{fmt_ms(cf_avg)} & {fmt_ms(vc_avg)} & "
            f"{fmt_ms(cf_p95)} & {fmt_ms(vc_p95)} & "
            f"{fmt_pct(impr_pct)}"
        )

    body = _tabular(col_spec, header, rows)
    caption = (
        "Multi-region warm-performance comparison (mock mode, $n$=runs per platform per region). "
        "\\textsuperscript{*}US-East-1 mock-only: Binance geo-blocks live API in this region. "
        "All values in milliseconds."
    )
    tex = _wrap_table(body, caption, "multiregion-warm")
    _write_tex(tex, output_path)
    return tex


def emit_burst_stage_table(burst_comparison: pd.DataFrame,
                            output_path: str) -> str:
    """
    Table: Burst test CF vs Vercel comparison with tail severity proxy.
    Rows: client/mode. Columns: CF avg | Vercel avg | CF p95 | Vercel p95 |
          CF p99/p95 | Vercel p99/p95 | tail_severity_cf | impr%
    """
    if burst_comparison.empty:
        tex = "% No burst comparison data found\n"
        _write_tex(tex, output_path)
        return tex

    col_spec = "llrrrrrr"
    header = (
        "Region & Mode & CF avg & Vercel avg & CF p95 & Vercel p95 "
        "& CF $p_{99}/p_{95}$ & Improvement"
    )
    rows = []

    for _, row in burst_comparison.iterrows():
        rows.append(
            f"{row.get('client','?')} & {row.get('mode','?')} & "
            f"{fmt_ms(row.get('cf_avg_ms'))} & {fmt_ms(row.get('vercel_avg_ms'))} & "
            f"{fmt_ms(row.get('cf_p95_ms'))} & {fmt_ms(row.get('vercel_p95_ms'))} & "
            f"{fmt_ms(row.get('cf_p99_p95_ratio'), precision=2)} & "
            f"{fmt_pct(row.get('avg_cf_improvement_pct'))}"
        )

    footnote = (
        "\\\\[2pt]\\multicolumn{8}{p{0.95\\linewidth}}{\\footnotesize "
        "\\textit{Note:} Per-stage breakdown unavailable (\\texttt{rawLatencies[]}=empty "
        "in k6 output). Stage behavior inferred from whole-run $p_{99}/p_{95}$ ratio "
        "(${>}1.5$ indicates spike-stage heavy-tail contribution) and avg/$p_{50}$ skew.}"
    )
    body = _tabular(col_spec, header, rows) + "\n" + footnote
    caption = (
        "Burst test comparison: Cloudflare Workers vs.\\ Vercel Edge Functions "
        "(200-VU ramp, mock mode). Values in milliseconds. "
        "$p_{99}/p_{95}$ ratio serves as proxy for spike-stage tail severity."
    )
    tex = _wrap_table(body, caption, "burst-stage")
    _write_tex(tex, output_path)
    return tex


def emit_aggregation_comparison_table(agg_df: pd.DataFrame,
                                       output_path: str) -> str:
    """
    Table: Cohen's d at run-level vs synthetic request-level.
    Directly addresses Reviewer 3 R3.2 concern.
    """
    if agg_df.empty:
        tex = "% No aggregation comparison data\n"
        _write_tex(tex, output_path)
        return tex

    col_spec = "llrrrrl"
    header = (
        "Scenario & Group & $n_{runs}$ & "
        "$d_{\\text{run}}$ & $d_{\\text{req}}^{\\dagger}$ & "
        "Inflation & Artifact?"
    )
    rows = []

    for _, row in agg_df.iterrows():
        d_run = row.get("d_run_level")
        d_req = row.get("d_request_synth")
        inflation = row.get("inflation_factor")
        artifact = "Yes" if row.get("artifact_confirmed") else "No"

        d_run_str = fmt_cohens_d(d_run, row.get("d_run_level_interp", ""))
        d_req_str = fmt_cohens_d(d_req, row.get("d_request_synth_interp", ""))
        inf_str = f"{inflation:.1f}$\\times$" if inflation and not np.isnan(inflation) else "N/A"
        n_runs = row.get("n_runs_cf", "?")

        rows.append(
            f"{row.get('scenario','?')} & {row.get('group','?')} & "
            f"{n_runs} & {d_run_str} & {d_req_str} & {inf_str} & {artifact}"
        )

    footnote = (
        "\\\\[2pt]\\multicolumn{7}{p{0.95\\linewidth}}{\\footnotesize "
        "$\\dagger$ $d_{\\text{req}}$ computed on log-normal synthetic samples "
        "reconstructed from k6 summary percentiles (\\texttt{rawLatencies[]}=empty). "
        "Demonstrates variance-compression artifact: averaging $n{\\approx}1000$ "
        "requests per run compresses within-platform variance, inflating Cohen's $d$ "
        "at run level by the factor shown. Both levels confirm a large effect; "
        "$d_{\\text{req}}$ is the more honest magnitude statement.}"
    )
    body = _tabular(col_spec, header, rows) + "\n" + footnote
    caption = (
        "Cohen's $d$ at run-level vs.\\ synthetic request-level: "
        "aggregation artifact analysis (addresses Reviewer~3, comment~R3.2). "
        "Run-level $d$ is inflated by variance compression from per-run averaging."
    )
    tex = _wrap_table(body, caption, "aggregation-comparison")
    _write_tex(tex, output_path)
    return tex


def emit_cold_start_table(revision_df: pd.DataFrame,
                           output_path: str) -> str:
    """
    Table: Cold-start latency across regions (mock mode only, n=1 run per cell).
    """
    cold = revision_df[revision_df["scenario"] == "cold"].copy()
    if cold.empty:
        tex = "% No cold-start data found\n"
        _write_tex(tex, output_path)
        return tex

    col_spec = "lrrrr"
    header = "Region & CF avg (ms) & Vercel avg (ms) & CF p95 (ms) & Vercel p95 (ms)"
    rows = []

    clients_order = ["local", "eu-west-1", "us-east-1", "ap-southeast-1"]
    client_display = {
        "local": "VN (local)",
        "eu-west-1": "EU-West-1",
        "us-east-1": "US-East-1",
        "ap-southeast-1": "AP-SE-1",
    }

    for client in clients_order:
        cf_grp = cold[(cold["client"] == client) & (cold["platform"] == "cloudflare")]
        vc_grp = cold[(cold["client"] == client) & (cold["platform"] == "vercel")]

        cf_avg = float(np.mean(cf_grp["avg"].dropna())) if not cf_grp.empty else None
        vc_avg = float(np.mean(vc_grp["avg"].dropna())) if not vc_grp.empty else None
        cf_p95 = float(np.mean(cf_grp["p95"].dropna())) if not cf_grp.empty else None
        vc_p95 = float(np.mean(vc_grp["p95"].dropna())) if not vc_grp.empty else None

        label = client_display.get(client, client)
        n_cf = len(cf_grp)
        n_vc = len(vc_grp)

        rows.append(
            f"{label} (n={n_cf}/{n_vc}) & "
            f"{fmt_ms(cf_avg)} & {fmt_ms(vc_avg)} & "
            f"{fmt_ms(cf_p95)} & {fmt_ms(vc_p95)}"
        )

    body = _tabular(col_spec, header, rows)
    caption = (
        "Cold-start latency comparison across regions (mock mode, $n$=runs per cell). "
        "Cold-start defined as first request after 60\\,s idle period. "
        "Values in milliseconds. Low $n$ per cell limits statistical inference; "
        "values reported descriptively."
    )
    tex = _wrap_table(body, caption, "cold-start-multiregion")
    _write_tex(tex, output_path)
    return tex


def emit_mannwhitney_table(mw_results: list[dict], output_path: str) -> str:
    """
    Table: Mann-Whitney U results for warm and burst scenarios.
    Addresses Reviewer 3 R3.3 (non-parametric test).
    """
    if not mw_results:
        tex = "% No Mann-Whitney results\n"
        _write_tex(tex, output_path)
        return tex

    col_spec = "lllrrrr"
    header = (
        "Scenario & Group & Metric & "
        "$U$ statistic & $p$-value & Effect $r$ & Significant?"
    )
    rows = []

    for r in mw_results:
        sig = "Yes" if r.get("significant") else "No"
        rows.append(
            f"{r.get('scenario','?')} & {r.get('group','?')} & {r.get('metric','avg')} & "
            f"{r.get('u_statistic', 'N/A'):.1f} & "
            f"{fmt_p_value(r.get('p_value'))} & "
            f"{fmt_effect_r(r.get('effect_r'))} & {sig}"
        )

    body = _tabular(col_spec, header, rows)
    caption = (
        "Mann-Whitney $U$ test results: Cloudflare Workers vs.\\ Vercel Edge Functions "
        "(addresses Reviewer~3, comment~R3.3). "
        "Non-parametric test appropriate for burst scenarios with non-normal distributions. "
        "Effect size $r = 1 - 2U/(n_1 n_2)$ (rank-biserial correlation)."
    )
    tex = _wrap_table(body, caption, "mann-whitney")
    _write_tex(tex, output_path)
    return tex


# ---------------------------------------------------------------------------
# I/O helper
# ---------------------------------------------------------------------------

def _write_tex(content: str, path: str) -> None:
    """Write LaTeX content to file, creating directories as needed."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


if __name__ == "__main__":
    # Smoke test: generate a minimal table
    test_df = pd.DataFrame([
        {"scenario": "warm", "client": "local", "platform": "cloudflare",
         "mode": "mock", "avg": 42.5, "p95": 55.0, "p99": 68.0, "run_num": 1},
        {"scenario": "warm", "client": "local", "platform": "vercel",
         "mode": "mock", "avg": 95.2, "p95": 118.0, "p99": 145.0, "run_num": 1},
    ])
    tex = emit_multiregion_warm_table(test_df, "/tmp/test-multiregion.tex")
    print(tex[:200])
    print("paper-table-emitter.py smoke test passed.")
