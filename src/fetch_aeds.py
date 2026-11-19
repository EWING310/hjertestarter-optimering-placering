"""Hent alle offentligt viste hjertestartere fra Dansk Hjertestarterregister.

Kilden er det JSON-endpoint, som kortet på hjertestarter.dk selv bruger.
Ved zoom 21 returnerer endpointet enkeltpunkter (ingen klynger), så hele
Danmark kan hentes med et lille antal bbox-kald.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd
import requests

BASE_URL = "https://cdn.hjertestarterdata.dk/api/v4/aedspublic"
HEADERS = {"User-Agent": "Mozilla/5.0 (aed-coverage-research)", "Referer": "https://www.hjertestarter.dk/"}
DK_BBOX = (54.5, 7.9, 57.8, 15.3)  # syd, vest, nord, øst
TILE_DEG = 0.5
ZOOM_UNCLUSTERED = 21
REQUEST_PAUSE_S = 0.5

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"


def tile_bboxes(bbox: tuple[float, float, float, float], step: float) -> list[tuple[float, float, float, float]]:
    south, west, north, east = bbox
    tiles = []
    lat = south
    while lat < north:
        lng = west
        while lng < east:
            tiles.append((lat, lng, min(lat + step, north), min(lng + step, east)))
            lng += step
        lat += step
    return tiles


def fetch_tile(session: requests.Session, tile: tuple[float, float, float, float]) -> list[dict]:
    south, west, north, east = tile
    url = f"{BASE_URL}/maps/clustered/web/true/true/true/true/{north}/{east}/{south}/{west}/{ZOOM_UNCLUSTERED}.json"
    resp = session.get(url, headers=HEADERS, timeout=60)
    resp.raise_for_status()
    return resp.json()


def classify(row: dict) -> str:
    if row.get("isGreyAed"):
        return "utilgaengelig"
    if row.get("is247Aed"):
        return "døgnåben"
    if row.get("isBehindLock"):
        return "bag_lås"
    return "åbningstid"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    records: list[dict] = []
    tiles = tile_bboxes(DK_BBOX, TILE_DEG)
    for i, tile in enumerate(tiles, 1):
        points = fetch_tile(session, tile)
        clustered = [p for p in points if p.get("c", 1) != 1]
        if clustered:
            raise RuntimeError(f"Tile {tile} returned clustered points; lower TILE_DEG")
        records.extend(points)
        print(f"[{i}/{len(tiles)}] {tile} -> {len(points)}")
        time.sleep(REQUEST_PAUSE_S)

    (OUT_DIR / "aeds_raw.json").write_text(json.dumps(records))
    df = pd.DataFrame(
        {
            "id": [r["id"] for r in records],
            "lat": [float(r["latitude"]) for r in records],
            "lon": [float(r["longitude"]) for r in records],
            "is247": [bool(r.get("is247Aed")) for r in records],
            "behind_lock": [bool(r.get("isBehindLock")) for r in records],
            "grey": [bool(r.get("isGreyAed")) for r in records],
            "kategori": [classify(r) for r in records],
        }
    ).drop_duplicates("id")
    df.to_csv(OUT_DIR / "aeds.csv", index=False)
    print(f"Gemte {len(df)} unikke hjertestartere")
    print(df["kategori"].value_counts())


if __name__ == "__main__":
    main()
