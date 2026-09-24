"""
CSV per-request trace ingest module for r1-revision k6 --out csv= files.

Each k6 --out csv file contains per-request rows for every metric. This module
filters to http_req_duration rows (primary latency metric) and returns a tidy
DataFrame suitable for TRUE per-request Cohen's d, Mann-Whitney U, and
per-stage burst breakdown.

AGGREGATION: per-request (n = tens of thousands per group). This is the
TRUE per-request level replacing the synthetic log-normal reconstruction used
in Phase 4 (d_request_synth).

Directory consumed:
  benchmark/results/r1-revision/{client}/{platform}/{scenario}/
    {scenario}-{platform}-paid-{mode}-run{N}-{ISO_TS}.csv

Burst stage boundaries (seconds elapsed from run start):
  Stage 1 ramp_up:   0  – 30 s
  Stage 2 spike:    30  – 90 s
  Stage 3 peak_hold: 90  – 120 s
  Stage 4 ramp_down: 120 – 180 s
  Stage 5 cooldown:  180 – 210 s
"""

import re
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BURST_STAGES = [
    (0,   30,  "ramp_up",    "0→10 VU ramp-up"),
    (30,  90,  "spike",      "10→100 VU spike"),
    (90,  120, "peak_hold",  "100→200 VU peak"),
    (120, 180, "ramp_down",  "200→50 VU ramp-down"),
    (180, 210, "cooldown",   "50→0 VU cooldown"),
]

# Columns retained in output — minimised for memory efficiency
_OUT_COLS = [
    "client", "platform", "scenario", "mode", "run_num",
    "latency_ms", "timestamp_unix", "elapsed_s", "stage",
    "status_code",
]

# Expected CSV column layout from k6 --out csv
_K6_CSV_COLS = [
    "metric_name", "timestamp", "metric_value",
    "check", "error", "error_code", "expected_response",
    "group", "method", "name", "proto", "scenario", "service",
    "status", "subproto", "tls_version", "url", "extra_tags",
]


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_path_metadata(csv_path: Path) -> dict:
    """
    Extract (client, platform, scenario, mode, run_num) from directory path and
    filename. Path structure:
      …/r1-revision/{client}/{platform}/{scenario}/{filename}.csv
    Filename pattern: {scenario}-{platform}-paid-{mode}-run{N}-{TS}.csv
    """
    parts = csv_path.parts
    # Find r1-revision anchor
    try:
        idx = next(i for i, p in enumerate(parts) if p == "r1-revision")
    except StopIteration:
        idx = -4  # fallback: use last 4 path components

    client   = parts[idx + 1] if idx + 1 < len(parts) else "unknown"
    platform = parts[idx + 2] if idx + 2 < len(parts) else "unknown"
    scenario = parts[idx + 3] if idx + 3 < len(parts) else "unknown"

    # Parse filename
    name = csv_path.stem  # strip .csv
    mode_match = re.search(r"-(mock|live)-", name)
    mode = mode_match.group(1) if mode_match else "unknown"
    run_match = re.search(r"-run(\d+)-", name)
    run_num = int(run_match.group(1)) if run_match else 0

    return {
        "client":   client,
        "platform": platform,
        "scenario": scenario,
        "mode":     mode,
        "run_num":  run_num,
    }


def _assign_burst_stage(elapsed_s: pd.Series) -> pd.Series:
    """Map elapsed seconds since run start to stage label."""
    stage = pd.Series("other", index=elapsed_s.index, dtype="object")
    for t_start, t_end, label, _ in BURST_STAGES:
        mask = (elapsed_s >= t_start) & (elapsed_s < t_end)
        stage[mask] = label
    return stage


# ---------------------------------------------------------------------------
# Main ingest function
# ---------------------------------------------------------------------------

def ingest_csv_traces(
    base_dir: str,
    scenario_filter: Optional[str] = None,
    low_memory_mode: bool = False,
) -> pd.DataFrame:
    """
    Walk r1-revision directory tree, read all *.csv trace files, filter to
    http_req_duration rows, assign per-stage labels for burst scenario, and
    return a tidy DataFrame.

    Args:
        base_dir:          Root path (e.g. benchmark/results/r1-revision).
        scenario_filter:   Optional — 'burst', 'cold', 'warm'. None = all.
        low_memory_mode:   If True, sample 20 % of rows per file to reduce RAM.

    Returns:
        DataFrame with columns in _OUT_COLS.
    """
    base = Path(base_dir)
    pattern = "**/*.csv"
    all_csv = sorted(base.glob(pattern))

    if scenario_filter:
        all_csv = [p for p in all_csv if f"/{scenario_filter}/" in p.as_posix()
                   or f"\\{scenario_filter}\\" in str(p)]

    frames: List[pd.DataFrame] = []

    for csv_path in all_csv:
        meta = _parse_path_metadata(csv_path)

        try:
            # Read with low_memory=False to avoid mixed-type column warnings
            raw = pd.read_csv(
                csv_path,
                dtype={"metric_name": str, "timestamp": float,
                       "metric_value": float, "status": str},
                usecols=lambda c: c in {
                    "metric_name", "timestamp", "metric_value", "status"
                },
                low_memory=False,
            )
        except Exception as exc:
            print(f"[ingest-csv-traces] WARNING: skip {csv_path.name}: {exc}")
            continue

        # Filter to per-request duration rows only
        dur = raw[raw["metric_name"] == "http_req_duration"].copy()
        if dur.empty:
            continue

        # Optional sampling for very large files
        if low_memory_mode and len(dur) > 5000:
            dur = dur.sample(frac=0.20, random_state=42)

        # Compute elapsed seconds relative to run start
        t_min = dur["timestamp"].min()
        dur["elapsed_s"] = dur["timestamp"] - t_min

        # Assign burst stage (only meaningful for burst scenario)
        if meta["scenario"] == "burst":
            dur["stage"] = _assign_burst_stage(dur["elapsed_s"])
        else:
            dur["stage"] = meta["scenario"]

        # Build output frame
        out = pd.DataFrame({
            "client":         meta["client"],
            "platform":       meta["platform"],
            "scenario":       meta["scenario"],
            "mode":           meta["mode"],
            "run_num":        meta["run_num"],
            "latency_ms":     dur["metric_value"].values,
            "timestamp_unix": dur["timestamp"].values,
            "elapsed_s":      dur["elapsed_s"].values,
            "stage":          dur["stage"].values,
            "status_code":    dur["status"].values if "status" in dur.columns else None,
        })

        frames.append(out)

    if not frames:
        return pd.DataFrame(columns=_OUT_COLS)

    result = pd.concat(frames, ignore_index=True)
    return result


# ---------------------------------------------------------------------------
# Cohen's d helpers
# ---------------------------------------------------------------------------

def cohens_d_true(g1: np.ndarray, g2: np.ndarray) -> float:
    """Cohen's d using pooled SD. Positive = g2 > g1."""
    g1 = np.asarray(g1, dtype=float)
    g2 = np.asarray(g2, dtype=float)
    n1, n2 = len(g1), len(g2)
    if n1 < 2 or n2 < 2:
        return float("nan")
    var1 = np.var(g1, ddof=1)
    var2 = np.var(g2, ddof=1)
    pooled_std = np.sqrt(((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2))
    if pooled_std == 0.0:
        return 0.0
    return float((np.mean(g2) - np.mean(g1)) / pooled_std)


def interpret_d(d: float) -> str:
    abs_d = abs(d)
    if np.isnan(abs_d):
        return "N/A"
    if abs_d < 0.2:
        return "negligible"
    if abs_d < 0.5:
        return "small"
    if abs_d < 0.8:
        return "medium"
    return "large"
