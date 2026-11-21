import numpy as np
import pytest

from src import config
from src.road_network import FERRY_KMH, SPEED_KMH, connect_minutes, drive_from_bases, to_csr, way_speed


def _line_graph(minutes: list[float]) -> dict[str, np.ndarray]:
    """Knuder på en ret linje med 1 km imellem; alle er lokale veje."""
    n = len(minutes) + 1
    return {
        "x": np.arange(n) * 1000.0, "y": np.zeros(n),
        "u": np.arange(n - 1, dtype=np.int32), "v": np.arange(1, n, dtype=np.int32),
        "minutes": np.asarray(minutes, dtype=np.float32), "local": np.ones(n, dtype=bool),
    }


@pytest.mark.unit
def test_way_speed_prefers_signed_limit_and_skips_non_drivable():
    assert way_speed({"highway": "residential", "maxspeed": "40"}) == (40.0, True, False)
    assert way_speed({"highway": "residential"}) == (SPEED_KMH["residential"], True, False)
    assert way_speed({"highway": "motorway"})[1] is False
    assert way_speed({"route": "ferry"}) == (FERRY_KMH, False, True)
    assert way_speed({"highway": "footway"}) is None
    assert way_speed({"highway": "service", "service": "parking_aisle"}) is None


@pytest.mark.unit
def test_to_csr_keeps_the_fastest_of_parallel_edges():
    g = _line_graph([2.0])
    g = {**g, "u": np.array([0, 1], np.int32), "v": np.array([1, 0], np.int32), "minutes": np.array([2.0, 0.5], np.float32)}

    graph = to_csr(g)

    assert graph.nnz == 1
    assert graph[0, 1] == pytest.approx(0.5)


@pytest.mark.unit
def test_drive_from_bases_uses_nearest_base_by_road_time():
    g = _line_graph([1.0, 1.0, 1.0, 1.0])  # knuder ved 0, 1, 2, 3, 4 km
    bases = np.array([[0.0, 0.0], [4000.0, 0.0]])
    targets = np.array([[1000.0, 0.0], [3000.0, 50.0]])

    minutes, base_idx = drive_from_bases(g, bases, targets)

    assert base_idx.tolist() == [0, 1]
    assert minutes[0] == pytest.approx(1.0)
    assert minutes[1] == pytest.approx(1.0 + connect_minutes(np.array([50.0]))[0])


@pytest.mark.unit
def test_connect_minutes_uses_route_factor():
    assert connect_minutes(np.array([250.0]))[0] == pytest.approx(config.ROUTE_FACTOR * 250 / 250)
