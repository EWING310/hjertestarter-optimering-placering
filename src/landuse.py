"""Arealer uden beboere (industri, havn, jernbane m.m.) fra OpenStreetMap.

GHSL fordeler beboerne efter bygningsvolumen, så store haller i industriområder
får beboere, der ikke findes. 50 m-celler inden for disse arealer fjernes, og
kommunens befolkning fordeles i stedet på de øvrige celler (kalibreringen i
src/population.py). En celle beholdes, hvis OSM har en bygning i den, der er
angivet som bolig (fx en ejerbolig i et erhvervsområde).

Butiks- og erhvervszoner (landuse=retail/commercial) fjernes ikke: i bymidterne
dækker de også lejlighederne over butikkerne.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import osmium
import pandas as pd
from shapely import wkb

from src import config

PBF_PATH = config.RAW / "denmark-latest.osm.pbf"
AREAS_PARQUET = config.PROCESSED / "osm_ikke_bolig.parquet"
HOMES_PARQUET = config.PROCESSED / "osm_boligbygninger.parquet"

NON_RESIDENTIAL = ("industrial", "railway", "port", "quarry", "landfill", "military")
RESIDENTIAL_BUILDINGS = (
    "house", "detached", "apartments", "terrace", "semidetached_house", "bungalow", "residential", "dormitory", "farm",
)


def extract() -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Polygoner for arealer uden beboere og midtpunkter af bygninger angivet som bolig."""
    factory = osmium.geom.WKBFactory()
    areas, homes, invalid = [], [], 0
    processor = osmium.FileProcessor(str(PBF_PATH)).with_areas().with_filter(osmium.filter.KeyFilter("landuse", "building"))
    for obj in processor:
        if not obj.is_area():
            continue
        landuse, building = obj.tags.get("landuse"), obj.tags.get("building")
        if landuse not in NON_RESIDENTIAL and building not in RESIDENTIAL_BUILDINGS:
            continue
        try:
            geom = wkb.loads(factory.create_multipolygon(obj), hex=True)
        except RuntimeError:
            invalid += 1
            continue
        if landuse in NON_RESIDENTIAL:
            areas.append((landuse, obj.tags.get("name", ""), geom))
        else:
            homes.append(geom.centroid)
    print(f"OSM: {len(areas):,} arealer uden beboere, {len(homes):,} boligbygninger ({invalid} ugyldige polygoner sprunget over)")
    return (
        gpd.GeoDataFrame(areas, columns=["landuse", "name", "geometry"], crs=config.CRS_WGS84).to_crs(config.CRS_METRIC),
        gpd.GeoDataFrame(geometry=homes, crs=config.CRS_WGS84).to_crs(config.CRS_METRIC),
    )


def load() -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """OSM-udtrækket tager et halvt minut, så resultatet gemmes."""
    if AREAS_PARQUET.exists() and HOMES_PARQUET.exists():
        return gpd.read_parquet(AREAS_PARQUET), gpd.read_parquet(HOMES_PARQUET)
    areas, homes = extract()
    areas.to_parquet(AREAS_PARQUET)
    homes.to_parquet(HOMES_PARQUET)
    return areas, homes


def uninhabited(grid: pd.DataFrame, areas: gpd.GeoDataFrame, homes: gpd.GeoDataFrame) -> np.ndarray:
    """True for celler (gx, gy, x, y), hvis midtpunkt ligger i et areal uden beboere og som ingen boligbygning har."""
    pts = gpd.GeoDataFrame(geometry=gpd.points_from_xy(grid["x"], grid["y"]), crs=config.CRS_METRIC)
    hit = gpd.sjoin(pts, areas[["geometry"]], predicate="within").index.unique()
    inside = np.zeros(len(grid), dtype=bool)
    inside[hit] = True
    g = config.GRID_M
    home_cells = pd.MultiIndex.from_arrays(
        [np.floor(homes.geometry.x.to_numpy() / g).astype(np.int64), np.floor(homes.geometry.y.to_numpy() / g).astype(np.int64)]
    )
    has_home = pd.MultiIndex.from_arrays([grid["gx"].to_numpy(), grid["gy"].to_numpy()]).isin(home_cells)
    return inside & ~has_home
