"""Afstands- og dækningsberegninger (rene funktioner på metriske koordinater)."""

from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree


def nearest_distance(demand_xy: np.ndarray, aed_xy: np.ndarray) -> np.ndarray:
    """Afstand (m) fra hvert efterspørgselspunkt til nærmeste hjertestarter."""
    if len(aed_xy) == 0:
        return np.full(len(demand_xy), np.inf)
    dist, _ = cKDTree(aed_xy).query(demand_xy, k=1, workers=-1)
    return dist


def coverage_share(dist: np.ndarray, weight: np.ndarray, radius: float) -> float:
    """Andel af (vægtet) efterspørgsel der ligger inden for `radius` af en hjertestarter."""
    total = weight.sum()
    if total == 0:
        return 0.0
    return float(weight[dist <= radius].sum() / total)


def risk_weights(
    pop_total: np.ndarray,
    pop_60plus: np.ndarray,
    total_events: float,
    ratio_60plus: float,
) -> np.ndarray:
    """Forventet antal hjertestop pr. år pr. celle ud fra alderssammensætning.

    Personer 60+ vægtes `ratio_60plus` gange højere end yngre, og vægtene
    skaleres så summen svarer til det nationale antal hjertestop pr. år.
    """
    elderly = np.minimum(pop_60plus, pop_total)
    younger = pop_total - elderly
    raw = younger + ratio_60plus * elderly
    raw_sum = raw.sum()
    if raw_sum == 0:
        return np.zeros_like(raw)
    return raw * (total_events / raw_sum)
