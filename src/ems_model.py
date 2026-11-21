"""Ambulancens responstid pr. celle: køretid fra nærmeste base, kalibreret mod målte responstider.

Ambulancen holder ofte ikke på basen, når et hjertestop sker, og udkald tager tid.
Derfor bruges køretiden kun som afstandsmål og skaleres til virkelige responstider:

    median responstid = a + b · køretid fra nærmeste base

med log-normal spredning (sigma) omkring medianen fra gang til gang. a, b og sigma
fittes, så modellens andel af kørsel A fremme inden for 5/10/15 min rammer det, regionerne
måler (Danske Regioner, alle fem regioner) og andelen inden for 15 min pr. kommune i
Region Syddanmark. Samme formel gælder for alle borgere i by og på land.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import ndtr

from src import config
from src.ambulance import KOMMUNE_REGION
from src.road_network import DRIVE_PARQUET

REGION_OBS = config.RAW / "responstider_regioner.csv"
KOMMUNE_OBS = config.RAW / "responstider_syddanmark_kommuner.csv"
PARAMS_JSON = config.PROCESSED / "ems_kalibrering.json"
FIT_CSV = config.OUTPUT / "ambulance_kalibrering.csv"
THRESHOLDS = (5, 10, 15)
BIN_MIN = 0.1
MAX_DRIVE_MIN = 90.0


@dataclass(frozen=True)
class EmsParams:
    a: float  # min: udkald og typisk afstand fra ambulancens faktiske position
    b: float  # skalering af køretiden
    sigma: float  # log-spredning fra gang til gang


def median_response(drive_min: np.ndarray, p: EmsParams) -> np.ndarray:
    return p.a + p.b * np.asarray(drive_min, dtype=float)


def share_within(drive_min: np.ndarray, weights: np.ndarray, limit: float, p: EmsParams) -> float:
    """Vægtet andel af udrykninger fremme inden for `limit` minutter."""
    z = (np.log(limit) - np.log(median_response(drive_min, p))) / p.sigma
    return float(np.sum(weights * ndtr(z)) / np.sum(weights))


def observations() -> pd.DataFrame:
    """Målte andele som (gruppe, tærskel, andel), gennemsnit over kvartaler."""
    reg = pd.read_csv(REGION_OBS)
    reg["gruppe"] = reg["region"].str.removeprefix("Region ")
    reg = reg.melt(id_vars=["gruppe", "kvartal"], value_vars=[f"inden_{t}" for t in THRESHOLDS], var_name="t", value_name="pct")
    reg["graense"] = reg["t"].str.removeprefix("inden_").astype(int)
    reg = reg.groupby(["gruppe", "graense"], as_index=False)["pct"].mean().assign(niveau="region")
    kom = pd.read_csv(KOMMUNE_OBS)
    kom = kom.assign(w=kom["antal"] * kom["andel_15"]).groupby("kommune", as_index=False)[["w", "antal"]].sum()
    kom = pd.DataFrame({"gruppe": kom["kommune"], "graense": 15, "pct": kom["w"] / kom["antal"], "niveau": "kommune"})
    return pd.concat([reg, kom], ignore_index=True).assign(andel=lambda d: d["pct"] / 100).drop(columns="pct")


def binned_groups(drive_min: np.ndarray, weights: np.ndarray, kommune: np.ndarray, groups: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """Vægt pr. køretidsinterval for hver gruppe (region eller kommune) - gør fittet hurtigt."""
    edges = np.arange(0, MAX_DRIVE_MIN + BIN_MIN, BIN_MIN)
    centers = np.minimum(edges[:-1] + BIN_MIN / 2, MAX_DRIVE_MIN)
    region = pd.Series(kommune).map(KOMMUNE_REGION).to_numpy()
    idx = np.minimum((drive_min / BIN_MIN).astype(int), len(centers) - 1)
    mat = np.zeros((len(groups), len(centers)))
    for i, gname in enumerate(groups):
        mask = (region == gname) | (kommune == gname)
        mat[i] = np.bincount(idx[mask], weights=weights[mask], minlength=len(centers))
    return centers, mat


def fit(drive_min: np.ndarray, weights: np.ndarray, kommune: np.ndarray) -> tuple[EmsParams, pd.DataFrame]:
    obs = observations()
    groups = sorted(obs["gruppe"].unique())
    centers, mat = binned_groups(drive_min, weights, kommune, groups)
    gi = obs["gruppe"].map({g: i for i, g in enumerate(groups)}).to_numpy()
    limits, target = obs["graense"].to_numpy(float), obs["andel"].to_numpy()

    def predict(p: EmsParams) -> np.ndarray:
        z = (np.log(limits)[:, None] - np.log(median_response(centers, p))[None, :]) / p.sigma
        return (mat[gi] * ndtr(z)).sum(axis=1) / mat[gi].sum(axis=1)

    def loss(theta: np.ndarray) -> float:
        return float(np.sum((predict(EmsParams(*theta)) - target) ** 2))

    res = minimize(loss, x0=np.array([4.0, 1.0, 0.4]), bounds=[(0.0, 15.0), (0.2, 5.0), (0.05, 1.5)], method="L-BFGS-B")
    if not res.success:
        raise RuntimeError(f"Kalibrering af ambulancetid fejlede: {res.message}")
    params = EmsParams(*(round(float(v), 4) for v in res.x))
    return params, obs.assign(model=predict(params)).round(4)


def load_params() -> EmsParams:
    return EmsParams(**json.loads(PARAMS_JSON.read_text())["params"])


def ambulance_times(demand: pd.DataFrame) -> pd.DataFrame:
    """Køretid, kalibreret median responstid og nærmeste base pr. efterspørgselscelle."""
    drive = pd.read_parquet(DRIVE_PARQUET)
    same = len(drive) == len(demand) and (drive["gx"].to_numpy() == demand["gx"].to_numpy()).all() \
        and (drive["gy"].to_numpy() == demand["gy"].to_numpy()).all()
    if not same:
        raise ValueError("ems_koertid.parquet passer ikke til demand_grid.parquet - kør src.road_network igen")
    minutes = drive["koertid_min"].to_numpy(float)
    return pd.DataFrame(
        {"koertid_min": minutes, "responstid_min": median_response(minutes, load_params()), "base_idx": drive["base_idx"].to_numpy()},
        index=demand.index,
    )


def main() -> None:
    demand = pd.read_parquet(config.PROCESSED / "demand_grid.parquet", columns=["pop", "kommune"])
    drive = pd.read_parquet(DRIVE_PARQUET)["koertid_min"].to_numpy(float)
    params, table = fit(drive, demand["pop"].to_numpy(), demand["kommune"].to_numpy())
    rmse = float(np.sqrt(np.mean((table["model"] - table["andel"]) ** 2)))
    config.OUTPUT.mkdir(parents=True, exist_ok=True)
    table.to_csv(FIT_CSV, index=False)
    PARAMS_JSON.write_text(json.dumps({"params": asdict(params), "rmse_andel": round(rmse, 4)}, indent=2))
    print(f"Median responstid = {params.a:.2f} + {params.b:.2f} · køretid; sigma = {params.sigma:.2f}; RMSE {100 * rmse:.1f} %-point")
    print(table[table["niveau"] == "region"].pivot(index="gruppe", columns="graense", values=["andel", "model"]).round(3))
    kom = table[table["niveau"] == "kommune"].assign(fejl=lambda d: d["model"] - d["andel"]).sort_values("fejl")
    print(kom[["gruppe", "andel", "model", "fejl"]].to_string(index=False))


if __name__ == "__main__":
    main()
