#!/usr/bin/env bash
# Kør hele pipelinen fra rå data til kortside. Forudsætter at data/raw er hentet (se README).
set -euo pipefail
cd "$(dirname "$0")"
PY=.venv/bin/python
$PY -m src.fetch_aeds
$PY -m src.fetch_osm
$PY -m src.population
$PY -m src.projection
$PY -m src.analysis
$PY -m src.web_export
