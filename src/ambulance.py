"""Ambulancebaser i alle fem regioner, geokodet lokalt mod adresserne i OpenStreetMap.

Kilde: data/raw/ambulancebaser.csv (håndsamlet fra regionernes og operatørernes egne
lister; kilde-URL pr. række). Danske adresser er importeret i OSM fra DAR, så
geokodningen kan ske offline mod Geofabriks udtræk. Rækker uden adresse (kun by)
placeres i byens centrum, rækker med kun et vejnavn i vejens midtpunkt.
"""

from __future__ import annotations

import difflib
import re

import numpy as np
import osmium
import pandas as pd
from pyproj import Transformer

from src import config

BASES_CSV = config.RAW / "ambulancebaser.csv"
BASES_GEO = config.PROCESSED / "ambulancebaser_geo.csv"
OSM_INDEX = config.PROCESSED / "osm_index.parquet"
PBF_PATH = config.RAW / "denmark-latest.osm.pbf"

REGION_KOMMUNER: dict[str, tuple[str, ...]] = {
    "Hovedstaden": (
        "Albertslund", "Allerød", "Ballerup", "Bornholm", "Brøndby", "Dragør", "Egedal", "Fredensborg", "Frederiksberg",
        "Frederikssund", "Furesø", "Gentofte", "Gladsaxe", "Glostrup", "Gribskov", "Halsnæs", "Helsingør", "Herlev",
        "Hillerød", "Hvidovre", "Høje-Taastrup", "Hørsholm", "Ishøj", "København", "Lyngby-Taarbæk", "Rudersdal",
        "Rødovre", "Tårnby", "Vallensbæk",
    ),
    "Sjælland": (
        "Faxe", "Greve", "Guldborgsund", "Holbæk", "Kalundborg", "Køge", "Lejre", "Lolland", "Næstved", "Odsherred",
        "Ringsted", "Roskilde", "Slagelse", "Solrød", "Sorø", "Stevns", "Vordingborg",
    ),
    "Syddanmark": (
        "Aabenraa", "Assens", "Billund", "Esbjerg", "Faaborg-Midtfyn", "Fanø", "Fredericia", "Haderslev", "Kerteminde",
        "Kolding", "Langeland", "Middelfart", "Nordfyns", "Nyborg", "Odense", "Svendborg", "Sønderborg", "Tønder",
        "Varde", "Vejen", "Vejle", "Ærø",
    ),
    "Midtjylland": (
        "Favrskov", "Hedensted", "Herning", "Holstebro", "Horsens", "Ikast-Brande", "Lemvig", "Norddjurs", "Odder",
        "Randers", "Ringkøbing-Skjern", "Samsø", "Silkeborg", "Skanderborg", "Skive", "Struer", "Syddjurs", "Viborg",
        "Aarhus",
    ),
    "Nordjylland": (
        "Aalborg", "Brønderslev", "Frederikshavn", "Hjørring", "Jammerbugt", "Læsø", "Mariagerfjord", "Morsø",
        "Rebild", "Thisted", "Vesthimmerlands",
    ),
}
KOMMUNE_REGION = {k: r for r, ks in REGION_KOMMUNER.items() for k in ks}

PLACE_RANK = {"city": 0, "town": 1, "suburb": 2, "village": 3, "quarter": 4, "neighbourhood": 5, "hamlet": 6}
PLACE_TYPES = set(PLACE_RANK)
ABBREVIATIONS = (("sdr", "sønder"), ("nr", "nørre"), ("gl", "gammel"), ("st", "store"), ("kr", "kirke"))
MAX_TOWN_DIST_M = 15_000  # en adresse skal ligge højst så langt fra byen, hvis postnummer mangler


def norm_name(s: str) -> str:
    s = s.lower().replace("-", " ").replace("aa", "å")
    for short, full in ABBREVIATIONS:
        s = re.sub(rf"\b{short}\.?\s", f"{full} ", s)
    return re.sub(r"[^\wæøå ]", "", re.sub(r"\s+", " ", s)).strip()


def street_key(s: str) -> str:
    """Vejnavn uden mellemrum, så 'H.C. Ørstedsvej' og 'H.C. Ørsteds Vej' matcher."""
    return norm_name(s).replace(" ", "")


def split_address(adresse: str) -> tuple[str, str]:
    """'Laenvej 29-31' -> ('laenvej', '29'); 'Markedspladsen 15, st. tv.' -> ('markedspladsen', '15')."""
    first = adresse.split(",")[0].strip()
    m = re.match(r"^(.*?)\s+(\d+\s*[A-Za-z]?)(?:\s*-\s*\w+)?$", first)
    if not m:
        return street_key(first), ""
    return street_key(m.group(1)), m.group(2).replace(" ", "").lower()


def _center(obj: osmium.osm.OSMObject) -> tuple[float, float] | None:
    if obj.is_node():
        return obj.location.lon, obj.location.lat
    coords = [(n.lon, n.lat) for n in obj.nodes if n.location.valid()]
    if not coords:
        return None
    lons, lats = zip(*coords, strict=True)
    return sum(lons) / len(lons), sum(lats) / len(lats)


def extract_osm_index(streets: set[str]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Adresser, stednavne og midtpunkter for de vejnavne, der kun er angivet uden husnummer."""
    processor = (
        osmium.FileProcessor(str(PBF_PATH), osmium.osm.NODE | osmium.osm.WAY)
        .with_locations()
        .with_filter(osmium.filter.KeyFilter("addr:housenumber", "place", "highway"))
    )
    addrs, places, roads = [], [], []
    for obj in processor:
        tags = obj.tags
        if "addr:housenumber" in tags and "addr:street" in tags:
            c = _center(obj)
            if c:
                addrs.append((norm_name(tags["addr:street"]), tags["addr:housenumber"].replace(" ", "").lower(),
                              tags.get("addr:postcode", ""), norm_name(tags.get("addr:city", "")), *c))
        elif tags.get("place") in PLACE_TYPES and "name" in tags:
            c = _center(obj)
            if c:
                places.append((norm_name(tags["name"]), tags["place"], *c))
        elif obj.is_way() and "highway" in tags and norm_name(tags.get("name", "")) in streets:
            c = _center(obj)
            if c:
                roads.append((norm_name(tags["name"]), *c))
    return (
        pd.DataFrame(addrs, columns=["street", "hn", "postnr", "city", "lon", "lat"]),
        pd.DataFrame(places, columns=["name", "place", "lon", "lat"]),
        pd.DataFrame(roads, columns=["street", "lon", "lat"]),
    )


def region_of_points(lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    from src.population import attach_municipality

    x, y = Transformer.from_crs(config.CRS_WGS84, config.CRS_METRIC, always_xy=True).transform(lon, lat)
    return attach_municipality(pd.DataFrame({"x": x, "y": y})).map(KOMMUNE_REGION).to_numpy()


def _town(row: pd.Series, places: pd.DataFrame, pool: pd.DataFrame) -> tuple[float, float] | None:
    """Stednavnet i samme region; findes flere, det der ligger nærmest postdistriktets adresser."""
    anchor = (float(pool["lon"].median()), float(pool["lat"].median())) if len(pool) else None
    cand = places[(places["name"] == norm_name(row["by"])) & (places["region"] == row["region"])]
    if cand.empty:
        return anchor
    if anchor is None:
        best = cand.loc[cand["place"].map(PLACE_RANK).idxmin()]
        return float(best["lon"]), float(best["lat"])
    best = _nearest(cand, anchor)
    return (float(best["lon"]), float(best["lat"])) if best is not None else anchor


def _nearest(cand: pd.DataFrame, town: tuple[float, float] | None) -> pd.Series | None:
    if cand.empty or town is None:
        return None
    d = np.hypot((cand["lon"] - town[0]) * 0.56, cand["lat"] - town[1]) * 111_000
    return cand.loc[d.idxmin()] if d.min() <= MAX_TOWN_DIST_M else None


def _street_in(street: str, pool: pd.DataFrame) -> str:
    """Stavevarianter som 'Frederikshavnvej'/'Frederikshavnsvej' rettes inden for samme postdistrikt."""
    if street in set(pool["street"]):
        return street
    close = difflib.get_close_matches(street, pool["street"].unique().tolist(), n=1, cutoff=0.9)
    return close[0] if close else street


def geocode_row(row: pd.Series, addrs: pd.DataFrame, places: pd.DataFrame, roads: pd.DataFrame) -> tuple[float, float, str]:
    pool = addrs[addrs["postnr"] == row["postnr"]] if row["postnr"] else addrs[addrs["city"] == norm_name(row["by"])]
    town = _town(row, places, pool)
    if row["adresse"]:
        street, hn = split_address(row["adresse"])
        if hn and len(pool):
            street = _street_in(street, pool)
            on_street = pool[pool["street"] == street]
        else:
            on_street = addrs[addrs["street"] == street]
        hit = _nearest(on_street[on_street["hn"] == hn], town) if hn else None
        if hit is not None:
            return float(hit["lon"]), float(hit["lat"]), "adresse"
        road = _nearest(on_street if hn else roads[roads["street"] == street], town)
        if road is not None:
            return float(road["lon"]), float(road["lat"]), "vej"
    if town is not None:
        return town[0], town[1], "by"
    raise ValueError(f"Kunne ikke geokode ambulancebase: {row['navn']} ({row['adresse']}, {row['by']})")


def osm_index(streets: set[str]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """OSM-udtrækket tager et minut at gennemløbe, så indekset gemmes."""
    paths = [OSM_INDEX.with_name(f"{OSM_INDEX.stem}_{p}.parquet") for p in ("adresser", "steder", "veje")]
    if all(p.exists() for p in paths):
        frames = tuple(pd.read_parquet(p) for p in paths)
        if "city" in frames[0] and streets <= set(frames[2]["street"]):
            return frames
    frames = extract_osm_index(streets)
    for f, p in zip(frames, paths, strict=True):
        f.to_parquet(p, index=False)
    return frames


def geocode(bases: pd.DataFrame) -> pd.DataFrame:
    streets = {norm_name(a) for a in bases["adresse"] if a and not re.search(r"\d", a)}
    addrs, places, roads = osm_index(streets)
    addrs = addrs.assign(street=addrs["street"].str.replace(" ", ""))
    roads = roads.assign(street=roads["street"].str.replace(" ", ""))
    places = places.assign(region=region_of_points(places["lon"].to_numpy(), places["lat"].to_numpy()))
    coords = [geocode_row(r, addrs, places, roads) for _, r in bases.iterrows()]
    lon, lat, quality = zip(*coords, strict=True)
    geo = bases.assign(lon=np.round(lon, 6), lat=np.round(lat, 6), geokodning=quality)
    outside = geo[region_of_points(geo["lon"].to_numpy(), geo["lat"].to_numpy()) != geo["region"].to_numpy()]
    if len(outside):
        raise ValueError(f"Ambulancebaser geokodet uden for deres region: {outside['navn'].tolist()}")
    return geo


def load_bases() -> pd.DataFrame:
    from src.load import project

    return project(pd.read_csv(BASES_GEO, keep_default_na=False))


def main() -> None:
    bases = pd.read_csv(BASES_CSV, dtype=str, keep_default_na=False)
    geo = geocode(bases)
    config.PROCESSED.mkdir(parents=True, exist_ok=True)
    geo.to_csv(BASES_GEO, index=False)
    print(f"Geokodede {len(geo)} ambulancebaser")
    print(geo.groupby(["region", "geokodning"]).size().unstack(fill_value=0))


if __name__ == "__main__":
    main()
