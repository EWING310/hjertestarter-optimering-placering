"""Udtræk offentlige steder (mulige værter + steder med mange mennesker) fra OpenStreetMap.

Kilde: Geofabriks Danmarks-udtræk (data/raw/denmark-latest.osm.pbf).
Bruges til to ting:
1. Som realistiske værtssteder for nye hjertestartere (tankstation, supermarked, skole ...).
2. Som "offentlig tæthed" - steder hvor mange mennesker færdes i dagtimerne.
"""

from __future__ import annotations

import osmium
import pandas as pd

from src import config

PBF_PATH = config.RAW / "denmark-latest.osm.pbf"

# (osm-nøgle, værdier, dansk kategori, typisk døgnadgang, offentlig tæthedsvægt 1-5)
POI_TYPES: list[tuple[str, tuple[str, ...], str, bool, int]] = [
    ("railway", ("station", "halt"), "Togstation", True, 5),
    ("amenity", ("bus_station",), "Busterminal", True, 4),
    ("amenity", ("ferry_terminal",), "Færgeterminal", True, 4),
    ("shop", ("mall", "department_store"), "Indkøbscenter", False, 5),
    ("shop", ("supermarket",), "Supermarked", False, 4),
    ("amenity", ("fuel",), "Tankstation", True, 2),
    ("amenity", ("school",), "Skole", False, 4),
    ("amenity", ("university", "college"), "Uddannelsesinstitution", False, 4),
    ("leisure", ("sports_centre", "stadium", "sports_hall"), "Idrætsanlæg", False, 4),
    ("leisure", ("swimming_pool",), "Svømmehal", False, 3),
    ("leisure", ("fitness_centre",), "Fitnesscenter", False, 3),
    ("amenity", ("library", "townhall", "community_centre"), "Bibliotek/rådhus/medborgerhus", False, 3),
    ("amenity", ("place_of_worship",), "Kirke", False, 2),
    ("amenity", ("nursing_home",), "Plejehjem", True, 3),
    ("social_facility", ("nursing_home", "assisted_living"), "Plejehjem", True, 3),
    ("amenity", ("pharmacy",), "Apotek", False, 2),
    ("tourism", ("attraction", "museum", "zoo", "theme_park"), "Attraktion", False, 3),
    ("amenity", ("theatre", "cinema", "arts_centre"), "Kultur", False, 3),
    ("leisure", ("marina",), "Havn/marina", False, 2),
]
KEYS = sorted({key for key, *_ in POI_TYPES})

# Private svømmebassiner o.l. er ikke offentlige steder
EXCLUDED_ACCESS = {"private", "no"}


def categorize(tags: dict[str, str]) -> tuple[str, bool, int] | None:
    if tags.get("access") in EXCLUDED_ACCESS:
        return None
    for key, values, label, is_24h, weight in POI_TYPES:
        if tags.get(key) in values:
            return label, is_24h, weight
    return None


def _way_center(way: osmium.osm.Way) -> tuple[float, float] | None:
    coords = [(n.lon, n.lat) for n in way.nodes if n.location.valid()]
    if not coords:
        return None
    lons, lats = zip(*coords, strict=True)
    return sum(lons) / len(lons), sum(lats) / len(lats)


def _row(osm_id: str, lon: float, lat: float, tags: dict[str, str], cat: tuple[str, bool, int]) -> dict:
    label, is_24h, weight = cat
    opening = tags.get("opening_hours", "")
    return {
        "osm_id": osm_id,
        "lat": lat,
        "lon": lon,
        "kategori": label,
        "navn": tags.get("name", ""),
        "adresse": " ".join(x for x in (tags.get("addr:street", ""), tags.get("addr:housenumber", "")) if x),
        "postnr": tags.get("addr:postcode", ""),
        "by": tags.get("addr:city", ""),
        "opening_hours": opening,
        "dognaaben": is_24h or opening.strip() == "24/7",
        "offentlig_vaegt": weight,
    }


def extract_pois() -> pd.DataFrame:
    processor = (
        osmium.FileProcessor(str(PBF_PATH), osmium.osm.NODE | osmium.osm.WAY)
        .with_locations()
        .with_filter(osmium.filter.KeyFilter(*KEYS))
    )
    rows = []
    for obj in processor:
        tags = dict(obj.tags)
        cat = categorize(tags)
        if cat is None:
            continue
        if obj.is_node():
            rows.append(_row(f"node/{obj.id}", obj.location.lon, obj.location.lat, tags, cat))
        elif obj.is_way():
            center = _way_center(obj)
            if center is not None:
                rows.append(_row(f"way/{obj.id}", center[0], center[1], tags, cat))
    return pd.DataFrame(rows)


def main() -> None:
    df = extract_pois()
    df.to_csv(config.RAW / "osm_pois.csv", index=False)
    print(f"Gemte {len(df):,} POI'er")
    print(df["kategori"].value_counts())


if __name__ == "__main__":
    main()
