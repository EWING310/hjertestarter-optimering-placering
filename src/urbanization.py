"""Urbaniseringsgrad (DEGURBA niveau 1) fra GHSL-SMOD 2025, 1 km."""

from __future__ import annotations

import numpy as np
import rasterio
from pyproj import Transformer

from src import config

SMOD_PATTERN = "GHS_SMOD_E2025_GLOBE_R2023A_54009_1000_V2_0_{tile}.tif"
SMOD_TILES = ("R3_C19", "R3_C20")


def smod_codes(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """GHSL-SMOD-kode (10-30) for punkter i UTM32."""
    mx, my = Transformer.from_crs(config.CRS_METRIC, "ESRI:54009", always_xy=True).transform(x, y)
    codes = np.zeros(len(mx), dtype=np.int16)
    for tile in SMOD_TILES:
        with rasterio.open(config.RAW / "ghsl_smod" / SMOD_PATTERN.format(tile=tile)) as src:
            data, b = src.read(1), src.bounds
            inside = (mx >= b.left) & (mx < b.right) & (my > b.bottom) & (my <= b.top)
            rows, cols = rasterio.transform.rowcol(src.transform, mx[inside], my[inside])
            codes[inside] = data[np.asarray(rows), np.asarray(cols)]
    return codes


def classify(codes: np.ndarray) -> np.ndarray:
    """0 = By (bykerne, 30), 1 = Mindre by/forstad (21-23), 2 = Land (10-13 og ukendt)."""
    return np.where(codes == 30, 0, np.where((codes >= 21) & (codes <= 23), 1, 2)).astype(np.int8)


def urban_class(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    return classify(smod_codes(x, y))
