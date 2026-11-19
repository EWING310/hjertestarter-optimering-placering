import numpy as np
import pytest

from src.coverage import coverage_share, nearest_distance, risk_weights


@pytest.mark.unit
def test_nearest_distance_returns_euclidean_distance_to_closest_aed():
    demand = np.array([[0.0, 0.0], [900.0, 0.0]])
    aeds = np.array([[0.0, 50.0], [1000.0, 0.0]])

    dist = nearest_distance(demand, aeds)

    np.testing.assert_allclose(dist, [50.0, 100.0])


@pytest.mark.unit
def test_nearest_distance_is_infinite_when_no_aeds():
    demand = np.array([[0.0, 0.0]])

    dist = nearest_distance(demand, np.empty((0, 2)))

    assert np.isinf(dist).all()


@pytest.mark.unit
def test_coverage_share_weights_by_demand():
    dist = np.array([10.0, 150.0, 90.0])
    weight = np.array([1.0, 2.0, 1.0])

    share = coverage_share(dist, weight, radius=100.0)

    assert share == pytest.approx(0.5)


@pytest.mark.unit
def test_risk_weights_scale_to_national_total_and_respect_ratio():
    pop_total = np.array([100.0, 100.0])
    pop_60plus = np.array([0.0, 100.0])

    w = risk_weights(pop_total, pop_60plus, total_events=80.0, ratio_60plus=7.0)

    assert w.sum() == pytest.approx(80.0)
    assert w[1] / w[0] == pytest.approx(7.0)


@pytest.mark.unit
def test_risk_weights_clip_elderly_above_total():
    w = risk_weights(np.array([10.0]), np.array([12.0]), total_events=1.0, ratio_60plus=7.0)

    assert w[0] == pytest.approx(1.0)
