"""Tid til første stød og forventet overlevelse - samme model for alle borgere."""

from __future__ import annotations

import numpy as np

from src import config


def time_to_aed(dist_m: np.ndarray) -> np.ndarray:
    """Minutter fra hjertestop til en hjertestarter i luftlinjeafstand `dist_m` er hentet og tilsluttet."""
    round_trip = 2 * config.ROUTE_FACTOR * np.asarray(dist_m, dtype=float)
    return config.T_ALARM_MIN + round_trip / config.RETRIEVE_SPEED_M_PER_MIN


def time_to_ems(response_min: np.ndarray) -> np.ndarray:
    """Minutter fra hjertestop til ambulancens første stød, givet responstiden fra 112-opkaldet."""
    return np.asarray(response_min, dtype=float) + config.T_EMS_EXTRA_MIN


def time_to_defib(dist_m: np.ndarray, t_ems: np.ndarray) -> np.ndarray:
    """Første stød kommer fra den hurtigste af nærmeste hjertestarter og ambulancen."""
    return np.minimum(time_to_aed(dist_m), t_ems)


def survival(t_defib: np.ndarray) -> np.ndarray:
    """Sandsynlighed for overlevelse ved stødbar rytme (Valenzuela 1997)."""
    a, b_cpr, b_defib = config.VALENZUELA
    logit = a - b_cpr * config.T_CPR_MIN - b_defib * np.asarray(t_defib, dtype=float)
    return 1 / (1 + np.exp(-logit))


def reach_radius(t_ems: np.ndarray) -> np.ndarray:
    """Største afstand hvor en hjertestarter stadig er hurtigere end ambulancen."""
    slack = np.maximum(np.asarray(t_ems, dtype=float) - config.T_ALARM_MIN, 0)
    return slack * config.RETRIEVE_SPEED_M_PER_MIN / (2 * config.ROUTE_FACTOR)
