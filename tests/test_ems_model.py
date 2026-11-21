import numpy as np
import pytest

from src.ems_model import EmsParams, median_response, share_within

P = EmsParams(a=3.0, b=0.6, sigma=0.4)


@pytest.mark.unit
def test_median_response_is_linear_in_drive_time():
    np.testing.assert_allclose(median_response(np.array([0.0, 10.0]), P), [3.0, 9.0])


@pytest.mark.unit
def test_half_of_runs_arrive_within_the_median():
    drive = np.array([10.0])

    assert share_within(drive, np.ones(1), 9.0, P) == pytest.approx(0.5)


@pytest.mark.unit
def test_share_within_rises_with_limit_and_falls_with_distance():
    near, far, w = np.array([2.0]), np.array([20.0]), np.ones(1)

    assert share_within(near, w, 5, P) < share_within(near, w, 10, P) < share_within(near, w, 15, P)
    assert share_within(far, w, 10, P) < share_within(near, w, 10, P)
