# Hjertestarternes blinde vinkler

Hvor lang tid går der i Danmark, før en person med hjertestop får det første stød, og hvor bør de næste
hjertestartere stå? Alle borgere måles med samme målestok, og forslagene fordeles mellem by og land i samme
forhold som hjertestoppene sker, så resultatet ikke skævvrides mod de tætteste byområder.

**Interaktivt kort:** https://ewing310.github.io/hjertestarter-optimering-placering/
(også i `docs/index.html`; ortofoto kan slås til og fra)

## Hovedresultater (data hentet 19.11.2026)

Danmark opdelt efter EU's urbaniseringsgrad (DEGURBA, GHSL-SMOD 2025):

| | By (bykerner) | Mindre by/forstad | Land |
|---|---:|---:|---:|
| Indbyggere | 1,88 mio. | 2,08 mio. | 2,08 mio. |
| Andel af forventede hjertestop 2036 | 26,7 % | 36,8 % | 36,5 % |
| Median afstand til døgntilgængelig hjertestarter | 135 m | 177 m | 392 m |
| Bor ≤100 m fra en | 34,1 % | 22,5 % | 9,8 % |
| Bor ≤500 m fra en | 99,2 % | 96,8 % | 57,1 % |
| Median tid til første stød | 5,2 min | 6,2 min | 11,0 min |
| Overlevelse ved stødbar rytme (model) | 34,7 % | 31,5 % | 24,4 % |

Beboere på landet venter i median dobbelt så længe på første stød som i bykernerne, og 43 % har ingen
døgntilgængelig hjertestarter inden for 500 m.

**Forslag til nye hjertestartere (fordelt efter hjertestop):**

| Nye | By | Mindre by | Land | Ekstra overlevere pr. år (2036) | Beboere med kortere tid |
|---:|---:|---:|---:|---:|---:|
| 100 | 27 | 37 | 36 | 1,6 | 105.043 |
| 500 | 134 | 184 | 182 | 5,6 | 369.506 |
| 1.000 | 267 | 368 | 365 | 9,4 | 611.751 |
| 2.000 | 535 | 735 | 730 | 15,6 | 992.282 |

- **Fordelingen koster næsten intet:** samme optimering uden krav om fordeling giver 15,8 overlevere pr. år ved
  2.000 nye, altså 1 % mere. Den første version af analysen talte kun beboere inden for 100 m og lagde 100 af de
  første 100 forslag i bykerner og kun 60 af 2.000 på landet.
- **Billige opgraderinger:** 105 af de 2.000 forslag ligger inden for 75 m af en eksisterende hjertestarter,
  der kun har åbningstid (75) eller står som utilgængelig (30). `forslag_goer_doegnaaben.csv` prioriterer 1.000 af dem.
- **Offentlige steder:** 3.789 stationer, indkøbscentre, skoler og idrætsanlæg har ingen registreret
  hjertestarter inden for 100 m.
- **Fremtid:** risikoen vokser mest frem mod 2036 i Horsens, Silkeborg, Brøndby, Høje-Taastrup og København (+15 %).

## Metode

1. **Befolkning.** GHSL GHS-POP 2025 (100 m) delt i 50 m-celler og kalibreret pr. kommune til Danmarks Statistik
   FOLK1A (2026K4), i alt og 60+. Andelen 60+ lokalt kommer fra Meta HRSL 2020, udglattet pr. H3-celle (~0,7 km²).
2. **Risiko.** Ca. 5.000 hjertestop uden for hospital pr. år fordeles på beboerne; personer 60+ vægtes 7 gange
   højere. Risikoen i 2036 skaleres pr. kommune med DST's befolkningsfremskrivning (FRKM126).
3. **Tid til første stød** for hver beboer = den korteste af
   - at hente nærmeste døgntilgængelige hjertestarter: 2 min + tur/retur med 110 m/min og ruteomvej 1,3
     (inkl. aflåste skabe, hvor 112 oplyser koden), og
   - ambulancens responstid, antaget 6 / 8 / 11 min i by / mindre by / land.
4. **Overlevelse** ved stødbar rytme følger Valenzuela et al. (*Circulation* 1997):
   logit = 0,260 − 0,106·(tid til HLR) − 0,139·(tid til stød), med HLR efter 2 min. 25 % af hjertestop antages stødbare.
5. **Optimering.** Hvert nyt sted vælges, så den samlede forventede overlevelse stiger mest (grådig facility location
   med lazy evaluation; målfunktionen er submodulær). Forslagene fordeles mellem by, mindre by og land efter
   klassernes andel af hjertestoppene i 2036, så ethvert top-N udsnit har den fordeling. Kandidater er beboede celler
   (én pr. 100 m-blok) og navngivne offentlige steder fra OpenStreetMap.
6. **Følsomhed.** Ændres ambulancetiderne til 5/7/9 eller 7/10/14 min, går 78–79 % af top 500-forslagene igen
   inden for 200 m.

## Forbehold

- Ambulancetiderne er en antagelse pr. område. Danske Regioner opgør kun responstider på regionsniveau
  (9 ud af 10 fremme inden for 15 min) og beskriver en tydelig sammenhæng med befolkningstæthed.
- Afstande er luftlinje gange en fast omvejsfaktor. Modellen antager, at nogen henter hjertestarteren, når den er
  hurtigere end ambulancen. Det gælder både tilskuere og Hjerteløbere.
- Befolkningen er bopælsbefolkning. Steder med mange besøgende vises særskilt.
- Registrets positioner og åbningstider er indberettet af ejerne og kan være forældede.
- Et forslag er et søgeområde på ca. 100 × 100 m. Den endelige placering kræver lokal vurdering.

## Output

| Fil | Indhold |
|---|---|
| `output/forslag_nye_hjertestartere.csv` | 2.000 prioriterede placeringer med område, kommune, værtssted, effekt og anbefaling |
| `output/forslag_goer_doegnaaben.csv` | 1.000 eksisterende hjertestartere, der bør gøres døgntilgængelige eller genaktiveres |
| `output/offentlige_steder_uden_hjertestarter.csv` | Offentlige steder med mange besøgende uden hjertestarter ≤100 m |
| `output/by_og_land.csv` | Adgang og overlevelse pr. urbaniseringsgrad |
| `output/kommuner_ranking.csv` | Alle 98 kommuner |
| `output/summary.json` | Nøgletal |
| `docs/index.html` | Interaktivt kort (GitHub Pages) |

## Datakilder

| Kilde | Brug |
|---|---|
| Dansk Hjertestarterregister (hjertestarter.dk) | Position og tilgængelighed for hjertestartere |
| GHSL GHS-POP E2025 og GHS-SMOD E2025 (EU JRC) | Befolkning og urbaniseringsgrad |
| Meta High Resolution Settlement Layer 2020 (HDX) | Andel 60+ |
| Danmarks Statistik FOLK1A og FRKM126 | Befolkning 2026K4 og fremskrivning til 2036 |
| Kontur Population 2023 | Maske mod nabolande |
| OpenStreetMap (Geofabrik) | Værtssteder og offentlige steder |
| geoBoundaries ADM2 | Kommunegrænser |
| Esri World Imagery | Ortofoto i kortet |

## Genkørsel

```bash
uv venv --python 3.13 .venv && uv pip install --python .venv/bin/python -r requirements.txt
# Rå data lægges i data/raw (se docstrings i src/ for kilder og URL'er):
#   kontur_population_DK_20231101.gpkg, hrsl/*.csv, ghsl/*.tif, ghsl_smod/*.tif,
#   denmark-latest.osm.pbf, kommuner.geojson
./run_all.sh
.venv/bin/python -m pytest -q
```

Kode i `src/`: `fetch_aeds`, `fetch_osm`, `population`, `projection`, `urbanization`, `survival`,
`fair_optimize`, `placement`, `analysis`, `web_export`.

## Licens

Koden er MIT-licenseret (se `LICENSE`). Data tilhører de respektive kilder: hjertestarterdata © TrygFonden /
Dansk Hjertestarterregister, GHSL © EU JRC, Danmarks Statistik, © OpenStreetMap-bidragydere (ODbL), Esri.
