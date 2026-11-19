"""Fælles konstanter og antagelser for analysen."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
OUTPUT = ROOT / "output"

CRS_WGS84 = "EPSG:4326"
CRS_METRIC = "EPSG:25832"  # ETRS89 / UTM 32N - dansk standard

GRID_M = 50  # efterspørgselsgrid (GHSL 100 m delt i 2x2)

# Dækningsradier (luftlinje). 100 m er den gængse definition i dansk forskning
# (Karlsson et al. 2019, Circulation) - ca. 3 min. at hente og vende tilbage.
PRIMARY_RADIUS_M = 100
REPORT_RADII_M = (100, 200, 500)

# Hjertestop uden for hospital (OHCA) i Danmark: ca. 5.000/år (≈85 pr. 100.000).
# Risikoen stiger kraftigt med alderen; vi antager, at personer 60+ har ~7x
# højere incidens end personer under 60 (giver ~70 % af tilfældene i 60+,
# hvilket matcher medianalder omkring 70+ i Dansk Hjertestopregister).
OHCA_PER_YEAR_DK = 5000
RISK_RATIO_60PLUS = 7.0

# Hvilke hjertestartere tæller som tilgængelige i den primære analyse.
# ~3/4 af hjertestop sker i hjemmet og mange om aftenen/natten, så kun
# døgntilgængelige hjertestartere dækker reelt hele døgnet. "bag_lås" er
# altid tilgængelige i aflåst skab - koden oplyses af 112.
AED_CATEGORIES_24_7 = ("døgnåben", "bag_lås")
AED_CATEGORIES_ANY = ("døgnåben", "åbningstid", "bag_lås")
# Eksisterende hjertestartere der kan opgraderes billigt i stedet for at købe nye
AED_CATEGORIES_UPGRADABLE = ("åbningstid", "utilgaengelig")

# Optimeringen vægter efter forventet risiko i 2036 (DST-fremskrivning pr. kommune),
# så placeringerne også holder i fremtiden.
OPT_WEIGHT = "risk_2036"

N_PROPOSALS = 2000
HOST_SNAP_RADIUS_M = 75  # forslag "snappes" til et offentligt værtssted inden for denne afstand

# --- Overlevelsesmodel (samme målestok for by og land) -------------------------
# Tid til første stød = min(tid til at hente nærmeste døgntilgængelige hjertestarter,
# ambulancens responstid). Overlevelse ved stødbar rytme: Valenzuela et al.,
# Circulation 1997: logit = 0.260 - 0.106*(tid til HLR) - 0.139*(tid til stød).
T_ALARM_MIN = 2.0  # genkende hjertestop, ringe 112, sende nogen afsted
RETRIEVE_SPEED_M_PER_MIN = 110.0  # rask gang/let løb
ROUTE_FACTOR = 1.3  # luftlinje -> gangrute
T_CPR_MIN = 2.0  # HLR startes typisk hurtigt i DK (telefonvejledt)
VALENZUELA = (0.260, 0.106, 0.139)
SHOCKABLE_SHARE = 0.25  # andel hjertestop med stødbar rytme, hvor en hjertestarter kan redde liv

# Urbaniseringsgrad (EU/FN DEGURBA niveau 1 via GHSL-SMOD 2025) og antaget median
# responstid for ambulance. Danske Regioner: tydelig sammenhæng mellem responstid
# og befolkningstæthed; 9 ud af 10 udrykninger er fremme inden for 15 min.
URBAN_CLASSES = ("By", "Mindre by/forstad", "Land")
EMS_MIN_BY_CLASS = (6.0, 8.0, 11.0)
HOST_SNAP_BY_CLASS_M = (75.0, 100.0, 200.0)
