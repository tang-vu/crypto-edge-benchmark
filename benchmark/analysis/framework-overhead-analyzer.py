"""
Framework overhead quantification for R3.4 (Springer R1 revision).

Computes per-platform, per-region decomposition of http_req_duration into:
  - http_req_waiting  (TTFB: network + server handler time as seen by client)
  - http_req_sending  (request upload time)
  - http_req_receiving (response download time)

The 'framework overhead delta' is derived by comparing (http_req_waiting)
between CF and Vercel after controlling for network distance:
  - Within same client region, CF and Vercel face identical network paths to
    the edge PoP; differences in http_req_waiting reveal handler dispatch
    overhead, not geography.
  - http_req_duration - http_req_waiting = client-framing overhead (send+recv)

Approach:
  1. Ingest all r1-revision warm-mock runs (mock isolates compute from live API)
  2. Per (client, platform): compute avg of http_req_waiting, http_req_duration,
     http_req_sending, http_req_receiving across runs
  3. For each client region: delta_wait = CF_wait - Vercel_wait
     delta_duration = CF_duration - Vercel_duration
     These deltas capture (CF_network - Vercel_network) + (CF_handler - Vercel_handler)
  4. The network component is symmetric by geo-proximity assumption within region.
     The vercel_framework_overhead = vercel_wait relative to CF_wait
     (CF Workers: minimal dispatch; Vercel: Next.js route matching + CORS middleware)

Outputs:
  - benchmark/analysis/output/framework-overhead.csv
  - benchmark/analysis/output/r1-tables/framework-overhead.tex

Usage:
  python benchmark/analysis/framework-overhead-analyzer.py
  (run from project root)
"""

import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
R1_DIR = PROJECT_ROOT / "benchmark" / "results" / "r1-revision"
OUTPUT_DIR = PROJECT_ROOT / "benchmark" / "analysis" / "output"
TABLES_DIR = OUTPUT_DIR / "r1-tables"

OUTPUT_CSV = OUTPUT_DIR / "framework-overhead.csv"
OUTPUT_TEX = TABLES_DIR / "framework-overhead.tex"

# Regions included in analysis
REGION_DISPLAY = {
    "local": "VN (local)",
    "us-east-1": "US-East-1",
    "eu-west-1": "EU-West-1",
    "ap-southeast-1": "AP-SE-1",
}


# ---------------------------------------------------------------------------
# Ingest helpers
# ---------------------------------------------------------------------------

def _extract_timing_metrics(data: dict) -> dict | None:
    """
    Extract http_req_duration, http_req_waiting, http_req_sending,
    http_req_receiving avg values from a k6 JSON summary.
    Returns None if required fields are missing.
    """
    k6 = data.get("metrics", {})

    def _avg(key: str) -> float | None:
        return k6.get(key, {}).get("values", {}).get("avg")

    dur = _avg("http_req_duration")
    wait = _avg("http_req_waiting")
    send = _avg("http_req_sending")
    recv = _avg("http_req_receiving")

    if dur is None or wait is None:
        return None

    return {
        "duration_avg": dur,
        "waiting_avg": wait,
        "sending_avg": send or 0.0,
        "receiving_avg": recv or 0.0,
    }


def ingest_warm_mock_runs(base_dir: Path) -> pd.DataFrame:
    """
    Walk r1-revision directory and collect all warm/mock run metrics.
    Returns DataFrame with per-file timing breakdown.
    """
    records = []

    for json_path in sorted(base_dir.rglob("*.json")):
        # Skip .summary.json sidecars
        if json_path.name.endswith(".summary.json"):
            continue

        # Filter warm mock only
        name_lower = json_path.name.lower()
        if "warm" not in name_lower:
            continue
        if "-mock-" not in name_lower:
            continue

        # Extract client / platform from directory structure
        # Expected: {base_dir}/{client}/{platform}/{scenario}/file.json
        try:
            rel = json_path.relative_to(base_dir)
            parts = rel.parts
            if len(parts) < 4:
                continue
            client = parts[0]
            platform = parts[1]
        except Exception:
            continue

        if platform not in ("cloudflare", "vercel"):
            continue
        if client not in REGION_DISPLAY:
            continue

        try:
            with open(json_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as e:
            print(f"Warning: skipping {json_path.name}: {e}", file=sys.stderr)
            continue

        metrics = _extract_timing_metrics(data)
        if metrics is None:
            print(f"Warning: no timing metrics in {json_path.name}", file=sys.stderr)
            continue

        # Run number
        run_match = re.search(r"-run(\d+)-", json_path.name)
        run_num = int(run_match.group(1)) if run_match else 0

        records.append({
            "client": client,
            "platform": platform,
            "run_num": run_num,
            "file": json_path.name,
            **metrics,
        })

    if not records:
        raise RuntimeError(f"No warm-mock JSON files found under {base_dir}")

    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def compute_overhead_table(df: pd.DataFrame) -> pd.DataFrame:
    """
    Group by (client, platform), average across runs, then compute:
      - client_avg_ms   = mean http_req_duration across runs
      - server_avg_ms   = mean http_req_waiting across runs (proxy for server time)
      - client_framing  = client_avg - server_avg (send + recv overhead)
      - wait_ratio      = server_avg / client_avg  (server fraction of round-trip)

    Then per client, compute:
      - delta_duration   = CF_duration - Vercel_duration  (positive = CF slower)
      - delta_wait       = CF_wait - Vercel_wait
      - framework_delta  = difference in (duration - wait) between platforms
        i.e., extra non-network overhead in Vercel vs CF
        = (Vercel_duration - Vercel_wait) - (CF_duration - CF_wait)
    """
    # Per-platform-region mean across runs
    grouped = (
        df.groupby(["client", "platform"])
        .agg(
            n_runs=("run_num", "count"),
            client_avg_ms=("duration_avg", "mean"),
            server_avg_ms=("waiting_avg", "mean"),
            sending_avg_ms=("sending_avg", "mean"),
            receiving_avg_ms=("receiving_avg", "mean"),
        )
        .reset_index()
    )

    grouped["client_framing_ms"] = (
        grouped["sending_avg_ms"] + grouped["receiving_avg_ms"]
    )
    grouped["overhead_non_wait_ms"] = (
        grouped["client_avg_ms"] - grouped["server_avg_ms"]
    )
    grouped["wait_ratio_pct"] = (
        grouped["server_avg_ms"] / grouped["client_avg_ms"] * 100.0
    ).round(1)

    # Per-region cross-platform comparison
    rows = []
    for client, grp in grouped.groupby("client"):
        cf_row = grp[grp["platform"] == "cloudflare"]
        vc_row = grp[grp["platform"] == "vercel"]

        if cf_row.empty or vc_row.empty:
            # Only one platform present for this region
            for _, r in grp.iterrows():
                rows.append({
                    "region": client,
                    "region_display": REGION_DISPLAY.get(client, client),
                    "platform": r["platform"],
                    "n_runs": int(r["n_runs"]),
                    "client_avg_ms": round(r["client_avg_ms"], 2),
                    "server_avg_ms": round(r["server_avg_ms"], 2),
                    "overhead_non_wait_ms": round(r["overhead_non_wait_ms"], 3),
                    "wait_ratio_pct": round(r["wait_ratio_pct"], 1),
                    "delta_duration_ms": None,
                    "delta_wait_ms": None,
                    "framework_delta_ms": None,
                    "delta_ratio": None,
                })
            continue

        cf = cf_row.iloc[0]
        vc = vc_row.iloc[0]

        # delta > 0 means CF is slower (numerically larger)
        delta_dur = cf["client_avg_ms"] - vc["client_avg_ms"]
        delta_wait = cf["server_avg_ms"] - vc["server_avg_ms"]

        # framework_delta: extra non-network framing in Vercel vs CF
        # Positive means Vercel adds MORE non-wait overhead than CF
        framework_delta = (
            vc["overhead_non_wait_ms"] - cf["overhead_non_wait_ms"]
        )

        # delta_ratio: (CF_wait / Vercel_wait) - gives relative server overhead ratio
        delta_ratio = (
            cf["server_avg_ms"] / vc["server_avg_ms"]
            if vc["server_avg_ms"] > 0 else None
        )

        for _, r in grp.iterrows():
            rows.append({
                "region": client,
                "region_display": REGION_DISPLAY.get(client, client),
                "platform": r["platform"],
                "n_runs": int(r["n_runs"]),
                "client_avg_ms": round(r["client_avg_ms"], 2),
                "server_avg_ms": round(r["server_avg_ms"], 2),
                "overhead_non_wait_ms": round(r["overhead_non_wait_ms"], 3),
                "wait_ratio_pct": round(r["wait_ratio_pct"], 1),
                "delta_duration_ms": round(delta_dur, 2),
                "delta_wait_ms": round(delta_wait, 2),
                "framework_delta_ms": round(framework_delta, 3),
                "delta_ratio": round(delta_ratio, 2) if delta_ratio else None,
            })

    result = pd.DataFrame(rows)
    # Sort by region then platform for readability
    region_order = {"local": 0, "us-east-1": 1, "eu-west-1": 2, "ap-southeast-1": 3}
    result["_sort_key"] = result["region"].map(region_order).fillna(99)
    result = result.sort_values(["_sort_key", "platform"]).drop(columns=["_sort_key"])
    return result.reset_index(drop=True)


# ---------------------------------------------------------------------------
# LaTeX table emitter
# ---------------------------------------------------------------------------

LATEX_TEMPLATE = r"""\begin{table}[htbp]
\centering
\small
\caption{Platform latency decomposition: client-observed \texttt{http\_req\_duration} vs.\
server-side TTFB (\texttt{http\_req\_waiting}) per region (warm mock, $n$=3 runs each).
$\Delta_{\text{wait}}$ = CF$_{\text{wait}}$ $-$ Vercel$_{\text{wait}}$; positive means
CF spends more time in server-handler. Framework overhead delta = extra
(duration$-$wait) in Vercel vs.\ CF, capturing route-dispatch and CORS middleware cost.
Values in ms.}
\label{tab:framework-overhead}
\begin{tabular}{llrrrrc}
\toprule
Region & Platform & \makecell{Total\\avg (ms)} & \makecell{TTFB\\(ms)} & \makecell{Framing\\(ms)} & \makecell{TTFB\\ratio (\%)} & \makecell{$\Delta_{\text{wait}}$\\(ms)} \\
\midrule
{ROWS}
\bottomrule
\end{tabular}
\\[2pt]\multicolumn{7}{p{0.95\linewidth}}{\footnotesize
\textit{TTFB} = \texttt{http\_req\_waiting} (server-side handler latency proxy).
\textit{Framing} = \texttt{http\_req\_sending} + \texttt{http\_req\_receiving} (client-side).
$\Delta_{\text{wait}}$ reported once per region pair (CF $-$ Vercel); positive = CF slower.
\textit{Framework overhead delta} summarised in Table notes; full data in supplemental CSV.}
\end{table}
"""

_BOLD_DELTA_THRESHOLD_MS = 5.0  # highlight deltas > 5 ms


def emit_latex_table(df: pd.DataFrame) -> str:
    """Build LaTeX table rows from overhead DataFrame."""
    rows_tex = []
    prev_region = None

    for _, row in df.iterrows():
        region_str = row["region_display"]
        platform_str = "CF Workers" if row["platform"] == "cloudflare" else "Vercel Edge"
        total_str = f"{row['client_avg_ms']:.1f}"
        ttfb_str = f"{row['server_avg_ms']:.1f}"
        framing_str = f"{row['overhead_non_wait_ms']:.2f}"
        ratio_str = f"{row['wait_ratio_pct']:.0f}\\%"

        # Delta only shown once per region (same value for both rows)
        if row["delta_wait_ms"] is not None:
            delta = row["delta_wait_ms"]
            delta_str = f"{delta:+.1f}"
            if abs(delta) >= _BOLD_DELTA_THRESHOLD_MS:
                delta_str = f"\\textbf{{{delta_str}}}"
        else:
            delta_str = "--"

        # Add horizontal separator between regions
        if prev_region is not None and region_str != prev_region:
            rows_tex.append("\\midrule")

        rows_tex.append(
            f"{region_str} & {platform_str} & {total_str} & "
            f"{ttfb_str} & {framing_str} & {ratio_str} & {delta_str} \\\\"
        )
        prev_region = region_str

    return LATEX_TEMPLATE.replace("{ROWS}", "\n".join(rows_tex))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=== Framework Overhead Analyzer (R3.4) ===")

    # Ensure output dirs exist
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    TABLES_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Ingest
    print(f"Ingesting warm-mock runs from: {R1_DIR}")
    df_raw = ingest_warm_mock_runs(R1_DIR)
    print(f"  Loaded {len(df_raw)} run files across "
          f"{df_raw['client'].nunique()} regions × "
          f"{df_raw['platform'].nunique()} platforms")

    # Show per-group counts
    counts = df_raw.groupby(["client", "platform"]).size().reset_index(name="count")
    print("\nRun counts per (region, platform):")
    for _, r in counts.iterrows():
        print(f"  {r['client']:20s}  {r['platform']:12s}  n={r['count']}")

    # 2. Compute overhead table
    overhead_df = compute_overhead_table(df_raw)

    # 3. Save CSV
    overhead_df.to_csv(OUTPUT_CSV, index=False)
    print(f"\nSaved CSV: {OUTPUT_CSV}")

    # 4. Print summary statistics
    print("\n=== Overhead Summary ===")
    for region in REGION_DISPLAY:
        region_rows = overhead_df[overhead_df["region"] == region]
        if region_rows.empty:
            continue
        cf_row = region_rows[region_rows["platform"] == "cloudflare"]
        vc_row = region_rows[region_rows["platform"] == "vercel"]

        region_disp = REGION_DISPLAY[region]
        if not cf_row.empty:
            r = cf_row.iloc[0]
            print(f"  {region_disp:20s} CF:     total={r['client_avg_ms']:.1f}ms  "
                  f"TTFB={r['server_avg_ms']:.1f}ms  "
                  f"framing={r['overhead_non_wait_ms']:.2f}ms")
        if not vc_row.empty:
            r = vc_row.iloc[0]
            delta_w = r["delta_wait_ms"]
            delta_str = f"  delta_wait={delta_w:+.1f}ms" if delta_w is not None else ""
            print(f"  {region_disp:20s} Vercel: total={r['client_avg_ms']:.1f}ms  "
                  f"TTFB={r['server_avg_ms']:.1f}ms  "
                  f"framing={r['overhead_non_wait_ms']:.2f}ms"
                  f"{delta_str}")

    # Framework overhead delta (cross-region average)
    has_both = overhead_df[
        overhead_df["delta_wait_ms"].notna() & (overhead_df["platform"] == "cloudflare")
    ]
    if not has_both.empty:
        avg_delta = has_both["delta_wait_ms"].mean()
        fw_delta = overhead_df[
            overhead_df["framework_delta_ms"].notna() & (overhead_df["platform"] == "vercel")
        ]["framework_delta_ms"].mean()
        print(f"\nCross-region mean delta_wait (CF - Vercel): {avg_delta:+.2f} ms")
        print(f"Cross-region mean framework_delta (Vercel extra framing): {fw_delta:+.3f} ms")

    # 5. Emit LaTeX
    tex_content = emit_latex_table(overhead_df)
    OUTPUT_TEX.write_text(tex_content, encoding="utf-8")
    print(f"\nSaved LaTeX table: {OUTPUT_TEX}")
    print("\nDone.")


if __name__ == "__main__":
    main()
