import numpy as np
import pytest

from src.survival import reach_radius, survival, time_to_aed, time_to_defib


@pytest.mark.unit
def test_time_to_aed_grows_with_round_trip_distance():
    assert time_to_aed(np.array([0.0]))[0] == pytest.approx(2.0)
    assert time_to_aed(np.array([110.0]))[0] == pytest.approx(2.0 + 2 * 1.3 * 110 / 110)


@pytest.mark.unit
def test_time_to_defib_is_capped_by_ambulance():
    t = time_to_defib(np.array([50.0, 5000.0]), np.array([8.0, 8.0]))

    assert t[0] < 8.0
    assert t[1] == pytest.approx(8.0)


@pytest.mark.unit
def test_survival_follows_valenzuela_and_decreases_with_time():
    s = survival(np.array([0.0, 5.0, 10.0]))

    expected0 = 1 / (1 + np.exp(-(0.260 - 0.106 * 2.0)))
    assert s[0] == pytest.approx(expected0)
    assert s[0] > s[1] > s[2]


@pytest.mark.unit
def test_reach_radius_is_where_aed_stops_beating_ambulance():
    r = reach_radius(np.array([8.0]))

    assert time_to_aed(r)[0] == pytest.approx(8.0)
