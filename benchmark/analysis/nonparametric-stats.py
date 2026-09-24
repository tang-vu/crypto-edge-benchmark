"""
Non-parametric statistical tests for benchmark comparison.

AGGREGATION LEVEL NOTE:
- Mann-Whitney U is used on per-run aggregate arrays (n=runs, typically 5-7).
  This is the same n as the Welch t-test in statistical_analysis.py.
- The test is preferred over t-test for burst data where normality is suspect
  due to VU ramp-up producing multi-modal latency distributions.
- Shapiro-Wilk is used to decide which test to report as primary.
"""

import numpy as np
from scipy import stats
from typing import Dict, Any


def mann_whitney_u(g1: np.ndarray, g2: np.ndarray) -> Dict[str, Any]:
    """
    Perform two-sided Mann-Whitney U test (does not assume normality).

    Effect size: rank-biserial correlation r = 1 - 2U/(n1*n2).
      r ~ 0.1 small, ~ 0.3 medium, ~ 0.5 large.

    Args:
        g1: First group observations (e.g., Cloudflare per-run avgs).
        g2: Second group observations (e.g., Vercel per-run avgs).

    Returns:
        Dict with keys: u_statistic, p_value, effect_r, significant,
                        median_g1, median_g2, median_diff.
    """
    g1 = np.asarray(g1, dtype=float)
    g2 = np.asarray(g2, dtype=float)

    if len(g1) < 2 or len(g2) < 2:
        return {
            "u_statistic": None,
            "p_value": None,
            "effect_r": None,
            "significant": None,
            "median_g1": float(np.median(g1)) if len(g1) else None,
            "median_g2": float(np.median(g2)) if len(g2) else None,
            "median_diff": None,
        }

    stat, p = stats.mannwhitneyu(g1, g2, alternative="two-sided")
    n1, n2 = len(g1), len(g2)
    # Rank-biserial correlation as effect size (ranges -1 to +1)
    r = 1.0 - (2.0 * float(stat)) / (n1 * n2)

    return {
        "u_statistic": float(stat),
        "p_value": float(p),
        "effect_r": float(r),
        "significant": bool(p < 0.05),
        "median_g1": float(np.median(g1)),
        "median_g2": float(np.median(g2)),
        "median_diff": float(np.median(g2) - np.median(g1)),
    }


def shapiro_test(data: np.ndarray) -> Dict[str, Any]:
    """
    Shapiro-Wilk normality test.

    Returns:
        Dict with keys: W (statistic), p_value, normal (bool: p >= 0.05).
    """
    data = np.asarray(data, dtype=float)
    if len(data) < 3:
        return {"W": None, "p_value": None, "normal": None}

    W, p = stats.shapiro(data)
    return {"W": float(W), "p_value": float(p), "normal": bool(p >= 0.05)}


def interpret_effect_r(r: float) -> str:
    """Interpret rank-biserial correlation magnitude."""
    abs_r = abs(r)
    if abs_r < 0.1:
        return "negligible"
    elif abs_r < 0.3:
        return "small"
    elif abs_r < 0.5:
        return "medium"
    else:
        return "large"


if __name__ == "__main__":
    # Smoke test
    rng = np.random.default_rng(42)
    a = rng.normal(40, 2, 7)
    b = rng.normal(90, 2, 7)
    result = mann_whitney_u(a, b)
    print(f"Mann-Whitney U: {result}")
    assert result["significant"], "Expected significant difference"
    sw = shapiro_test(a)
    print(f"Shapiro-Wilk on group a: {sw}")
    print("nonparametric-stats.py smoke test passed.")
