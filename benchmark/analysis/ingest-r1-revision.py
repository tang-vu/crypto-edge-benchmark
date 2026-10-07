"""
Ingest module for r1-revision hierarchical benchmark results.

Directory structure consumed:
  benchmark/results/r1-revision/{client}/{platform}/{scenario}/
      {scenario}-{platform}-paid-{mode}-run{N}-{ISO_TS}.json

Clients: local, us-east-1, eu-west-1, ap-southeast-1
Platforms: cloudflare, vercel
Scenarios: warm, burst, cold
Modes: mock, live (us-east-1 has only mock due to Binance geo-block)

AGGREGATION LEVEL: Each record in the returned DataFrame represents one
benchmark run (one JSON file). Statistics within each record are per-run
aggregates (avg, p50, p90, p95, p99) exported by k6.
No per-request rawLatencies are present in these files (rawLatencies=[]).
"""

import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import numpy as np


# Known clients / aliases for display
CLIENT_DISPLAY = {
    "local": "VN (local)",
    "us-east-1": "US-East-1",
    "eu-west-1": "EU-West-1",
    "ap-southeast-1": "AP-SE-1",
}

# us-east-1 has no live data — Binance geo-blocks the region (F1 constraint)
US_EAST_LIVE_NOTE = "us-east-1 has mock-only data; Binance geo-blocks live API in this region."


def _extract_metrics_from_file(data: Dict) -> Dict:
    """
    Extract k6 summary metrics from a parsed JSON result file.

    Returns dict with: avg, min, max, med (p50), p90, p95, p99,
    total_requests, throughput, error_rate.
    """
    metrics_out = {}
    k6 = data.get("metrics", {})

    dur = k6.get("http_req_duration", {}).get("values", {})
    metrics_out["avg"] = dur.get("avg")
    metrics_out["min"] = dur.get("min")
    metrics_out["max"] = dur.get("max")
    metrics_out["p50"] = dur.get("med") or dur.get("p(50)")
    metrics_out["p90"] = dur.get("p(90)")
    metrics_out["p95"] = dur.get("p(95)")
    metrics_out["p99"] = dur.get("p(99)")

    reqs = k6.get("http_reqs", {}).get("values", {})
    metrics_out["total_requests"] = reqs.get("count")
    metrics_out["throughput"] = reqs.get("rate")

    failed = k6.get("http_req_failed", {}).get("values", {})
    metrics_out["error_rate"] = (failed.get("rate") or 0.0) * 100.0

    return metrics_out


def _parse_filename(filename: str) -> Dict:
    """
    Parse run metadata from filename pattern:
      {scenario}-{platform}-paid-{mode}-run{N}-{ISO_TS}.json

    Returns dict with: scenario_hint, platform_hint, mode, run_num.
    """
    name = Path(filename).stem  # strip .json
    parsed = {}

    # mode: mock or live
    if "-mock-" in name:
        parsed["mode"] = "mock"
    elif "-live-" in name:
        parsed["mode"] = "live"
    else:
        parsed["mode"] = "unknown"

    # run number
    run_match = re.search(r"-run(\d+)-", name)
    parsed["run_num"] = int(run_match.group(1)) if run_match else None

    return parsed


def ingest_revision_results(base_dir: str) -> pd.DataFrame:
    """
    Walk r1-revision hierarchical directory and return a flat DataFrame.

    Each row = one benchmark run file with columns:
        client, client_display, platform, scenario, mode, run_num,
        file_path, avg, min, max, p50, p90, p95, p99,
        total_requests, throughput, error_rate,
        test_duration_ms, timestamp

    Skips .summary.json files and non-JSON files.
    """
    records: List[Dict] = []
    base_path = Path(base_dir)

    if not base_path.exists():
        raise FileNotFoundError(f"r1-revision directory not found: {base_dir}")

    for json_path in sorted(base_path.rglob("*.json")):
        # Skip summary files
        if json_path.name.endswith(".summary.json"):
            continue

        # Derive client, platform, scenario from path components
        # Expected: base_dir/{client}/{platform}/{scenario}/filename.json
        try:
            rel = json_path.relative_to(base_path)
            parts = rel.parts
            if len(parts) < 4:
                continue  # unexpected structure
            client = parts[0]
            platform = parts[1]
            scenario = parts[2]
        except Exception:
            continue

        # Validate known values
        if platform not in ("cloudflare", "vercel"):
            continue
        if scenario not in ("warm", "burst", "cold"):
            continue

        try:
            with open(json_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as e:
            print(f"Warning: Failed to load {json_path}: {e}")
            continue

        file_meta = _parse_filename(json_path.name)
        metrics = _extract_metrics_from_file(data)

        # Test metadata from embedded testMetadata block (if present)
        test_meta = data.get("testMetadata", {})
        state = data.get("state", {})

        record = {
            "client": client,
            "client_display": CLIENT_DISPLAY.get(client, client),
            "platform": platform,
            "scenario": scenario,
            "mode": file_meta.get("mode", "unknown"),
            "run_num": file_meta.get("run_num"),
            "file_path": str(json_path),
            "test_duration_ms": state.get("testRunDurationMs"),
            "timestamp": test_meta.get("timestamp", ""),
            **metrics,
        }
        records.append(record)

    df = pd.DataFrame(records)
    if df.empty:
        return df

    # Enforce types
    numeric_cols = ["avg", "min", "max", "p50", "p90", "p95", "p99",
                    "total_requests", "throughput", "error_rate", "test_duration_ms"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["run_num"] = pd.to_numeric(df["run_num"], errors="coerce").astype("Int64")

    return df.sort_values(["scenario", "client", "platform", "mode", "run_num"]).reset_index(drop=True)


def summarize_revision_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    Group r1-revision data by (scenario, client, platform, mode) and
    compute per-group statistics across runs.

    AGGREGATION LEVEL: n = number of runs per group (typically 3).
    Returns per-group mean, std, CI bounds for avg and p95 latency.

    This is the 'n=runs' level that matches the original Jan-2026 analysis.
    """
    if df.empty:
        return pd.DataFrame()

    rows = []
    groups = df.groupby(["scenario", "client", "platform", "mode"])

    for (scenario, client, platform, mode), grp in groups:
        for metric in ["avg", "p50", "p95", "p99", "throughput", "error_rate"]:
            vals = grp[metric].dropna().values
            n = len(vals)
            if n == 0:
                continue

            mean_val = float(np.mean(vals))
            std_val = float(np.std(vals, ddof=1)) if n > 1 else 0.0

            rows.append({
                "scenario": scenario,
                "client": client,
                "client_display": CLIENT_DISPLAY.get(client, client),
                "platform": platform,
                "mode": mode,
                "metric": metric,
                "n_runs": n,
                "mean": mean_val,
                "std": std_val,
                "min": float(np.min(vals)),
                "max": float(np.max(vals)),
            })

    return pd.DataFrame(rows)


def get_us_east_caveat() -> str:
    """Return caveat string for US-East-1 mock-only limitation."""
    return US_EAST_LIVE_NOTE


if __name__ == "__main__":
    import sys
    base = sys.argv[1] if len(sys.argv) > 1 else "benchmark/results/r1-revision"
    df = ingest_revision_results(base)
    print(f"Loaded {len(df)} run files")
    if df.empty:
        sys.exit(
            f"Error: no eligible run files found in {base!r}. "
            "Use the input root containing "
            "{client}/{cloudflare|vercel}/{warm|burst|cold}/*.json "
            "(excluding *.summary.json), and check any load warnings above."
        )
    print(df.groupby(["scenario", "client", "platform", "mode"]).size().to_string())
    print("\nCaveat:", get_us_east_caveat())
