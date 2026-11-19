import pandas as pd
import pytest

from src.projection import growth_factors


@pytest.mark.unit
def test_growth_factors_weight_elderly_growth_more_than_young():
    proj = pd.DataFrame(
        {
            "kommune": ["A"] * 4,
            "alder": [30, 70, 30, 70],
            "aar": [2026, 2026, 2036, 2036],
            "antal": [100.0, 100.0, 100.0, 200.0],
        }
    )

    g = growth_factors(proj, ratio_60plus=7.0, base=2026, target=2036).set_index("kommune")

    assert g.loc["A", "vaekst_befolkning"] == pytest.approx(300 / 200)
    assert g.loc["A", "vaekst_60plus"] == pytest.approx(2.0)
    assert g.loc["A", "vaekst_risiko"] == pytest.approx((100 + 1400) / (100 + 700))
