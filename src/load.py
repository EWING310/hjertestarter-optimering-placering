"""Indlæs og projicér de forberedte datasæt."""

from __future__ import annotations

import numpy as np
import pandas as pd
from pyproj import Transformer

from src import config
from src.coverage import risk_weights

_TO_UTM = Transformer.from_crs(config.CRS_WGS84, config.CRS_METRIC, always_xy=True)
_TO_WGS = Transformer.from_crs(config.CRS_METRIC, config.CRS_WGS84, always_xy=True)


def project(df: pd.DataFrame) -> pd.DataFrame:
    x, y = _TO_UTM.transform(df["lon"].to_numpy(), df["lat"].to_numpy())
    return df.assign(x=x, y=y)


def unproject(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    lon, lat = _TO_WGS.transform(x, y)
    return np.asarray(lon), np.asarray(lat)


def xy(df: pd.DataFrame) -> np.ndarray:
    return df[["x", "y"]].to_numpy()


def load_demand() -> pd.DataFrame:
    grid = pd.read_parquet(config.PROCESSED / "demand_grid.parquet")
    grid["risk"] = risk_weights(
        grid["pop"].to_numpy(), grid["pop60"].to_numpy(), config.OHCA_PER_YEAR_DK, config.RISK_RATIO_60PLUS
    )
    growth = pd.read_csv(config.PROCESSED / "kommune_vaekst_2026_2036.csv").set_index("kommune")["vaekst_risiko"]
    grid["risk_2036"] = grid["risk"] * grid["kommune"].map(growth).fillna(1.0)
    return grid


def load_aeds() -> pd.DataFrame:
    return project(pd.read_csv(config.RAW / "aeds.csv"))


def load_pois() -> pd.DataFrame:
    pois = pd.read_csv(config.RAW / "osm_pois.csv", dtype={"postnr": str}, keep_default_na=False)
    pois = pois[pois["navn"].str.strip() != ""]
    return project(pois.reset_index(drop=True))
