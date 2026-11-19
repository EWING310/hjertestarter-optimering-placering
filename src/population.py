"""Byg et 50 m efterspørgselsgrid for Danmark.

1. GHSL GHS-POP 2025 (EU JRC, 100 m) giver fordelingen af beboere. Den er
   baseret på bygningsvolumen og er robust i tætte byområder.
2. Andelen af 60+ tages fra Meta HRSL 2020 (60+/total) aggregeret pr. H3-celle
   (res. 8, ~0,7 km²), så lokale artefakter i HRSL udlignes.
3. Hver 100 m GHSL-celle deles i 4 delceller (50 m), så en 100 m dækningsradius
   rammer ~13 delceller (≈ cirklens areal) i stedet for 5 hele celler.
4. Punkterne klippes til Danmark, aggregeres til et 50 m grid i UTM32,
   tildeles kommune og kalibreres til Danmarks Statistiks seneste officielle
   tal pr. kommune (FOLK1A: i alt og 60+).
"""

from __future__ import annotations

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
import pyarrow.csv as pacsv
import rasterio
import requests
from pyproj import Transformer

from src import config

ARCSEC = 3600
H3_RES = 8
DST_URL = "https://api.statbank.dk/v1/data"
GHSL_TILES = ("R3_C19", "R3_C20")
GHSL_PATTERN = "GHS_POP_E2025_GLOBE_R2023A_54009_100_V1_0_{tile}.tif"
DK_BBOX_WGS84 = (7.9, 54.5, 15.3, 57.8)  # vest, syd, øst, nord
# geoBoundaries -> Danmarks Statistik navne
KOMMUNE_ALIASES = {"Copenhagen": "København", "Nordfyn": "Nordfyns", "Vesthimmerland": "Vesthimmerlands"}


def _read_hrsl(name: str, value_col: str) -> pd.DataFrame:
    df = pacsv.read_csv(config.RAW / "hrsl" / name).to_pandas()
    df.columns = ["lon", "lat", value_col]
    df["ix"] = np.rint(df["lon"] * ARCSEC).astype(np.int64)
    df["iy"] = np.rint(df["lat"] * ARCSEC).astype(np.int64)
    return df


def load_hrsl() -> pd.DataFrame:
    general = _read_hrsl("dnk_general_2020.csv", "pop")
    elderly = _read_hrsl("dnk_elderly_60_plus_2020.csv", "pop60")[["ix", "iy", "pop60"]]
    merged = general.merge(elderly, on=["ix", "iy"], how="left")
    merged["pop60"] = merged["pop60"].fillna(0.0)
    return merged.drop(columns=["ix", "iy"])


def _read_ghsl_tile(path: str, bbox_moll: tuple[float, float, float, float]) -> pd.DataFrame:
    with rasterio.open(path) as src:
        window = rasterio.windows.from_bounds(*bbox_moll, transform=src.transform).round_offsets().round_lengths()
        data = src.read(1, window=window, boundless=True, fill_value=0)
        transform = src.window_transform(window)
    rows, cols = np.nonzero(data > 0)
    xs, ys = rasterio.transform.xy(transform, rows, cols, offset="center")
    return _split_cells(np.asarray(xs), np.asarray(ys), data[rows, cols])


def _split_cells(xs: np.ndarray, ys: np.ndarray, pop: np.ndarray, size: float = 100.0) -> pd.DataFrame:
    """Del hver celle i 2x2 delceller med en fjerdedel af befolkningen hver."""
    q = size / 4
    offsets = [(-q, -q), (-q, q), (q, -q), (q, q)]
    return pd.concat(
        [pd.DataFrame({"mx": xs + dx, "my": ys + dy, "pop": pop / 4}) for dx, dy in offsets], ignore_index=True
    )


def load_ghsl_points() -> pd.DataFrame:
    to_moll = Transformer.from_crs(config.CRS_WGS84, "ESRI:54009", always_xy=True)
    w, s, e, n = DK_BBOX_WGS84
    xs, ys = to_moll.transform([w, w, e, e], [s, n, s, n])
    bbox = (min(xs), min(ys), max(xs), max(ys))
    tiles = [_read_ghsl_tile(str(config.RAW / "ghsl" / GHSL_PATTERN.format(tile=t)), bbox) for t in GHSL_TILES]
    pts = pd.concat(tiles, ignore_index=True)
    to_wgs = Transformer.from_crs("ESRI:54009", config.CRS_WGS84, always_xy=True)
    lon, lat = to_wgs.transform(pts["mx"].to_numpy(), pts["my"].to_numpy())
    return pd.DataFrame({"lon": lon, "lat": lat, "pop": pts["pop"].to_numpy()})


def add_h3(points: pd.DataFrame) -> pd.DataFrame:
    cells = [h3.latlng_to_cell(lat, lon, H3_RES) for lat, lon in zip(points["lat"].to_numpy(), points["lon"].to_numpy(), strict=True)]
    return points.assign(h3=cells)


def mask_to_denmark(points: pd.DataFrame) -> pd.DataFrame:
    """Hurtigt forfilter: behold punkter i H3-celler som Kontur angiver som danske."""
    kontur = gpd.read_file(config.RAW / "kontur_population_DK_20231101.gpkg", ignore_geometry=True)
    return points[points["h3"].isin(set(kontur["h3"]))].reset_index(drop=True)


def elderly_share_by_hex(hrsl: pd.DataFrame) -> pd.Series:
    sums = hrsl.groupby("h3")[["pop", "pop60"]].sum()
    return (sums["pop60"] / sums["pop"]).clip(0, 1)


def to_grid(points: pd.DataFrame) -> pd.DataFrame:
    to_utm = Transformer.from_crs(config.CRS_WGS84, config.CRS_METRIC, always_xy=True)
    x, y = to_utm.transform(points["lon"].to_numpy(), points["lat"].to_numpy())
    g = config.GRID_M
    grid = pd.DataFrame(
        {"gx": np.floor(x / g).astype(np.int64), "gy": np.floor(y / g).astype(np.int64), "pop": points["pop"], "pop60": points["pop60"]}
    )
    grid = grid.groupby(["gx", "gy"], as_index=False)[["pop", "pop60"]].sum()
    grid["x"] = (grid["gx"] + 0.5) * g
    grid["y"] = (grid["gy"] + 0.5) * g
    to_wgs = Transformer.from_crs(config.CRS_METRIC, config.CRS_WGS84, always_xy=True)
    grid["lon"], grid["lat"] = to_wgs.transform(grid["x"].to_numpy(), grid["y"].to_numpy())
    return grid


def load_municipalities() -> gpd.GeoDataFrame:
    kommuner = gpd.read_file(config.RAW / "kommuner.geojson").to_crs(config.CRS_METRIC)
    kommuner["kommune"] = kommuner["shapeName"].replace(KOMMUNE_ALIASES)
    return kommuner[["kommune", "geometry"]]


def attach_municipality(df: pd.DataFrame, x_col: str = "x", y_col: str = "y", max_snap_m: float = 2000) -> pd.Series:
    """Kommunenavn for hvert punkt (punkter lige uden for kystlinjen snappes til nærmeste kommune)."""
    kommuner = load_municipalities()
    pts = gpd.GeoDataFrame(index=df.index, geometry=gpd.points_from_xy(df[x_col], df[y_col]), crs=config.CRS_METRIC)
    joined = gpd.sjoin(pts, kommuner, how="left", predicate="within")
    names = joined[~joined.index.duplicated()]["kommune"].copy()
    unmatched = names.isna()
    if unmatched.any():
        near = gpd.sjoin_nearest(pts[unmatched], kommuner, how="left", max_distance=max_snap_m)
        near = near[~near.index.duplicated()]
        names.loc[near.index] = near["kommune"]
    return names


def fetch_official_population() -> pd.DataFrame:
    """Seneste kvartals befolkning pr. kommune (i alt og 60+) fra Danmarks Statistik."""
    ages = [str(a) for a in range(126)]
    payload = {
        "table": "FOLK1A",
        "format": "BULK",
        "lang": "da",
        "variables": [
            {"code": "OMRÅDE", "values": ["*"]},
            {"code": "KØN", "values": ["TOT"]},
            {"code": "ALDER", "values": ages},
            {"code": "CIVILSTAND", "values": ["TOT"]},
            {"code": "Tid", "values": ["(1)"]},
        ],
    }
    resp = requests.post(DST_URL, json=payload, timeout=120)
    resp.raise_for_status()
    rows = [line.split(";") for line in resp.text.strip().splitlines()]
    df = pd.DataFrame(rows[1:], columns=rows[0])
    df["INDHOLD"] = pd.to_numeric(df["INDHOLD"])
    df["alder"] = df["ALDER"].str.extract(r"(\d+)").astype(int)
    df = df[~df["OMRÅDE"].str.startswith(("Region", "Hele"))]
    out = df.groupby("OMRÅDE").apply(
        lambda d: pd.Series({"pop_total": d["INDHOLD"].sum(), "pop_60plus": d.loc[d["alder"] >= 60, "INDHOLD"].sum()}),
        include_groups=False,
    )
    out = out.reset_index().rename(columns={"OMRÅDE": "kommune"})
    out.attrs["periode"] = df["TID"].iloc[0]
    return out


def calibrate_to_municipalities(grid: pd.DataFrame, official: pd.DataFrame) -> pd.DataFrame:
    """Skalér total og 60+ i hver kommune til de officielle tal; relativ fordeling bevares."""
    sums = grid.groupby("kommune")[["pop", "pop60"]].sum()
    f = official.set_index("kommune").join(sums, how="inner")
    factors = pd.DataFrame({"f_pop": f["pop_total"] / f["pop"], "f_pop60": f["pop_60plus"] / f["pop60"]})
    out = grid.join(factors, on="kommune")
    out[["f_pop", "f_pop60"]] = out[["f_pop", "f_pop60"]].fillna(1.0)
    pop = out["pop"] * out["f_pop"]
    pop60 = np.minimum(out["pop60"] * out["f_pop60"], pop)
    return out.assign(pop=pop, pop60=pop60).drop(columns=["f_pop", "f_pop60"])


def build_demand_grid() -> pd.DataFrame:
    points = mask_to_denmark(add_h3(load_ghsl_points()))
    print(f"GHSL-punkter i DK: {len(points):,} (sum {points['pop'].sum():,.0f})")
    hrsl = add_h3(load_hrsl())
    share = elderly_share_by_hex(hrsl)
    national_share = float(hrsl["pop60"].sum() / hrsl["pop"].sum())
    points["pop60"] = points["pop"] * points["h3"].map(share).fillna(national_share)
    grid = to_grid(points)
    grid["kommune"] = attach_municipality(grid)
    outside = grid["kommune"].isna()
    print(f"Grid-celler: {len(grid):,}; uden for DK fjernet: {outside.sum():,} (pop {grid.loc[outside, 'pop'].sum():,.0f})")
    grid = grid[~outside].reset_index(drop=True)
    official = fetch_official_population()
    official.to_csv(config.RAW / "dst_folk1a_kommuner.csv", index=False)
    print(f"DST FOLK1A {official.attrs['periode']}: {official['pop_total'].sum():,.0f} (60+: {official['pop_60plus'].sum():,.0f})")
    return calibrate_to_municipalities(grid, official)


def main() -> None:
    config.PROCESSED.mkdir(parents=True, exist_ok=True)
    grid = build_demand_grid()
    grid.to_parquet(config.PROCESSED / "demand_grid.parquet", index=False)
    print(f"Model: befolkning {grid['pop'].sum():,.0f}; heraf 60+: {grid['pop60'].sum():,.0f}; max celle {grid['pop'].max():,.0f}")


if __name__ == "__main__":
    main()
