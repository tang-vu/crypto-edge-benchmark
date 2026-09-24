"""
Cold-start n=5 cross-region analysis for Phase 9.1.

Loads cold-start JSON files from r1-revision/{region}/{platform}/cold/,
uses up to 5 mock runs per cell (ascending by timestamp), computes
mean + bootstrap 95% CI, outputs CSV and updated LaTeX table.

Outputs:
  benchmark/analysis/output/r1-cold-stats-n5.csv
  benchmark/analysis/output/r1-tables/cold.tex  (updated label: n=5)
"""

import json
import glob
import os
import csv
import numpy as np

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT  = os.path.dirname(os.path.dirname(SCRIPT_DIR))
BASE_DIR   = os.path.join(REPO_ROOT, "benchmark", "results", "r1-revision")
OUT_DIR    = os.path.join(REPO_ROOT, "benchmark", "analysis", "output")
TABLES_DIR = os.path.join(OUT_DIR, "r1-tables")
os.makedirs(TABLES_DIR, exist_ok=True)

CLIENTS    = ["local", "us-east-1", "eu-west-1", "ap-southeast-1"]
PLATFORMS  = ["cloudflare", "vercel"]
N_LIMIT    = 5   # use at most 5 mock runs per cell

CLIENT_DISPLAY = {
    "local":          "VN (local)",
    "us-east-1":      "US-East-1",
    "eu-west-1":      "EU-West-1",
    "ap-southeast-1": "AP-SE-1",
}
PLAT_DISPLAY = {"cloudflare": "CF Workers", "vercel": "Vercel Edge"}


def load_avg(filepath):
    """Return http_req_duration avg from k6 JSON summary."""
    try:
        with open(filepath) as f:
            d = json.load(f)
        m = d.get("metrics", {}).get("http_req_duration", {})
        v = m.get("values", {})
        avg = v.get("avg")
        return float(avg) if avg is not None else None
    except Exception as e:
        print(f"  WARNING: failed to parse {filepath}: {e}")
        return None


def bootstrap_ci(values, n_boot=10000, ci=0.95, seed=42):
    """Bootstrap percentile CI for mean."""
    rng = np.random.default_rng(seed)
    arr = np.array(values, dtype=float)
    if len(arr) < 2:
        return arr[0], arr[0]
    boot = np.array([np.mean(rng.choice(arr, size=len(arr), replace=True))
                     for _ in range(n_boot)])
    lo = np.percentile(boot, (1 - ci) / 2 * 100)
    hi = np.percentile(boot, (1 + ci) / 2 * 100)
    return lo, hi


def collect_cold_runs(client, platform, mode="mock", n_limit=N_LIMIT):
    """
    Collect up to n_limit cold-start run JSON files, sorted by timestamp (ascending).
    Returns list of avg latency values.
    """
    pattern = os.path.join(
        BASE_DIR, client, platform, "cold",
        f"cold-{platform}-paid-{mode}-run*.json"
    )
    files = sorted(glob.glob(pattern))   # lexicographic = timestamp order
    files = files[:n_limit]
    avgs = []
    for fp in files:
        val = load_avg(fp)
        if val is not None:
            avgs.append(val)
    return avgs


def main():
    rows = []

    for client in CLIENTS:
        for platform in PLATFORMS:
            avgs = collect_cold_runs(client, platform, mode="mock", n_limit=N_LIMIT)
            if not avgs:
                print(f"  SKIP (no data): {client}/{platform}/cold/mock")
                continue
            n = len(avgs)
            mean = np.mean(avgs)
            ci_lo, ci_hi = bootstrap_ci(avgs)
            rows.append({
                "client":    client,
                "platform":  platform,
                "mode":      "mock",
                "n_runs":    n,
                "mean_ms":   round(mean, 1),
                "ci95_low":  round(ci_lo, 1),
                "ci95_high": round(ci_hi, 1),
            })
            print(f"  {client}/{platform}/mock n={n}: mean={mean:.1f}ms CI=[{ci_lo:.1f},{ci_hi:.1f}]")

        # live runs for non-US clients
        if client != "us-east-1":
            for platform in PLATFORMS:
                avgs = collect_cold_runs(client, platform, mode="live", n_limit=N_LIMIT)
                if not avgs:
                    continue
                n = len(avgs)
                mean = np.mean(avgs)
                ci_lo, ci_hi = bootstrap_ci(avgs)
                rows.append({
                    "client":    client,
                    "platform":  platform,
                    "mode":      "live",
                    "n_runs":    n,
                    "mean_ms":   round(mean, 1),
                    "ci95_low":  round(ci_lo, 1),
                    "ci95_high": round(ci_hi, 1),
                })
                print(f"  {client}/{platform}/live n={n}: mean={mean:.1f}ms CI=[{ci_lo:.1f},{ci_hi:.1f}]")

    # Write CSV
    csv_path = os.path.join(OUT_DIR, "r1-cold-stats-n5.csv")
    fieldnames = ["client", "platform", "mode", "n_runs", "mean_ms", "ci95_low", "ci95_high"]
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            w.writerow(row)
    print(f"\nWrote: {csv_path}")

    # Write LaTeX table
    tex_path = os.path.join(TABLES_DIR, "cold.tex")
    _write_latex_table(rows, tex_path)
    print(f"Wrote: {tex_path}")


def _write_latex_table(rows, tex_path):
    # Sort: region order, platform order, mode
    region_order = ["local", "eu-west-1", "us-east-1", "ap-southeast-1"]
    plat_order   = ["cloudflare", "vercel"]
    mode_order   = ["mock", "live"]

    def sort_key(r):
        ri = region_order.index(r["client"]) if r["client"] in region_order else 99
        pi = plat_order.index(r["platform"]) if r["platform"] in plat_order else 99
        mi = mode_order.index(r["mode"]) if r["mode"] in mode_order else 99
        return (ri, pi, mi)

    rows_sorted = sorted(rows, key=sort_key)

    lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        r"\caption{Cold-start latency by region and platform (n\,=\,5 runs per cell,"
        r" bootstrap 95\,\% CI). Lower is better."
        r" Binance geo-block prevents us-east-1 live measurements.}",
        r"\label{tab:cold-start-n3}",
        r"\begin{tabular}{llllrr}",
        r"\toprule",
        r"Region & Platform & Mode & $n$ & Mean (ms) & 95\,\% CI (ms) \\",
        r"\midrule",
    ]

    prev_region = None
    for row in rows_sorted:
        region_lbl  = CLIENT_DISPLAY.get(row["client"], row["client"])
        plat_lbl    = PLAT_DISPLAY.get(row["platform"], row["platform"])
        mode_lbl    = row["mode"]
        n           = row["n_runs"]
        mean        = row["mean_ms"]
        ci_lo       = row["ci95_low"]
        ci_hi       = row["ci95_high"]

        if prev_region is not None and row["client"] != prev_region:
            lines.append(r"\midrule")
        prev_region = row["client"]

        lines.append(
            fr"{region_lbl} & {plat_lbl} & {mode_lbl} & {n} & {mean} & [{ci_lo:.1f},\ {ci_hi:.1f}] \\"
        )

    lines += [
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table}",
    ]
    with open(tex_path, "w") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
