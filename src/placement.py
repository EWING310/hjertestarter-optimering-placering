"""Forslag til nye og opgraderede hjertestartere med samme målestok for by og land."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from src import config
from src.fair_optimize import FairPick, build_neighbourhoods, fair_greedy
from src.load import unproject, xy
from src.population import attach_municipality
from src.survival import reach_radius, time_to_aed
from src.urbanization import urban_class

CANDIDATE_BLOCK_M = 100  # én kandidat pr. 100 m blok (den mest befolkede 50 m celle)
UPGRADE_SNAP_M = 75
UPGRADE_ADVICE = {
    "åbningstid": "Gør eksisterende hjertestarter døgntilgængelig (har i dag åbningstid)",
    "utilgaengelig": "Genaktivér registreret hjertestarter (står i dag som utilgængelig)",
}
EMS = np.asarray(config.EMS_MIN_BY_CLASS)


def class_shares(demand: pd.DataFrame) -> np.ndarray:
    """Hver urbaniseringsklasses andel af de forventede hjertestop i 2036."""
    by_class = demand.groupby("klasse")[config.OPT_WEIGHT].sum().reindex(range(len(config.URBAN_CLASSES)), fill_value=0)
    return (by_class / by_class.sum()).to_numpy()


def candidate_sites(demand: pd.DataFrame, pois: pd.DataFrame) -> pd.DataFrame:
    """Beboede celler (én pr. 100 m blok) og navngivne offentlige steder, hvor et nyt sted kan forkorte tiden."""
    min_useful = time_to_aed(np.array([50.0]))[0]
    d = demand[(demand["pop"] >= 1) & (demand["t_now"] > min_useful)]
    block = (np.floor(d["x"] / CANDIDATE_BLOCK_M).astype(np.int64) * 10_000_000 + np.floor(d["y"] / CANDIDATE_BLOCK_M).astype(np.int64))
    cells = d.loc[d.groupby(block)["pop"].idxmax(), ["x", "y", "klasse"]].assign(kilde="bolig", poi_idx=-1)
    poi_tree = cKDTree(xy(demand))
    _, nearest = poi_tree.query(xy(pois), k=1)
    useful = demand["t_now"].to_numpy()[nearest] > min_useful
    p = pois.loc[useful, ["x", "y"]].assign(klasse=demand["klasse"].to_numpy()[nearest[useful]], kilde="offentligt sted")
    p["poi_idx"] = p.index
    return pd.concat([cells, p], ignore_index=True)


def run(demand: pd.DataFrame, sites: pd.DataFrame, k: int, shares: np.ndarray | None) -> list[FairPick]:
    radii = reach_radius(EMS[sites["klasse"].to_numpy()])
    hoods = build_neighbourhoods(xy(demand), xy(sites), radii)
    return fair_greedy(
        demand[config.OPT_WEIGHT].to_numpy(), demand["t_now"].to_numpy(), sites["klasse"].to_numpy(), hoods, k, shares
    )


def pick_effects(picks: list[FairPick], demand: pd.DataFrame, sites: pd.DataFrame) -> pd.DataFrame:
    """Effekt pr. forslag: ekstra overlevere, beboere med kortere tid og nye inden for 100 m."""
    pop, pop60, risk = (demand[c].to_numpy() for c in ("pop", "pop60", "risk"))
    dxy, d_now, t_now = xy(demand), demand["dist_247"].to_numpy(), demand["t_now"].to_numpy()
    rows = []
    for p in picks:
        cells = np.asarray(p.improved_cells, dtype=np.int64)
        delta = np.asarray(p.delta_survival)
        site = sites.iloc[p.candidate]
        d_site = np.hypot(dxy[cells, 0] - site["x"], dxy[cells, 1] - site["y"])
        newly_100 = (d_site <= 100) & (d_now[cells] > 100)
        rows.append(
            {
                "rang": p.rank,
                "klasse": config.URBAN_CLASSES[p.klasse],
                "x": site["x"],
                "y": site["y"],
                "poi_idx": site["poi_idx"],
                "ekstra_overlevere_pr_aar": round(config.SHOCKABLE_SHARE * float((risk[cells] * delta).sum()), 4),
                "ekstra_overlevere_pr_aar_2036": round(config.SHOCKABLE_SHARE * p.gain, 4),
                "beboere_kortere_tid": round(float(pop[cells].sum())),
                "heraf_60plus": round(float(pop60[cells].sum())),
                "nye_beboere_inden_for_100m": round(float(pop[cells][newly_100].sum())),
                "tid_til_stoed_foer_min": round(float(np.average(t_now[cells], weights=pop[cells] + 1e-9)), 1) if len(cells) else np.nan,
            }
        )
    return pd.DataFrame(rows)


def describe(picks: list[FairPick], demand: pd.DataFrame, sites: pd.DataFrame, pois: pd.DataFrame, upgradable: pd.DataFrame) -> pd.DataFrame:
    out = pick_effects(picks, demand, sites)
    lon, lat = unproject(out["x"].to_numpy(), out["y"].to_numpy())
    out.insert(1, "lat", lat.round(6))
    out.insert(2, "lon", lon.round(6))
    out.insert(1, "rang_i_klasse", out.groupby("klasse").cumcount() + 1)
    out["kommune"] = attach_municipality(out).to_numpy()
    out = out.join(nearest_host(out, pois)).join(upgrade_advice(out, upgradable))
    out["google_maps"] = "https://www.google.com/maps?q=" + out["lat"].astype(str) + "," + out["lon"].astype(str)
    return out.drop(columns=["x", "y", "poi_idx"])


def nearest_host(sites: pd.DataFrame, pois: pd.DataFrame) -> pd.DataFrame:
    dist, idx = cKDTree(xy(pois)).query(xy(sites), k=1)
    host = pois.iloc[idx].reset_index(drop=True)
    limit = sites["klasse"].map(dict(zip(config.URBAN_CLASSES, config.HOST_SNAP_BY_CLASS_M, strict=True))).to_numpy()
    ok = dist <= limit
    fallback = np.where(sites["klasse"] == "Land", "Udendørs skab centralt i bebyggelsen", "Boligområde (udendørs skab / opgang / boligforening)")
    return pd.DataFrame(
        {
            "foreslaaet_vaert": np.where(ok, host["navn"], fallback),
            "vaert_type": np.where(ok, host["kategori"], "Bolig"),
            "vaert_adresse": np.where(ok, (host["adresse"] + " " + host["postnr"] + " " + host["by"]).str.strip(), ""),
            "afstand_til_vaert_m": np.where(ok, dist.round(0), np.nan),
        }
    )


def upgrade_advice(sites: pd.DataFrame, upgradable: pd.DataFrame) -> pd.DataFrame:
    dist, idx = cKDTree(xy(upgradable)).query(xy(sites), k=1)
    near = upgradable.iloc[idx].reset_index(drop=True)
    return pd.DataFrame(
        {
            "naermeste_opgraderbare_m": dist.round(0),
            "anbefaling": np.where(dist <= UPGRADE_SNAP_M, near["kategori"].map(UPGRADE_ADVICE), "Ny døgnåben hjertestarter"),
        }
    )


def upgradable_sites(upgradable: pd.DataFrame) -> pd.DataFrame:
    return upgradable.assign(klasse=urban_class(upgradable["x"].to_numpy(), upgradable["y"].to_numpy()), poi_idx=-1)


def conversions(demand: pd.DataFrame, upgradable: pd.DataFrame, shares: np.ndarray, k: int = 1000) -> pd.DataFrame:
    """Eksisterende hjertestartere med åbningstid/utilgængelig, prioriteret som de nye steder."""
    sites = upgradable_sites(upgradable).reset_index(drop=True)
    picks = run(demand, sites, k, shares)
    eff = pick_effects(picks, demand, sites)
    chosen = sites.iloc[[p.candidate for p in picks]].reset_index(drop=True)
    return eff.drop(columns=["x", "y", "poi_idx"]).assign(
        hjertestarter_id=chosen["id"].to_numpy(),
        nuvaerende_adgang=chosen["kategori"].to_numpy(),
        kommune=chosen["kommune"].to_numpy(),
        lat=chosen["lat"].round(6).to_numpy(),
        lon=chosen["lon"].round(6).to_numpy(),
    )
