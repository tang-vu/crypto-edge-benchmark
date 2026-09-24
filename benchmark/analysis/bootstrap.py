"""
Bootstrap CI module for statistical analysis.

AGGREGATION LEVEL: Operates on whatever data is passed in.
- When called with per-run aggregates (n=runs, typically 5-7): yields CI on the mean-of-run-means.
- When called with synthetic per-request pseudo-samples (n=many): yields CI on the true request distribution.

All functions are deterministic via seeded numpy RNG.
"""

import numpy as np
from typing import Tuple


def bootstrap_ci(
    data: np.ndarray,
    statistic=np.mean,
    n_resamples: int = 10000,
    ci: float = 0.95,
    seed: int = 42,
) -> Tuple[float, float, float]:
    """
    Compute bootstrap percentile confidence interval for a given statistic.

    Args:
        data: 1-D array of observations.
        statistic: Callable applied to each resample (default: np.mean).
        n_resamples: Number of bootstrap resamples (default 10000).
        ci: Confidence level, e.g. 0.95 for 95% CI.
        seed: RNG seed for reproducibility.

    Returns:
        Tuple (point_estimate, ci_lower, ci_upper) where point_estimate is
        statistic(data) and ci bounds are percentile-method bootstrap bounds.
    """
    data = np.asarray(data, dtype=float)
    n = len(data)

    if n < 2:
        val = float(statistic(data))
        return val, val, val

    rng = np.random.default_rng(seed)
    # Draw n_resamples bootstrap samples all at once (n_resamples × n matrix)
    indices = rng.integers(0, n, size=(n_resamples, n))
    resampled = data[indices]
    boot_stats = np.apply_along_axis(statistic, 1, resampled)

    alpha = (1.0 - ci) / 2.0
    lower = float(np.percentile(boot_stats, alpha * 100))
    upper = float(np.percentile(boot_stats, (1 - alpha) * 100))
    point = float(statistic(data))

    return point, lower, upper


def bootstrap_ci_median(
    data: np.ndarray,
    n_resamples: int = 10000,
    ci: float = 0.95,
    seed: int = 42,
) -> Tuple[float, float, float]:
    """Convenience wrapper: bootstrap CI for the median."""
    return bootstrap_ci(data, statistic=np.median, n_resamples=n_resamples, ci=ci, seed=seed)


if __name__ == "__main__":
    # Smoke test: bootstrap of [1..100] -> mean ~50, 95% CI approx [44, 56]
    rng = np.random.default_rng(0)
    sample = rng.integers(1, 101, size=100).astype(float)
    mean_val, lo, hi = bootstrap_ci(sample, n_resamples=10000, seed=42)
    print(f"Sample mean: {mean_val:.2f}, 95% CI: [{lo:.2f}, {hi:.2f}]")
    assert 40 < lo < 50, f"CI lower out of expected range: {lo}"
    assert 50 < hi < 60, f"CI upper out of expected range: {hi}"
    print("bootstrap.py smoke test passed.")
