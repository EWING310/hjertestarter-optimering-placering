"""Byg den interaktive kortside.

Skriver output/hjertestarter_blindspots.html og en kopi til docs/index.html
(GitHub Pages). Baggrundskortet er kommunegrænser som vektorer og rastre
renderet her som PNG data-URI'er, så siden også virker hvor eksterne
kortfliser er blokeret. Ortofoto (Esri World Imagery) kan slås til, hvor
siden må hente fliser udefra.
"""

from __future__ import annotations

import base64
import io
import json

import numpy as np
import pandas as pd
from PIL import Image
from pyproj import Transformer

from src import config
from src.ambulance import load_bases
from src.ems_model import PARAMS_JSON
from src.population import load_municipalities

TEMPLATE = config.ROOT / "src" / "web" / "template.html"
LEAFLET_CSS = config.ROOT / "src" / "web" / "vendor" / "leaflet.css"
OUT_HTML = config.OUTPUT / "hjertestarter_blindspots.html"
PAGES_HTML = config.ROOT / "docs" / "index.html"

POP_PX_M = 300.0  # pixelstørrelse i Web Mercator-meter (~170 m på jorden)
POP_RGB = (122, 134, 153)  # mellemtone der kan ses på både lyst og mørkt kort
ACCESS_PX_M = 450.0  # ~250 m på jorden = adgangscellernes størrelse
# Sekventiel rampe (én tonefamilie, lys -> mørk) for tid til første stød
T_RAMP = ((0.0, (251, 213, 197)), (0.5, (232, 102, 74)), (1.0, (143, 29, 13)))
T_MIN, T_MAX = 4.0, 11.0
ACCESS_MIN_POP = 10  # 250 m celler med færre beboere vises kun i rastret
SIMPLIFY_M = 120


def _r(values: pd.Series, nd: int) -> list:
    return [round(float(v), nd) for v in values]


def _mercator_grid(x: np.ndarray, y: np.ndarray, px: float) -> tuple:
    mx, my = Transformer.from_crs(config.CRS_METRIC, "EPSG:3857", always_xy=True).transform(x, y)
    x0, x1, y0, y1 = mx.min() - px, mx.max() + px, my.min() - px, my.max() + px
    shape = (int((y1 - y0) / px) + 1, int((x1 - x0) / px) + 1)
    cells = (((y1 - my) / px).astype(int), ((mx - x0) / px).astype(int))
    (lon0, lon1), (lat0, lat1) = Transformer.from_crs("EPSG:3857", config.CRS_WGS84, always_xy=True).transform([x0, x1], [y0, y1])
    return shape, cells, [[lat0, lon0], [lat1, lon1]]


def _png(rgba: np.ndarray) -> str:
    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def density_raster(x: np.ndarray, y: np.ndarray, values: np.ndarray) -> dict:
    """Befolkningstæthed som ét farvetonet raster; alfa følger log(antal)."""
    shape, cells, bounds = _mercator_grid(x, y, POP_PX_M)
    grid = np.zeros(shape)
    np.add.at(grid, cells, values)
    rgba = np.zeros((*shape, 4), dtype=np.uint8)
    rgba[..., :3] = POP_RGB
    rgba[..., 3] = (np.clip(np.log10(grid + 1) / np.log10(3000), 0, 1) ** 0.8 * 235).astype(np.uint8)
    return {"png": _png(rgba), "bounds": bounds}


def _ramp(u: np.ndarray) -> np.ndarray:
    stops = np.array([s for s, _ in T_RAMP])
    cols = np.array([c for _, c in T_RAMP], dtype=float)
    return np.stack([np.interp(u, stops, cols[:, i]) for i in range(3)], axis=-1)


def access_raster(access: pd.DataFrame) -> dict:
    """Befolkningsvægtet tid til første stød pr. pixel - samme skala for by og land."""
    x, y = Transformer.from_crs(config.CRS_WGS84, config.CRS_METRIC, always_xy=True).transform(access["lon"].to_numpy(), access["lat"].to_numpy())
    shape, cells, bounds = _mercator_grid(np.asarray(x), np.asarray(y), ACCESS_PX_M)
    pop, tw = np.zeros(shape), np.zeros(shape)
    np.add.at(pop, cells, access["pop"].to_numpy())
    np.add.at(tw, cells, (access["t"] * access["pop"]).to_numpy())
    t = np.divide(tw, pop, out=np.zeros(shape), where=pop > 0)
    rgba = np.zeros((*shape, 4), dtype=np.uint8)
    rgba[..., :3] = _ramp(np.clip((t - T_MIN) / (T_MAX - T_MIN), 0, 1)).astype(np.uint8)
    alpha = 110 + 120 * np.clip(np.log10(pop + 1) / np.log10(800), 0, 1)
    rgba[..., 3] = np.where(pop > 0.5, alpha, 0).astype(np.uint8)
    return {"png": _png(rgba), "bounds": bounds, "tmin": T_MIN, "tmax": T_MAX}


def municipality_shapes() -> dict:
    kommuner = load_municipalities()
    kommuner["geometry"] = kommuner.geometry.simplify(SIMPLIFY_M, preserve_topology=True)
    gj = json.loads(kommuner.to_crs(config.CRS_WGS84).to_json(to_wgs84=True))
    for feat in gj["features"]:
        feat.pop("id", None)
        feat["geometry"]["coordinates"] = _round_coords(feat["geometry"]["coordinates"])
    return gj


def _round_coords(c):
    if isinstance(c[0], (float, int)):
        return [round(c[0], 4), round(c[1], 4)]
    return [_round_coords(x) for x in c]


def aed_layer(aeds: pd.DataFrame) -> dict:
    codes = {"døgnåben": 0, "bag_lås": 1, "åbningstid": 2, "utilgaengelig": 3}
    return {"lat": _r(aeds["lat"], 5), "lon": _r(aeds["lon"], 5), "k": aeds["kategori"].map(codes).tolist()}


def access_cells(access: pd.DataFrame) -> dict:
    a = access[access["pop"] >= ACCESS_MIN_POP]
    return {
        "lat": _r(a["lat"], 5), "lon": _r(a["lon"], 5), "pop": _r(a["pop"], 0), "pop60": _r(a["pop60"], 0),
        "t": _r(a["t"], 1), "d": _r(a["d"], 0), "k": a["klasse"].astype(int).tolist(),
        "e": _r(a["e"], 1), "b": a["base_idx"].astype(int).tolist(),
    }


def base_layer(bases: pd.DataFrame) -> list[dict]:
    cols = {"navn": "n", "region": "reg", "operatoer": "op", "basetype": "type", "geokodning": "geo", "lat": "lat", "lon": "lon"}
    return bases[list(cols)].rename(columns=cols).round({"lat": 5, "lon": 5}).to_dict("records")


PROPOSAL_COLS = {
    "rang": "r", "rang_i_klasse": "rk", "klasse": "kl", "lat": "lat", "lon": "lon",
    "ekstra_overlevere_pr_aar": "g", "ekstra_overlevere_pr_aar_2036": "g36", "beboere_kortere_tid": "pop",
    "heraf_60plus": "pop60", "nye_beboere_inden_for_100m": "n100", "tid_til_stoed_foer_min": "tb",
    "kommune": "kom", "foreslaaet_vaert": "host", "vaert_type": "type", "vaert_adresse": "addr",
    "ambulance_responstid_min": "te", "hurtigere_end_ambulancen_inden_for_m": "rr",
}


def proposals_records(p: pd.DataFrame) -> list[dict]:
    out = p[list(PROPOSAL_COLS)].rename(columns=PROPOSAL_COLS).fillna("")
    out["conv"] = p["anbefaling"].str.startswith(("Gør", "Genaktivér")).astype(int)
    return out.to_dict("records")


def conversion_records(c: pd.DataFrame) -> list[dict]:
    cols = {
        "rang": "r", "klasse": "kl", "lat": "lat", "lon": "lon", "kommune": "kom", "nuvaerende_adgang": "adg",
        "ekstra_overlevere_pr_aar": "g", "ekstra_overlevere_pr_aar_2036": "g36", "beboere_kortere_tid": "pop",
        "tid_til_stoed_foer_min": "tb", "ambulance_responstid_min": "te", "hurtigere_end_ambulancen_inden_for_m": "rr",
    }
    return c.head(500)[list(cols)].rename(columns=cols).to_dict("records")


def public_records(p: pd.DataFrame) -> list[dict]:
    cols = {"kategori": "cat", "navn": "name", "kommune": "kom", "klasse": "kl", "by": "by", "lat": "lat", "lon": "lon",
            "afstand_til_hjertestarter_m": "d", "beboere_inden_for_500m": "pop"}
    return p[list(cols)].rename(columns=cols).round({"lat": 5, "lon": 5}).to_dict("records")


def build_data() -> dict:
    out, proc = config.OUTPUT, config.PROCESSED
    demand = pd.read_parquet(proc / "demand_grid.parquet")
    access = pd.read_parquet(proc / "access_250m.parquet")
    proposals = pd.read_csv(out / "forslag_nye_hjertestartere.csv", keep_default_na=False)
    efficient = pd.read_csv(proc / "uden_kvote.csv")
    kommuner = pd.read_csv(out / "kommuner_ranking.csv")
    kom_cols = ["kommune", "befolkning", "andel_land_pct", "median_tid_til_stoed_min", "median_ambulance_responstid_min",
                "daekning_100m_pct", "daekning_500m_pct", "døgntilgængelige", "forventede_overlevere_pr_aar", "vaekst_60plus"]
    return {
        "summary": json.loads((out / "summary.json").read_text()),
        "curve": _r(proposals["ekstra_overlevere_pr_aar_2036"].cumsum(), 3),
        "curveFree": _r(efficient["ekstra_overlevere_pr_aar_2036"].cumsum(), 3),
        "proposals": proposals_records(proposals),
        "conversions": conversion_records(pd.read_csv(out / "forslag_goer_doegnaaben.csv")),
        "public": public_records(pd.read_csv(out / "offentlige_steder_uden_hjertestarter.csv", dtype={"postnr": str}, keep_default_na=False)),
        "kommuner": kommuner[kom_cols].round(3).to_dict("records"),
        "classes": list(config.URBAN_CLASSES),
        "bases": base_layer(load_bases()),
        "emsFit": json.loads(PARAMS_JSON.read_text()),
        "model": {
            "tAlarm": config.T_ALARM_MIN,
            "tEmsExtra": config.T_EMS_EXTRA_MIN,
            "speed": config.RETRIEVE_SPEED_M_PER_MIN,
            "route": config.ROUTE_FACTOR,
            "tCpr": config.T_CPR_MIN,
            "valenzuela": list(config.VALENZUELA),
        },
        "aeds": aed_layer(pd.read_parquet(proc / "aeds_med_kommune.parquet")),
        "cells": access_cells(access),
        "raster": density_raster(demand["x"].to_numpy(), demand["y"].to_numpy(), demand["pop"].to_numpy()),
        "accessRaster": access_raster(access),
        "outlines": municipality_shapes(),
    }


def main() -> None:
    data = build_data()
    html = TEMPLATE.read_text(encoding="utf-8")
    html = html.replace("/*__LEAFLET_CSS__*/", LEAFLET_CSS.read_text(encoding="utf-8"))
    html = html.replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    OUT_HTML.write_text(html, encoding="utf-8")
    PAGES_HTML.parent.mkdir(parents=True, exist_ok=True)
    PAGES_HTML.write_text("<!doctype html>\n<html lang=\"da\">\n<head>\n<meta charset=\"utf-8\">\n"
                          "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n"
                          + html + "\n</html>\n", encoding="utf-8")
    print(f"Skrev {OUT_HTML} ({OUT_HTML.stat().st_size / 1e6:.1f} MB) og {PAGES_HTML}")


if __name__ == "__main__":
    main()
