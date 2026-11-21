"""Kør hele analysen: adgang til hjertestartere for by og land, kommuner og forslag til placeringer."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from src import config, placement
from src.coverage import coverage_share, nearest_distance
from src.load import load_aeds, load_demand, load_pois, unproject, xy
from src.population import attach_municipality
from src.ambulance import load_bases
from src.ems_model import PARAMS_JSON, ambulance_times
from src.survival import survival, time_to_defib, time_to_ems
from src.urbanization import urban_class

ACCESS_CELL_M = 250  # aggregering af tid til første stød til kortet
MILESTONES = (50, 100, 250, 500, 1000, 2000)


def enrich_demand(demand: pd.DataFrame, aeds_247: pd.DataFrame, aeds_any: pd.DataFrame) -> pd.DataFrame:
    klasse = urban_class(demand["x"].to_numpy(), demand["y"].to_numpy())
    dist_247 = nearest_distance(xy(demand), xy(aeds_247))
    ems = ambulance_times(demand)
    t_ems = time_to_ems(ems["responstid_min"].to_numpy())
    t_now = time_to_defib(dist_247, t_ems)
    return demand.join(ems).assign(
        klasse=klasse,
        t_ems=t_ems,
        dist_247=dist_247,
        dist_any=nearest_distance(xy(demand), xy(aeds_any)),
        t_now=t_now,
        s_now=survival(t_now),
    )


def national_coverage(demand: pd.DataFrame) -> list[dict]:
    rows = []
    for label, col in (("døgntilgængelige", "dist_247"), ("inkl. åbningstid", "dist_any")):
        dist = demand[col].to_numpy()
        for r in config.REPORT_RADII_M:
            rows.append(
                {
                    "hjertestartere": label,
                    "radius_m": r,
                    "befolkning_daekket_pct": round(100 * coverage_share(dist, demand["pop"].to_numpy(), r), 1),
                    "60plus_daekket_pct": round(100 * coverage_share(dist, demand["pop60"].to_numpy(), r), 1),
                    "risiko_daekket_pct": round(100 * coverage_share(dist, demand["risk"].to_numpy(), r), 1),
                }
            )
    return rows


def _weighted_median(values: np.ndarray, weights: np.ndarray) -> float:
    order = np.argsort(values)
    cum = np.cumsum(weights[order])
    return float(values[order][np.searchsorted(cum, cum[-1] / 2)])


def group_access(d: pd.DataFrame) -> pd.Series:
    """Adgangsmål for en gruppe beboere (by-klasse eller kommune)."""
    pop, risk = d["pop"].to_numpy(), d["risk"].to_numpy()
    return pd.Series(
        {
            "befolkning": pop.sum(),
            "befolkning_60plus": d["pop60"].sum(),
            "hjertestop_pr_aar": risk.sum(),
            "hjertestop_pr_aar_2036": d["risk_2036"].sum(),
            "daekning_100m_pct": 100 * pop[d["dist_247"] <= 100].sum() / pop.sum(),
            "daekning_500m_pct": 100 * pop[d["dist_247"] <= 500].sum() / pop.sum(),
            "median_afstand_m": _weighted_median(d["dist_247"].to_numpy(), pop),
            "median_ambulance_responstid_min": _weighted_median(d["responstid_min"].to_numpy(), pop),
            "median_tid_til_stoed_min": _weighted_median(d["t_now"].to_numpy(), pop),
            "overlevelse_stoedbar_pct": 100 * np.average(d["s_now"], weights=risk),
            "forventede_overlevere_pr_aar": config.SHOCKABLE_SHARE * float((risk * d["s_now"]).sum()),
        }
    )


def class_table(demand: pd.DataFrame) -> pd.DataFrame:
    t = demand.groupby("klasse").apply(group_access, include_groups=False)
    t.index = [config.URBAN_CLASSES[i] for i in t.index]
    t["andel_af_hjertestop_pct"] = 100 * t["hjertestop_pr_aar_2036"] / t["hjertestop_pr_aar_2036"].sum()
    return t.round(2)


def municipality_table(demand: pd.DataFrame, aeds: pd.DataFrame, growth: pd.DataFrame) -> pd.DataFrame:
    t = demand.groupby("kommune").apply(group_access, include_groups=False)
    land_pop = demand[demand["klasse"] == 2].groupby("kommune")["pop"].sum().reindex(t.index).fillna(0)
    t["andel_land_pct"] = 100 * land_pop / t["befolkning"]
    counts = aeds.groupby(["kommune", "kategori"]).size().unstack(fill_value=0)
    t = t.join(counts).fillna(0)
    t["døgntilgængelige"] = t[[c for c in config.AED_CATEGORIES_24_7 if c in t]].sum(axis=1)
    t = t.join(growth.set_index("kommune")[["vaekst_60plus", "vaekst_risiko"]])
    return t.sort_values("median_tid_til_stoed_min", ascending=False).round(3)


def public_places_without_aed(pois: pd.DataFrame, aeds_any: pd.DataFrame, demand: pd.DataFrame) -> pd.DataFrame:
    """Offentlige steder med mange mennesker uden nogen tilgængelig hjertestarter inden for 100 m."""
    busy = pois[pois["offentlig_vaegt"] >= 4].copy()
    busy["afstand_til_hjertestarter_m"] = nearest_distance(xy(busy), xy(aeds_any)).round(0)
    hoods = cKDTree(xy(demand)).query_ball_point(xy(busy), r=500, workers=-1)
    pop = demand["pop"].to_numpy()
    busy["beboere_inden_for_500m"] = [round(float(pop[h].sum())) for h in hoods]
    gap = busy[busy["afstand_til_hjertestarter_m"] > config.PRIMARY_RADIUS_M].copy()
    gap["kommune"] = attach_municipality(gap).to_numpy()
    gap["klasse"] = [config.URBAN_CLASSES[k] for k in urban_class(gap["x"].to_numpy(), gap["y"].to_numpy())]
    cols = [
        "kategori", "navn", "kommune", "klasse", "adresse", "postnr", "by", "lat", "lon",
        "afstand_til_hjertestarter_m", "beboere_inden_for_500m", "offentlig_vaegt",
    ]
    return gap.sort_values(["offentlig_vaegt", "beboere_inden_for_500m"], ascending=False)[cols]


def access_grid(demand: pd.DataFrame) -> pd.DataFrame:
    """Tid til første stød (befolkningsvægtet) pr. 250 m celle - samme skala for by og land."""
    s = ACCESS_CELL_M
    d = demand.assign(
        bx=np.floor(demand["x"] / s), by=np.floor(demand["y"] / s),
        tw=demand["t_now"] * demand["pop"], dw=demand["dist_247"] * demand["pop"], ew=demand["responstid_min"] * demand["pop"],
    )
    agg = d.groupby(["bx", "by"], as_index=False).agg(
        pop=("pop", "sum"), pop60=("pop60", "sum"), risk=("risk", "sum"), tw=("tw", "sum"), dw=("dw", "sum"),
        ew=("ew", "sum"), klasse=("klasse", "first"),
    )
    base = d.loc[d.groupby(["bx", "by"])["pop"].idxmax(), ["bx", "by", "base_idx"]]
    agg = agg.merge(base, on=["bx", "by"])
    agg = agg[agg["pop"] > 0]
    lon, lat = unproject(((agg["bx"] + 0.5) * s).to_numpy(), ((agg["by"] + 0.5) * s).to_numpy())
    agg = agg.assign(t=agg["tw"] / agg["pop"], d=agg["dw"] / agg["pop"], e=agg["ew"] / agg["pop"], lat=lat.round(5), lon=lon.round(5))
    return agg.drop(columns=["bx", "by", "tw", "dw", "ew"])


def ambulance_summary() -> dict:
    calib = json.loads(PARAMS_JSON.read_text())
    bases = load_bases()
    return {
        "baser": int(len(bases)),
        "baser_pr_region": bases["region"].value_counts().to_dict(),
        "geokodning": bases["geokodning"].value_counts().to_dict(),
        "model": calib["params"],
        "rmse_andel": calib["rmse_andel"],
        "t_ekstra_min": config.T_EMS_EXTRA_MIN,
    }


def milestones(props: pd.DataFrame) -> dict:
    out = {}
    for n in MILESTONES:
        top = props.head(n)
        if len(top) < n:
            break
        out[n] = {
            "ekstra_overlevere_pr_aar": round(float(top["ekstra_overlevere_pr_aar"].sum()), 2),
            "ekstra_overlevere_pr_aar_2036": round(float(top["ekstra_overlevere_pr_aar_2036"].sum()), 2),
            "beboere_kortere_tid": int(top["beboere_kortere_tid"].sum()),
            "fordeling": top["klasse"].value_counts().reindex(config.URBAN_CLASSES, fill_value=0).astype(int).to_dict(),
        }
    return out


def _old_distribution() -> dict:
    path = config.PROCESSED / "gammel_metode_fordeling.json"
    return json.loads(path.read_text()) if path.exists() else {}


def main() -> None:
    config.OUTPUT.mkdir(parents=True, exist_ok=True)
    demand, aeds, pois = load_demand(), load_aeds(), load_pois()
    aeds["kommune"] = attach_municipality(aeds).to_numpy()
    aeds_247 = aeds[aeds["kategori"].isin(config.AED_CATEGORIES_24_7)]
    aeds_any = aeds[aeds["kategori"].isin(config.AED_CATEGORIES_ANY)]
    upgradable = aeds[aeds["kategori"].isin(config.AED_CATEGORIES_UPGRADABLE)].reset_index(drop=True)
    demand = enrich_demand(demand, aeds_247, aeds_any)
    growth = pd.read_csv(config.PROCESSED / "kommune_vaekst_2026_2036.csv")

    shares = placement.class_shares(demand)
    sites = placement.candidate_sites(demand, pois)
    print(f"Kandidatsteder: {len(sites):,}; kvoter by/mindre by/land: {np.round(shares, 3)}")
    fair = placement.describe(placement.run(demand, sites, config.N_PROPOSALS, shares), demand, sites, pois, upgradable)
    efficient = placement.pick_effects(placement.run(demand, sites, config.N_PROPOSALS, None), demand, sites)
    conv = placement.conversions(demand, upgradable, shares)
    public = public_places_without_aed(pois, aeds_any, demand)
    classes = class_table(demand)

    fair.to_csv(config.OUTPUT / "forslag_nye_hjertestartere.csv", index=False)
    conv.to_csv(config.OUTPUT / "forslag_goer_doegnaaben.csv", index=False)
    classes.to_csv(config.OUTPUT / "by_og_land.csv")
    municipality_table(demand, aeds, growth).to_csv(config.OUTPUT / "kommuner_ranking.csv")
    public.to_csv(config.OUTPUT / "offentlige_steder_uden_hjertestarter.csv", index=False)
    access_grid(demand).to_parquet(config.PROCESSED / "access_250m.parquet", index=False)
    aeds.to_parquet(config.PROCESSED / "aeds_med_kommune.parquet", index=False)
    efficient[["rang", "klasse", "ekstra_overlevere_pr_aar", "ekstra_overlevere_pr_aar_2036"]].to_csv(
        config.PROCESSED / "uden_kvote.csv", index=False
    )

    summary = {
        "hjertestartere_registreret": int(len(aeds)),
        "hjertestartere_pr_kategori": aeds["kategori"].value_counts().to_dict(),
        "befolkning_model": int(demand["pop"].sum()),
        "befolkning_60plus_model": int(demand["pop60"].sum()),
        "national_daekning": national_coverage(demand),
        "by_og_land": classes.reset_index(names="klasse").to_dict("records"),
        "kvoter": dict(zip(config.URBAN_CLASSES, np.round(shares, 4).tolist(), strict=True)),
        "effekt_med_kvote": milestones(fair),
        "effekt_uden_kvote": milestones(efficient),
        "gammel_metode_fordeling": _old_distribution(),
        "ambulance": ambulance_summary(),
        "forventede_overlevere_pr_aar_i_dag": round(config.SHOCKABLE_SHARE * float((demand["risk"] * demand["s_now"]).sum()), 1),
        "offentlige_steder_uden_hjertestarter_100m": int(len(public)),
    }
    (config.OUTPUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    keys = ("kvoter", "effekt_med_kvote", "effekt_uden_kvote", "gammel_metode_fordeling")
    print(json.dumps({k: summary[k] for k in keys}, ensure_ascii=False, indent=1))
    print(classes.T)


if __name__ == "__main__":
    main()
