import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Point, box

from src import config
from src.landuse import uninhabited

G = config.GRID_M


def _cells(*gxy: tuple[int, int]) -> pd.DataFrame:
    gx, gy = np.array([c[0] for c in gxy]), np.array([c[1] for c in gxy])
    return pd.DataFrame({"gx": gx, "gy": gy, "x": (gx + 0.5) * G, "y": (gy + 0.5) * G})


@pytest.mark.unit
def test_cells_in_industrial_area_are_uninhabited_unless_a_home_is_there():
    grid = _cells((0, 0), (1, 0), (5, 0))
    areas = gpd.GeoDataFrame(geometry=[box(0, 0, 2 * G, G)], crs=config.CRS_METRIC)
    homes = gpd.GeoDataFrame(geometry=[Point(1.2 * G, 0.4 * G)], crs=config.CRS_METRIC)

    out = uninhabited(grid, areas, homes)

    assert out.tolist() == [True, False, False]


@pytest.mark.unit
def test_overlapping_areas_do_not_duplicate_cells():
    grid = _cells((0, 0), (3, 3))
    areas = gpd.GeoDataFrame(geometry=[box(0, 0, G, G), box(-G, -G, G, G)], crs=config.CRS_METRIC)
    homes = gpd.GeoDataFrame(geometry=[], crs=config.CRS_METRIC)

    out = uninhabited(grid, areas, homes)

    assert out.tolist() == [True, False]
