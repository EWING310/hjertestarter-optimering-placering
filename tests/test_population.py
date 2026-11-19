import pandas as pd
import pytest

from src.population import calibrate_to_municipalities


@pytest.mark.unit
def test_calibration_matches_official_totals_per_municipality():
    grid = pd.DataFrame(
        {"kommune": ["A", "A", "B"], "pop": [10.0, 30.0, 5.0], "pop60": [2.0, 6.0, 1.0]}
    )
    official = pd.DataFrame({"kommune": ["A", "B"], "pop_total": [80.0, 5.0], "pop_60plus": [24.0, 2.0]})

    out = calibrate_to_municipalities(grid, official)

    totals = out.groupby("kommune")[["pop", "pop60"]].sum()
    assert totals.loc["A", "pop"] == pytest.approx(80.0)
    assert totals.loc["A", "pop60"] == pytest.approx(24.0)
    assert totals.loc["B", "pop60"] == pytest.approx(2.0)
    assert out.loc[0, "pop"] / out.loc[1, "pop"] == pytest.approx(10.0 / 30.0)


@pytest.mark.unit
def test_calibration_never_lets_elderly_exceed_total():
    grid = pd.DataFrame({"kommune": ["A"], "pop": [10.0], "pop60": [9.0]})
    official = pd.DataFrame({"kommune": ["A"], "pop_total": [10.0], "pop_60plus": [20.0]})

    out = calibrate_to_municipalities(grid, official)

    assert (out["pop60"] <= out["pop"]).all()


@pytest.mark.unit
def test_calibration_keeps_cells_in_municipalities_without_official_data():
    grid = pd.DataFrame({"kommune": ["A", "Z"], "pop": [10.0, 3.0], "pop60": [1.0, 1.0]})
    official = pd.DataFrame({"kommune": ["A"], "pop_total": [20.0], "pop_60plus": [2.0]})

    out = calibrate_to_municipalities(grid, official)

    assert out.loc[1, "pop"] == pytest.approx(3.0)
