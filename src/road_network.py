"""Køretid ad vejnettet fra nærmeste ambulancebase til hver beboet 50 m-celle.

Vejnettet bygges fra OpenStreetMap (Geofabriks Danmarks-udtræk): alle veje en
ambulance kan køre på samt færgeruter. Hastigheden er vejens skiltede
hastighed (`maxspeed`) eller en standard pr. vejtype. Den korteste køretid fra
alle baser på én gang findes med multi-source Dijkstra. Hver celle kobles til
nærmeste lokale vej (ikke motorvej) med en kort strækning i lav fart.

Resultatet er ren køretid fra basen. Udkald, at ambulancen ofte ikke holder på
basen, og afvigelser i hastighed kalibreres bagefter mod målte responstider
(se src/ems_model.py).
"""

from __future__ import annotations

from array import array

import numpy as np
import osmium
import pandas as pd
from pyproj import Transformer
from scipy.sparse import coo_matrix, csr_matrix
from scipy.sparse.csgraph import connected_components, dijkstra
from scipy.spatial import cKDTree

from src import config
from src.ambulance import load_bases

PBF_PATH = config.RAW / "denmark-latest.osm.pbf"
GRAPH_NPZ = config.PROCESSED / "vejnet.npz"
DRIVE_PARQUET = config.PROCESSED / "ems_koertid.parquet"

# Standardhastighed (km/t) pr. vejtype, når maxspeed mangler
SPEED_KMH = {
    "motorway": 110, "trunk": 90, "primary": 70, "secondary": 65, "tertiary": 55,
    "motorway_link": 60, "trunk_link": 50, "primary_link": 45, "secondary_link": 40, "tertiary_link": 35,
    "unclassified": 50, "road": 40, "residential": 30, "living_street": 15, "service": 20,
}
NON_LOCAL = ("motorway", "motorway_link", "trunk", "trunk_link")  # celler kobles ikke direkte på disse
FERRY_KMH = 25.0
FERRY_WAIT_MIN = 15.0  # ventetid/ombordkørsel pr. færgerute
CONNECT_KMH = 15.0  # sidste stykke fra vej til bolig (indkørsel, sti)
SKIP_SERVICE = {"parking_aisle", "drive-through"}


def way_speed(tags: osmium.osm.TagList) -> tuple[float, bool, bool] | None:
    """(km/t, lokal vej, færge) for en vej, eller None hvis ambulancen ikke kan køre der."""
    if tags.get("route") == "ferry":
        return FERRY_KMH, False, True
    hw = tags.get("highway")
    if hw not in SPEED_KMH or tags.get("area") == "yes" or tags.get("service") in SKIP_SERVICE:
        return None
    speed = float(SPEED_KMH[hw])
    raw = tags.get("maxspeed", "").split(";")[0].strip()
    if raw.isdigit() and 5 <= int(raw) <= 130:
        speed = float(raw)
    return speed, hw not in NON_LOCAL, False


def read_ways() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Knudereferencer og koordinater for alle kørbare veje, med vejens fart pr. knude."""
    processor = (
        osmium.FileProcessor(str(PBF_PATH), osmium.osm.NODE | osmium.osm.WAY)
        .with_locations()
        .with_filter(osmium.filter.KeyFilter("highway", "route"))
    )
    ids, lon, lat = array("q"), array("d"), array("d")
    speed, local, ferry, lengths = array("f"), array("b"), array("b"), array("q")
    for way in processor:
        if not way.is_way():
            continue
        props = way_speed(way.tags)
        if props is None:
            continue
        n = 0
        for nd in way.nodes:
            if nd.location.valid():
                ids.append(nd.ref)
                lon.append(nd.location.lon)
                lat.append(nd.location.lat)
                n += 1
        if n >= 2:
            speed.append(props[0])
            local.append(props[1])
            ferry.append(props[2])
            lengths.append(n)
        elif n == 1:
            del ids[-1], lon[-1], lat[-1]
    way_props = np.stack([np.frombuffer(speed, np.float32), np.frombuffer(local, np.int8), np.frombuffer(ferry, np.int8)], axis=1)
    return (np.frombuffer(ids, np.int64), np.frombuffer(lon, np.float64), np.frombuffer(lat, np.float64),
            np.frombuffer(lengths, np.int64), way_props)


def build_graph() -> dict[str, np.ndarray]:
    ids, lon, lat, lengths, props = read_ways()
    uniq, first, node = np.unique(ids, return_index=True, return_inverse=True)
    x, y = Transformer.from_crs(config.CRS_WGS84, config.CRS_METRIC, always_xy=True).transform(lon[first], lat[first])
    way_of_ref = np.repeat(np.arange(len(lengths)), lengths)
    starts = np.cumsum(lengths) - lengths
    is_edge = np.ones(len(ids), dtype=bool)
    is_edge[np.cumsum(lengths) - 1] = False  # sidste knude i en vej har ingen efterfølger
    a = np.flatnonzero(is_edge)
    u, v, w = node[a], node[a + 1], way_of_ref[a]
    meters = np.hypot(x[u] - x[v], y[u] - y[v])
    minutes = meters / (props[w, 0] * 1000 / 60)
    ferry_start = np.isin(a, starts) & (props[w, 2] == 1)
    minutes = minutes + np.where(ferry_start, FERRY_WAIT_MIN, 0.0)
    local = np.zeros(len(uniq), dtype=bool)
    local_ref = props[way_of_ref, 1] == 1
    local[node[local_ref]] = True
    return {"x": np.asarray(x), "y": np.asarray(y), "u": u.astype(np.int32), "v": v.astype(np.int32),
            "minutes": minutes.astype(np.float32), "local": local}


def load_graph() -> dict[str, np.ndarray]:
    if GRAPH_NPZ.exists():
        return dict(np.load(GRAPH_NPZ))
    g = build_graph()
    np.savez_compressed(GRAPH_NPZ, **g)
    return g


def to_csr(g: dict[str, np.ndarray]) -> csr_matrix:
    """Uorienteret graf; ligger flere veje mellem samme to knuder, bruges den hurtigste."""
    n = len(g["x"])
    lo, hi = np.minimum(g["u"], g["v"]).astype(np.int64), np.maximum(g["u"], g["v"]).astype(np.int64)
    keep = lo != hi
    lo, hi, t = lo[keep], hi[keep], g["minutes"][keep]
    order = np.lexsort((t, hi, lo))
    lo, hi, t = lo[order], hi[order], t[order]
    first = np.ones(len(lo), dtype=bool)
    first[1:] = (lo[1:] != lo[:-1]) | (hi[1:] != hi[:-1])
    return coo_matrix((np.maximum(t[first], 1e-4), (lo[first], hi[first])), shape=(n, n)).tocsr()


def main_component(graph: csr_matrix) -> np.ndarray:
    """Knuder i det største sammenhængende vejnet. Færgerne forbinder alle beboede øer til det;
    resten er små afbrudte stumper (parkeringspladser o.l.), som celler ikke må kobles på."""
    _, label = connected_components(graph, directed=False)
    return label == np.bincount(label).argmax()


def snap(g: dict[str, np.ndarray], pts: np.ndarray, allowed: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Nærmeste tilladte lokale vejknude og afstanden dertil (m)."""
    idx = np.flatnonzero(g["local"] & allowed)
    dist, i = cKDTree(np.column_stack([g["x"][idx], g["y"][idx]])).query(pts, k=1, workers=-1)
    return idx[i], dist


def connect_minutes(meters: np.ndarray) -> np.ndarray:
    return config.ROUTE_FACTOR * meters / (CONNECT_KMH * 1000 / 60)


def drive_from_bases(g: dict[str, np.ndarray], base_xy: np.ndarray, target_xy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Køretid (min) fra nærmeste base til hvert punkt og indeks for den base."""
    graph = to_csr(g)
    allowed = main_component(graph)
    base_nodes, base_snap = snap(g, base_xy, allowed)
    dist, _, source = dijkstra(graph, directed=False, indices=base_nodes, min_only=True, return_predecessors=True)
    cell_nodes, cell_snap = snap(g, target_xy, allowed)
    base_of_node = np.full(len(g["x"]), -1, dtype=np.int32)
    base_of_node[base_nodes[::-1]] = np.arange(len(base_nodes))[::-1]
    src = source[cell_nodes]
    base_idx = np.where(src >= 0, base_of_node[np.maximum(src, 0)], -1)  # scipy markerer "ingen vej" med negativ kilde
    start = np.where(base_idx >= 0, connect_minutes(base_snap[np.maximum(base_idx, 0)]), np.inf)
    return dist[cell_nodes] + connect_minutes(cell_snap) + start, base_idx


def main() -> None:
    g = load_graph()
    print(f"Vejnet: {len(g['x']):,} knuder, {len(g['u']):,} vejstykker")
    bases = load_bases()
    demand = pd.read_parquet(config.PROCESSED / "demand_grid.parquet", columns=["gx", "gy", "x", "y", "pop", "kommune"])
    minutes, base_idx = drive_from_bases(g, bases[["x", "y"]].to_numpy(), demand[["x", "y"]].to_numpy())
    out = pd.DataFrame({"gx": demand["gx"], "gy": demand["gy"], "koertid_min": minutes.astype(np.float32),
                        "base_idx": base_idx.astype(np.int16)})
    out.to_parquet(DRIVE_PARQUET, index=False)
    pop = demand["pop"].to_numpy()
    if not np.isfinite(minutes).all():
        raise ValueError("Beboede celler uden vejforbindelse til en ambulancebase")
    per_kommune = demand.assign(t=minutes * pop).groupby("kommune")[["t", "pop"]].sum()
    print("Befolkningsvægtet køretid fra nærmeste base pr. kommune (min):")
    print((per_kommune["t"] / per_kommune["pop"]).sort_values().round(1).to_string())


if __name__ == "__main__":
    main()
