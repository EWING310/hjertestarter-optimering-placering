"""Fremskrivning: hvordan ændrer hjertestop-risikoen sig pr. kommune frem mod målåret?

Bruger Danmarks Statistiks befolkningsfremskrivning (FRKM126) og samme
aldersvægtning som resten af analysen (60+ vægtes RISK_RATIO_60PLUS gange).
"""

from __future__ import annotations

import pandas as pd
import requests

from src import config

DST_URL = "https://api.statbank.dk/v1/data"
TABLE = "FRKM126"
BASE_YEAR = 2026
TARGET_YEAR = 2036


def fetch_projection(years: tuple[int, int] = (BASE_YEAR, TARGET_YEAR)) -> pd.DataFrame:
    payload = {
        "table": TABLE,
        "format": "BULK",
        "lang": "da",
        "variables": [
            {"code": "KOMMUNEDK", "values": ["*"]},
            {"code": "ALDER", "values": ["*"]},
            {"code": "KØN", "values": ["*"]},
            {"code": "Tid", "values": [str(y) for y in years]},
        ],
    }
    resp = requests.post(DST_URL, json=payload, timeout=180)
    resp.raise_for_status()
    rows = [line.split(";") for line in resp.text.strip().splitlines()]
    df = pd.DataFrame(rows[1:], columns=rows[0])
    df = df[df["ALDER"] != "Alder i alt"]
    return pd.DataFrame(
        {
            "kommune": df["KOMMUNEDK"],
            "alder": df["ALDER"].str.extract(r"(\d+)")[0].astype(int),
            "aar": df["TID"].astype(int),
            "antal": pd.to_numeric(df["INDHOLD"]),
        }
    )


def growth_factors(proj: pd.DataFrame, ratio_60plus: float, base: int, target: int) -> pd.DataFrame:
    """Vækstfaktor for befolkning, 60+ og aldersvægtet risiko pr. kommune (target/base)."""
    p = proj.assign(
        pop60=proj["antal"].where(proj["alder"] >= 60, 0),
        risk=proj["antal"].where(proj["alder"] < 60, proj["antal"] * ratio_60plus),
    )
    agg = p.groupby(["kommune", "aar"])[["antal", "pop60", "risk"]].sum().unstack("aar")
    return pd.DataFrame(
        {
            "vaekst_befolkning": agg[("antal", target)] / agg[("antal", base)],
            "vaekst_60plus": agg[("pop60", target)] / agg[("pop60", base)],
            "vaekst_risiko": agg[("risk", target)] / agg[("risk", base)],
        }
    ).reset_index()


def main() -> None:
    proj = fetch_projection()
    growth = growth_factors(proj, config.RISK_RATIO_60PLUS, BASE_YEAR, TARGET_YEAR)
    growth.to_csv(config.PROCESSED / "kommune_vaekst_2026_2036.csv", index=False)
    print(growth.sort_values("vaekst_risiko", ascending=False).head(10).round(3))
    print(growth.sort_values("vaekst_risiko").head(5).round(3))


if __name__ == "__main__":
    main()
