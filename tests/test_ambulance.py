import pytest

from src.ambulance import KOMMUNE_REGION, REGION_KOMMUNER, norm_name, split_address


@pytest.mark.unit
@pytest.mark.parametrize(
    ("adresse", "expected"),
    [
        ("Laenvej 29-31", ("laenvej", "29")),
        ("Hjulmagervej 3A-B", ("hjulmagervej", "3a")),
        ("Søren Nymarks Vej 4 H", ("sørennymarksvej", "4h")),
        ("Markedspladsen 15, st. tv.", ("markedspladsen", "15")),
        ("H.C. Ørstedsvej 35", ("hcørstedsvej", "35")),
        ("Bispeengbuen", ("bispeengbuen", "")),
    ],
)
def test_split_address_normalises_street_and_house_number(adresse, expected):
    assert split_address(adresse) == expected


@pytest.mark.unit
def test_street_spelling_variants_share_a_key():
    assert split_address("H.C. Ørsteds Vej 35") == split_address("H.C. Ørstedsvej 35")


@pytest.mark.unit
def test_norm_name_expands_common_abbreviations():
    assert norm_name("Sdr. Omfartsvej") == "sønder omfartsvej"
    assert norm_name("Gl. Banevej") == "gammel banevej"
    assert norm_name("Aarhus") == norm_name("Århus")


@pytest.mark.unit
def test_every_municipality_belongs_to_exactly_one_region():
    assert len(REGION_KOMMUNER) == 5
    assert len(KOMMUNE_REGION) == 98
    assert sum(len(k) for k in REGION_KOMMUNER.values()) == 98
