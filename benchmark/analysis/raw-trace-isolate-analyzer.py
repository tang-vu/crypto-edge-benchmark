#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P9.2 — Raw Trace Isolate-Level Distribution Analyzer

Parses HDR: NDJSON lines emitted by burst-test-headers.js into a tidy
DataFrame, then computes:

  CF-Ray analysis (Cloudflare):
    - Unique datacenter colo codes per run (CF-Ray format: "<hex>-<COLO>")
    - Per-colo request share (%)
    - Routing consistency index = fraction of requests hitting the top colo

  X-Vercel-Id analysis (Vercel):
    - Unique region codes (format: "<region>::<lambda-id>")
    - Unique lambda instance IDs (proxy for isolate count)
    - Affinity index = fraction of requests to the most-used lambda instance
      (high = warm pool reuse, low = horizontal spread)

  Latency stats per platform for comparison context.

Outputs:
  benchmark/analysis/output/r1-tables/isolate-distribution.tex
  benchmark/analysis/output/figures/fig-isolate-distribution.png
  benchmark/analysis/output/figures/fig-isolate-distribution.pdf

Usage (run from project root):
  python benchmark/analysis/raw-trace-isolate-analyzer.py \\
      --cf-log  benchmark/results/r1-revision/local/cloudflare/burst-headers/burst-cf-headers-run1.log \\
      --vc-log  benchmark/results/r1-revision/local/vercel/burst-headers/burst-vercel-headers-run1.log
"""

import argparse
import json
import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')  # non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR   = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
OUTPUT_DIR   = PROJECT_ROOT / "benchmark" / "analysis" / "output"
TABLES_DIR   = OUTPUT_DIR / "r1-tables"
FIGURES_DIR  = OUTPUT_DIR / "figures"

DEFAULT_CF_LOG = (
    PROJECT_ROOT / "benchmark" / "results" / "r1-revision"
    / "local" / "cloudflare" / "burst-headers" / "burst-cf-headers-run1.log"
)
DEFAULT_VC_LOG = (
    PROJECT_ROOT / "benchmark" / "results" / "r1-revision"
    / "local" / "vercel" / "burst-headers" / "burst-vercel-headers-run1.log"
)

# ---------------------------------------------------------------------------
# Log parser
# ---------------------------------------------------------------------------

# k6 log format: msg="HDR:{\"key\":\"val\",...}" — inner JSON is backslash-escaped
# within the logfmt quoted string. We extract the raw escaped payload and
# unescape it before JSON parsing.
_HDR_RE = re.compile(r'msg="HDR:(\{.+\})" source=console')


def parse_hdr_log(log_path: Path) -> pd.DataFrame:
    """
    Parse k6 log file and extract HDR: NDJSON records.

    Each line looks like (k6 logfmt):
      time="..." level=info msg="HDR:{\"key\":\"val\",...}" source=console

    The JSON payload is backslash-escaped inside the logfmt quoted value,
    so we unescape \\\" → \" before parsing.

    Returns DataFrame with columns:
      ts, vu, iter, lat, ttfb, status, cf_ray, x_vercel_id, region, cold
    """
    records = []
    path = Path(log_path)
    if not path.exists():
        print(f"[isolate-analyzer] WARNING: log not found: {path}", file=sys.stderr)
        return pd.DataFrame()

    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = _HDR_RE.search(line)
            if not m:
                continue
            # Unescape the logfmt-escaped inner JSON string
            # The log file stores the JSON with backslash-escaped inner quotes:
            #   msg="HDR:{\"key\":\"val\"}" source=console
            # A single pass of \" → " is sufficient; do NOT double-unescape.
            raw_json = m.group(1).replace('\\"', '"')
            try:
                rec = json.loads(raw_json)
                records.append(rec)
            except json.JSONDecodeError:
                continue

    if not records:
        print(f"[isolate-analyzer] WARNING: no HDR records in {path.name}", file=sys.stderr)
        return pd.DataFrame()

    df = pd.DataFrame(records)
    df["lat"]    = pd.to_numeric(df.get("lat",    pd.Series()), errors="coerce")
    df["ttfb"]   = pd.to_numeric(df.get("ttfb",   pd.Series()), errors="coerce")
    df["status"] = pd.to_numeric(df.get("status", pd.Series()), errors="coerce")
    return df


# ---------------------------------------------------------------------------
# CF-Ray analysis
# ---------------------------------------------------------------------------

def analyze_cf_ray(df: pd.DataFrame) -> dict:
    """
    Compute CF datacenter (colo) distribution from CF-Ray header values.
    CF-Ray format: "<8hex>-<COLO>"  e.g. "9f810c33-HKG"
    Returns dict with keys: total, colos, top_colo, routing_consistency_pct
    """
    cf_df = df[df["cf_ray"].notna()].copy()
    n_total = len(df)
    n_cf    = len(cf_df)

    if n_cf == 0:
        return {"total": n_total, "cf_sample_n": 0, "colos": {}, "top_colo": None,
                "routing_consistency_pct": None, "unique_colos": 0}

    # Extract colo code = last hyphen-separated component
    cf_df["colo"] = cf_df["cf_ray"].str.extract(r"-([A-Z]{3})$")[0].fillna("UNKNOWN")

    colo_counts = cf_df["colo"].value_counts()
    colo_pct    = (colo_counts / n_cf * 100).round(1)

    top_colo    = colo_counts.index[0]
    routing_con = float(colo_counts.iloc[0] / n_cf * 100)

    return {
        "total":                    n_total,
        "cf_sample_n":              n_cf,
        "unique_colos":             len(colo_counts),
        "colos":                    {k: {"count": int(v), "pct": float(colo_pct[k])}
                                     for k, v in colo_counts.items()},
        "top_colo":                 top_colo,
        "routing_consistency_pct":  round(routing_con, 1),
    }


# ---------------------------------------------------------------------------
# X-Vercel-Id analysis
# ---------------------------------------------------------------------------

def analyze_vercel_id(df: pd.DataFrame) -> dict:
    """
    Compute Vercel region + lambda instance distribution.

    X-Vercel-Id observed format: "hkg1::hkg1::<instance-id>-<timestamp>-<nonce>"
    where <instance-id> is a stable 5-char identifier for the isolate instance,
    e.g. "zmvnk". The full last component is unique per-request (timestamp+nonce);
    the 5-char prefix is the reusable isolate key.

    Returns dict with keys: total, regions, unique_lambdas, affinity_index_pct
    """
    vc_df = df[df["x_vercel_id"].notna()].copy()
    n_total = len(df)
    n_vc    = len(vc_df)

    if n_vc == 0:
        return {"total": n_total, "vc_sample_n": 0, "regions": {}, "unique_lambdas": 0,
                "affinity_index_pct": None}

    # Observed Vercel X-Vercel-Id formats:
    #   Format A (standard): "hkg1::hkg1::zmvnk-<ts>-<nonce>"  → region=hkg1
    #   Format B (fallback): "<ts>-<hash>" (no region prefix)   → region=unknown
    # Normalise: region = first :: component if it looks like a region code
    # (≤8 alphanumeric chars); otherwise "unknown".
    def _extract_region(vid_series: pd.Series) -> pd.Series:
        parts = vid_series.str.split("::")
        first = parts.str[0].fillna("")
        # Region codes are short (3-6 chars), e.g. "hkg1", "iad1"
        is_region = first.str.match(r"^[a-z]{2,4}\d{1}$")
        return first.where(is_region, other="unknown")

    vc_df["region_code"] = _extract_region(vc_df["x_vercel_id"])

    # Instance ID = 5-char alpha prefix of last :: component before the first '-'.
    # Format A: "hkg1::hkg1::zmvnk-1778...-f5b..." → last="zmvnk-...", id="zmvnk" (alpha)
    # Format B: "<ts>-<hash>" (no ::) → last="<ts>-<hash>", first token is numeric ts.
    #   Mark Format-B instances as "fmt_b" since they lack a stable isolate identifier.
    last_component = vc_df["x_vercel_id"].str.split("::").str[-1].fillna("")
    first_token     = last_component.str.split("-").str[0].fillna("")
    is_alpha_id     = first_token.str.match(r"^[a-z]{3,8}$")  # true for "zmvnk", "f8n8t"
    vc_df["instance_id"] = first_token.where(is_alpha_id, other="fmt_b_fallback")

    region_counts  = vc_df["region_code"].value_counts()
    region_pct     = (region_counts / n_vc * 100).round(1)

    instance_counts = vc_df["instance_id"].value_counts()
    unique_lambdas  = len(instance_counts)

    # Affinity index: % of requests handled by the single most-reused isolate instance.
    # High = warm pool concentration (few busy instances).
    # Low  = wide horizontal spread (many instances, each handling few requests).
    top_instance_n  = int(instance_counts.iloc[0])
    affinity_index  = top_instance_n / n_vc * 100

    # Top-5 instance distribution for reporting
    top5 = {k: {"count": int(v), "pct": round(float(instance_counts[k] / n_vc * 100), 2)}
            for k, v in instance_counts.head(5).items()}

    return {
        "total":                n_total,
        "vc_sample_n":          n_vc,
        "unique_regions":       len(region_counts),
        "regions":              {k: {"count": int(v), "pct": float(region_pct[k])}
                                 for k, v in region_counts.items()},
        "unique_lambdas":       unique_lambdas,
        "top_lambda_count":     top_instance_n,
        "affinity_index_pct":   round(affinity_index, 2),
        "top5_instances":       top5,
    }


# ---------------------------------------------------------------------------
# Latency summary
# ---------------------------------------------------------------------------

def latency_summary(df: pd.DataFrame) -> dict:
    """Compute latency percentiles from parsed HDR records."""
    lat = df["lat"].dropna()
    if lat.empty:
        return {}
    return {
        "n":    int(len(lat)),
        "mean": round(float(lat.mean()),  2),
        "p50":  round(float(lat.median()), 2),
        "p95":  round(float(lat.quantile(0.95)), 2),
        "p99":  round(float(lat.quantile(0.99)), 2),
    }


# ---------------------------------------------------------------------------
# LaTeX table
# ---------------------------------------------------------------------------

_LATEX_TEMPLATE = r"""\begin{table}[htbp]
\centering
\small
\caption{Isolate-level routing telemetry from burst test (local client, 1 run,
$\approx$115K CF requests / $\approx$83K Vercel requests).
CF-Ray colo = Cloudflare edge datacenter code;
Vercel region = \texttt{x-vercel-id} region prefix;
\textit{Routing consistency} = \% requests routed to top colo/region;
\textit{Lambda affinity index} = \% requests hitting single most-reused
Vercel lambda instance (proxy for isolate warm-pool concentration).}
\label{tab:isolate-distribution}
\begin{tabular}{lrrrrr}
\toprule
Platform & Samples & \makecell{Unique\\colos/regions} & \makecell{Top\\colo/region} & \makecell{Routing\\consistency (\%)} & \makecell{Lambda\\instances} \\
\midrule
{ROWS}
\bottomrule
\end{tabular}
\\[4pt]\multicolumn{6}{p{0.95\linewidth}}{\footnotesize
\textit{Note:} CF routes all burst traffic through a single PoP (HKG) from
the Vietnamese client — consistent with anycast proximity-based routing.
Vercel distributes across multiple lambda instances per burst run;
affinity index reflects warm-pool reuse across the test window.}
\end{table}
"""


def emit_latex(cf_stats: dict, vc_stats: dict, cf_lat: dict, vc_lat: dict) -> str:
    rows = []

    # Cloudflare row
    cf_top  = cf_stats.get("top_colo", "--")
    cf_uni  = cf_stats.get("unique_colos", 0)
    cf_con  = cf_stats.get("routing_consistency_pct", 0)
    cf_n    = cf_stats.get("cf_sample_n", 0)
    rows.append(
        f"CF Workers & {cf_n:,} & {cf_uni} & {cf_top} & "
        f"{cf_con:.1f}\\% & N/A (anycast) \\\\"
    )

    # Vercel row
    vc_top_region = list(vc_stats.get("regions", {}).keys())[0] if vc_stats.get("regions") else "--"
    vc_uni_reg   = vc_stats.get("unique_regions", 0)
    vc_n         = vc_stats.get("vc_sample_n", 0)
    vc_lambdas   = vc_stats.get("unique_lambdas", 0)
    vc_aff       = vc_stats.get("routing_consistency_pct",
                                vc_stats.get("regions", {}).get(vc_top_region, {}).get("pct", 0))
    rows.append(
        f"Vercel Edge & {vc_n:,} & {vc_uni_reg} & {vc_top_region} & "
        f"{vc_aff:.1f}\\% & {vc_lambdas:,} \\\\"
    )

    return _LATEX_TEMPLATE.replace("{ROWS}", "\n".join(rows))


# ---------------------------------------------------------------------------
# Figure
# ---------------------------------------------------------------------------

def plot_distribution(cf_stats: dict, vc_stats: dict, out_base: Path) -> None:
    """
    Two-panel bar chart:
      Left:  CF-Ray colo distribution (% of requests)
      Right: Vercel X-Vercel-Id region distribution (% of requests)
    """
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))

    # --- CF panel ---
    ax = axes[0]
    colos = cf_stats.get("colos", {})
    if colos:
        labels = list(colos.keys())
        values = [colos[k]["pct"] for k in labels]
        bars = ax.bar(labels, values, color="#F6821F", edgecolor="white", linewidth=0.6)
        ax.set_title("Cloudflare — CF-Ray Datacenter Distribution", fontsize=10, fontweight="bold")
        ax.set_xlabel("CF Datacenter (colo)", fontsize=9)
        ax.set_ylabel("% of Burst Requests", fontsize=9)
        ax.set_ylim(0, 110)
        for bar, val in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width() / 2, val + 1,
                    f"{val:.1f}%", ha="center", va="bottom", fontsize=8)
        n = cf_stats.get("cf_sample_n", 0)
        ax.annotate(f"n = {n:,} requests", xy=(0.98, 0.97), xycoords="axes fraction",
                    ha="right", va="top", fontsize=8, color="#555")
    else:
        ax.text(0.5, 0.5, "No CF-Ray data", ha="center", va="center", transform=ax.transAxes)
        ax.set_title("Cloudflare — CF-Ray Distribution", fontsize=10)

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # --- Vercel panel ---
    ax = axes[1]
    regions = vc_stats.get("regions", {})
    if regions:
        labels = list(regions.keys())
        values = [regions[k]["pct"] for k in labels]
        bars = ax.bar(labels, values, color="#000000", edgecolor="white", linewidth=0.6)
        ax.set_title("Vercel Edge — X-Vercel-Id Region Distribution", fontsize=10, fontweight="bold")
        ax.set_xlabel("Vercel Region", fontsize=9)
        ax.set_ylabel("% of Burst Requests", fontsize=9)
        ax.set_ylim(0, 110)
        for bar, val in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width() / 2, val + 1,
                    f"{val:.1f}%", ha="center", va="bottom", fontsize=8)
        n   = vc_stats.get("vc_sample_n", 0)
        uni = vc_stats.get("unique_lambdas", 0)
        aff = vc_stats.get("affinity_index_pct", 0)
        ax.annotate(
            f"n = {n:,} | {uni} lambda instances\nTop-instance affinity: {aff:.1f}%",
            xy=(0.98, 0.97), xycoords="axes fraction",
            ha="right", va="top", fontsize=8, color="#555",
        )
    else:
        ax.text(0.5, 0.5, "No X-Vercel-Id data", ha="center", va="center", transform=ax.transAxes)
        ax.set_title("Vercel Edge — Region Distribution", fontsize=10)

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    fig.suptitle(
        "Edge Platform Routing Telemetry — Burst Test (local client, VN → provider PoP)",
        fontsize=11, y=1.01,
    )
    fig.tight_layout()

    for ext in ("png", "pdf"):
        out = out_base.with_suffix(f".{ext}")
        fig.savefig(out, dpi=150, bbox_inches="tight")
        print(f"  Saved figure: {out}")

    plt.close(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="P9.2 isolate-level distribution analysis")
    parser.add_argument("--cf-log",  type=Path, default=DEFAULT_CF_LOG,
                        help="Path to CF burst-headers k6 log file")
    parser.add_argument("--vc-log",  type=Path, default=DEFAULT_VC_LOG,
                        help="Path to Vercel burst-headers k6 log file")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    TABLES_DIR.mkdir(parents=True, exist_ok=True)
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)

    print("=== P9.2 Raw Trace Isolate Analyzer ===")

    # Parse logs
    print(f"\nParsing CF log:     {args.cf_log}")
    cf_df = parse_hdr_log(args.cf_log)
    print(f"  Records:          {len(cf_df):,}")

    print(f"\nParsing Vercel log: {args.vc_log}")
    vc_df = parse_hdr_log(args.vc_log)
    print(f"  Records:          {len(vc_df):,}")

    # Analyze
    cf_stats = analyze_cf_ray(cf_df)     if not cf_df.empty else {}
    vc_stats = analyze_vercel_id(vc_df)  if not vc_df.empty else {}
    cf_lat   = latency_summary(cf_df)    if not cf_df.empty else {}
    vc_lat   = latency_summary(vc_df)    if not vc_df.empty else {}

    # Print findings
    print("\n--- CF-Ray Datacenter Distribution ---")
    if cf_stats:
        print(f"  Total requests:       {cf_stats['total']:,}")
        print(f"  Samples w/ CF-Ray:    {cf_stats['cf_sample_n']:,}")
        print(f"  Unique colos:         {cf_stats['unique_colos']}")
        print(f"  Top colo:             {cf_stats['top_colo']}")
        print(f"  Routing consistency:  {cf_stats['routing_consistency_pct']:.1f}%")
        for colo, info in sorted(cf_stats["colos"].items(), key=lambda x: -x[1]["count"]):
            print(f"    {colo}: {info['count']:,} ({info['pct']:.1f}%)")
    print(f"  Latency (from HDR):   avg={cf_lat.get('mean','N/A')}ms  "
          f"p95={cf_lat.get('p95','N/A')}ms  p99={cf_lat.get('p99','N/A')}ms")

    print("\n--- X-Vercel-Id Region + Isolate Distribution ---")
    if vc_stats:
        print(f"  Total requests:       {vc_stats['total']:,}")
        print(f"  Samples w/ VC ID:     {vc_stats['vc_sample_n']:,}")
        print(f"  Unique regions:       {vc_stats['unique_regions']}")
        print(f"  Unique isolate IDs:   {vc_stats['unique_lambdas']:,}")
        print(f"  Isolate affinity idx: {vc_stats['affinity_index_pct']:.2f}%  "
              f"(top isolate handled {vc_stats['top_lambda_count']:,} / {vc_stats['vc_sample_n']:,} req)")
        for region, info in sorted(vc_stats["regions"].items(), key=lambda x: -x[1]["count"]):
            print(f"    Region {region}: {info['count']:,} ({info['pct']:.1f}%)")
        print("  Top-5 isolate instances (by request share):")
        for inst, info in vc_stats.get("top5_instances", {}).items():
            print(f"    {inst}: {info['count']:,} ({info['pct']:.2f}%)")
    print(f"  Latency (from HDR):   avg={vc_lat.get('mean','N/A')}ms  "
          f"p95={vc_lat.get('p95','N/A')}ms  p99={vc_lat.get('p99','N/A')}ms")

    # Emit LaTeX
    if cf_stats or vc_stats:
        tex = emit_latex(cf_stats, vc_stats, cf_lat, vc_lat)
        tex_path = TABLES_DIR / "isolate-distribution.tex"
        tex_path.write_text(tex, encoding="utf-8")
        print(f"\nSaved LaTeX: {tex_path}")

    # Plot figure
    fig_base = FIGURES_DIR / "fig-isolate-distribution"
    if cf_stats or vc_stats:
        plot_distribution(cf_stats, vc_stats, fig_base)

    print("\nDone.")


if __name__ == "__main__":
    main()
