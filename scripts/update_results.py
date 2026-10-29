#!/usr/bin/env python3
"""Werk de Datawrapper-CSV's bij met verkiezingsdata van CivicAPI."""

import csv
import json
import re
import sys
import urllib.request
from pathlib import Path


# -------------------------------------------------------------------
# Instellingen
# -------------------------------------------------------------------

HOUSE_URL = "https://civicapi.org/api/v2/race/87524"
SENATE_URL = "https://civicapi.org/api/v2/race/87528"
GOVERNORS_URL = "https://civicapi.org/api/v2/race/87535"

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

USER_AGENT = "DS-election-data/1.0 (+https://github.com/)"

# CivicAPI publiceert voor de verkiezingen testuitslagen.
# Laat dit op False staan tot de redactie bewust live uitslagen activeert.
LIVE_RESULTS_ENABLED = False


# -------------------------------------------------------------------
# CSV-kolommen
# -------------------------------------------------------------------

MAP_FIELDS = [
    "code",
    "district",
    "rating",
    "zetel",
    "marge",
    "democraat",
    "republikein",
]

HOUSE_SEAT_FIELDS = [
    "status",
    "Democraten verkozen",
    "Democraten leiden",
    "Nog geen uitslag",
    "Andere kandidaten leiden",
    "Andere kandidaten verkozen",
    "Republikeinen leiden",
    "Republikeinen verkozen",
]

SENATE_SEAT_FIELDS = [
    "status",
    "Democraten in handen",
    "Democraten leiden",
    "Nog geen uitslag",
    "Andere kandidaten leiden",
    "Andere kandidaten verkozen",
    "Republikeinen leiden",
    "Republikeinen in handen",
]

GOVERNORS_SEAT_FIELDS = [
    "status",
    "Democraten in handen",
    "Democraten leiden",
    "Nog geen uitslag",
    "Andere kandidaten leiden",
    "Andere kandidaten verkozen",
    "Republikeinen leiden",
    "Republikeinen in handen",
]


# -------------------------------------------------------------------
# Algemene functies
# -------------------------------------------------------------------

def fetch_json(url):
    """Haal een JSON-bestand op bij CivicAPI."""

    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT},
    )

    with urllib.request.urlopen(request, timeout=60) as response:
        if response.status != 200:
            raise RuntimeError(
                f"CivicAPI gaf HTTP-status {response.status} voor {url}"
            )

        return json.load(response)


def clean_text(value):
    """Verwijder dubbele spaties en regeleinden uit tekst."""

    return re.sub(r"\s+", " ", str(value or "")).strip()


def read_csv(path):
    """Lees een CSV-bestand in als lijst van dictionaries."""

    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        return list(csv.DictReader(handle))


def write_csv(path, fieldnames, rows):
    """Schrijf een CSV eerst tijdelijk weg en vervang daarna het oude bestand."""

    temporary_path = path.with_suffix(path.suffix + ".tmp")

    with temporary_path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )

        writer.writeheader()
        writer.writerows(rows)

    temporary_path.replace(path)


def house_code(civic_code):
    """
    Zet een CivicAPI-code om naar de code van de Datawrapper-kaart.

    Voorbeelden:
    az-01 -> AZ01
    ak-al -> AK00
    """

    state, district = civic_code.lower().split("-", 1)

    if district == "al":
        number = "00"
    else:
        number = district.zfill(2)

    return state.upper() + number


def format_percentage(value):
    """Formatteer een percentage met een decimale komma."""

    return f"{float(value or 0):.1f}%".replace(".", ",")


def format_votes(value):
    """Formatteer stemtotalen met punten als duizendtallen."""

    return f"{int(value or 0):,}".replace(",", ".")


def party_group(party):
    """Herleid een partij tot Democratisch, Republikeins of Overig."""

    if party == "Democratic":
        return "D"

    if party == "Republican":
        return "R"

    return "O"


# -------------------------------------------------------------------
# Status en kandidaten
# -------------------------------------------------------------------

def determine_status(region):
    """
    Bepaal of een kandidaat leidt of verkozen is.

    Zolang LIVE_RESULTS_ENABLED False is, worden alle CivicAPI-
    testuitslagen genegeerd.
    """

    candidates = region.get("candidates") or []

    if not LIVE_RESULTS_ENABLED:
        return "Nog geen uitslag", None

    winners = [
        candidate
        for candidate in candidates
        if candidate.get("winner")
    ]

    total_votes = sum(
        int(candidate.get("votes") or 0)
        for candidate in candidates
    )

    reporting = float(region.get("percent_reporting") or 0)

    if winners:
        leader = max(
            winners,
            key=lambda candidate: int(candidate.get
