#!/usr/bin/env python3
"""Update Datawrapper CSV files with live CivicAPI election data."""

import csv
import json
import re
import sys
import urllib.request
from pathlib import Path

HOUSE_URL = "https://civicapi.org/api/v2/race/87524"
SENATE_URL = "https://civicapi.org/api/v2/race/87528"
GOVERNORS_URL = "https://civicapi.org/api/v2/race/87535"
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
USER_AGENT = "DS-election-data/1.0 (+https://github.com/)"

# Safety switch: CivicAPI is publishing test results before election night.
# Keep False until the newsroom deliberately activates live results.
LIVE_RESULTS_ENABLED = False

MAP_FIELDS = [
    "code", "district", "rating", "zetel", "marge", "democraat", "republikein"
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


def fetch_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        if response.status != 200:
            raise RuntimeError(f"CivicAPI gaf HTTP-status {response.status} voor {url}")
        return json.load(response)


def clean_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path, fieldnames, rows):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def house_code(civic_code):
    state, district = civic_code.lower().split("-", 1)
    number = "00" if district == "al" else district.zfill(2)
    return state.upper() + number


def format_percentage(value):
    return f"{float(value or 0):.1f}%".replace(".", ",")


def format_votes(value):
    return f"{int(value or 0):,}".replace(",", ".")


def party_group(party):
    if party == "Democratic":
        return "D"
    if party == "Republican":
        return "R"
    return "O"


def determine_status(region):
    candidates = region.get("candidates") or []
    if not LIVE_RESULTS_ENABLED:
        return "Nog geen uitslag", None
    winners = [candidate for candidate in candidates if candidate.get("winner")]
    total_votes = sum(int(candidate.get("votes") or 0) for candidate in candidates)
    reporting = float(region.get("percent_reporting") or 0)

    if winners:
        leader = max(winners, key=lambda candidate: int(candidate.get("votes") or 0))
        state = "verkozen"
    elif candidates and (total_votes > 0 or reporting > 0):
        leader = max(
            candidates,
            key=lambda candidate: (
                int(candidate.get("votes") or 0),
                float(candidate.get("percent") or 0),
            ),
        )
        state = "leidt"
    else:
        return "Nog geen uitslag", None

    group = party_group(leader.get("party"))
    label = {"D": "Democraat", "R": "Republikein", "O": "Andere kandidaat"}[group]
    return f"{label} {state}", leader


def margin_text(region, leader):
    if leader is None:
        return ""
    candidates = sorted(
        region.get("candidates") or [],
        key=lambda candidate: (
            float(candidate.get("percent") or 0),
            int(candidate.get("votes") or 0),
        ),
        reverse=True,
    )
    if not candidates:
        return ""
    leader_percentage = float(candidates[0].get("percent") or 0)
    runner_up_percentage = float(candidates[1].get("percent") or 0) if len(candidates) > 1 else 0
    margin = leader_percentage - runner_up_percentage
    prefix = party_group(leader.get("party"))
    return f"{prefix} +{margin:.1f} procentpunt".replace(".", ",")


def seat_type(region):
    incumbents = [candidate for candidate in region.get("candidates") or [] if candidate.get("incumbent")]
    if not incumbents:
        return "Open zetel"
    parties = {candidate.get("party") for candidate in incumbents}
    if parties == {"Democratic"}:
        return "Democratische zetel"
    if parties == {"Republican"}:
        return "Republikeinse zetel"
    return "Andere zetel"


def candidate_text(region, party):
    candidates = [
        candidate for candidate in region.get("candidates") or []
        if candidate.get("party") == party
    ]
    candidates.sort(
        key=lambda candidate: (
            -int(candidate.get("votes") or 0),
            clean_text(candidate.get("name")),
        )
    )
    entries = []
    for candidate in candidates:
        text = f"{clean_text(candidate.get('name'))}: {format_percentage(candidate.get('percent'))}"
        if int(candidate.get("votes") or 0) > 0:
            text += f" · {format_votes(candidate.get('votes'))} stemmen"
        entries.append(text)
    return " | ".join(entries)


def map_row(template, region):
    status, leader = determine_status(region)
    return {
        "code": template["code"],
        "district": template["district"],
        "rating": status,
        "zetel": seat_type(region),
        "marge": margin_text(region, leader),
        "democraat": candidate_text(region, "Democratic"),
        "republikein": candidate_text(region, "Republican"),
    }


def count_races(regions):
    counts = {
        "D_won": 0,
        "D_leads": 0,
        "unreported": 0,
        "O_leads": 0,
        "O_won": 0,
        "R_leads": 0,
        "R_won": 0,
    }
    mapping = {
        "Democraat verkozen": "D_won",
        "Democraat leidt": "D_leads",
        "Nog geen uitslag": "unreported",
        "Andere kandidaat leidt": "O_leads",
        "Andere kandidaat verkozen": "O_won",
        "Republikein leidt": "R_leads",
        "Republikein verkozen": "R_won",
    }
    for region in regions.values():
        status, _ = determine_status(region)
        counts[mapping[status]] += 1
    return counts


def validate_source(house, senate):
    house_regions = house.get("region_results") or {}
    senate_regions = senate.get("region_results") or {}
    if len(house_regions) != 435:
        raise RuntimeError(f"Verwacht 435 House-races, ontvangen: {len(house_regions)}")
    if len(senate_regions) != 35:
        raise RuntimeError(f"Verwacht 35 Senate-races, ontvangen: {len(senate_regions)}")
    if len({region.get("election_id") for region in house_regions.values()}) != 435:
        raise RuntimeError("House bevat ontbrekende of dubbele election_id's")
    if len({region.get("election_id") for region in senate_regions.values()}) != 35:
        raise RuntimeError("Senate bevat ontbrekende of dubbele election_id's")


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    house_path = DATA_DIR / "house.csv"
    senate_path = DATA_DIR / "senate.csv"

    if not house_path.exists() or not senate_path.exists():
        raise RuntimeError("data/house.csv en data/senate.csv moeten al bestaan als templates")

    house_template = read_csv(house_path)
    senate_template = read_csv(senate_path)
    if len(house_template) != 435:
        raise RuntimeError(f"House-template bevat {len(house_template)} rijen in plaats van 435")
    if len(senate_template) != 51:
        raise RuntimeError(f"Senate-template bevat {len(senate_template)} rijen in plaats van 51")

    house = fetch_json(HOUSE_URL)
    senate = fetch_json(SENATE_URL)
    governors = fetch_json(GOVERNORS_URL)
    validate_source(house, senate)

    house_regions = {house_code(code): region for code, region in house["region_results"].items()}
    senate_regions = {code.upper(): region for code, region in senate["region_results"].items()}

    template_house_codes = {row["code"] for row in house_template}
    if template_house_codes != set(house_regions):
        missing = sorted(template_house_codes - set(house_regions))
        extra = sorted(set(house_regions) - template_house_codes)
        raise RuntimeError(f"House-codes komen niet overeen. Ontbrekend: {missing}; extra: {extra}")

    house_rows = [map_row(row, house_regions[row["code"]]) for row in house_template]

    senate_rows = []
    for row in senate_template:
        code = row["code"]
        if code in senate_regions:
            senate_rows.append(map_row(row, senate_regions[code]))
        else:
            senate_rows.append({
                "code": code,
                "district": row["district"],
                "rating": "Geen race",
                "zetel": "Geen race in 2026",
                "marge": "",
                "democraat": "",
                "republikein": "",
            })

    house_counts = count_races(house["region_results"])
    house_seats = [{
        "status": "zetels",
        "Democraten verkozen": house_counts["D_won"],
        "Democraten leiden": house_counts["D_leads"],
        "Nog geen uitslag": house_counts["unreported"],
        "Andere kandidaten leiden": house_counts["O_leads"],
        "Andere kandidaten verkozen": house_counts["O_won"],
        "Republikeinen leiden": house_counts["R_leads"],
        "Republikeinen verkozen": house_counts["R_won"],
    }]

    senate_counts = count_races(senate["region_results"])
    # The 35 races in the national CivicAPI feed are the seats being contested.
    # The remaining 65 holdover seats are fixed for this 2026 workflow.
    # Do not use the changing top-level `seats` values from CivicAPI here.
    holdovers = {"Democratic": 34, "Republican": 31}
    senate_seats = [{
        "status": "zetels",
        "Democraten in handen": holdovers.get("Democratic", 0) + senate_counts["D_won"],
        "Democraten leiden": senate_counts["D_leads"],
        "Nog geen uitslag": senate_counts["unreported"],
        "Andere kandidaten leiden": senate_counts["O_leads"],
        "Andere kandidaten verkozen": senate_counts["O_won"],
        "Republikeinen leiden": senate_counts["R_leads"],
        "Republikeinen in handen": holdovers.get("Republican", 0) + senate_counts["R_won"],
    }]

    governor_counts = count_races(governors["region_results"])

governor_holdovers = {
    "Democratic": 6,
    "Republican": 8,
}

governors_seats = [{
    "status": "posten",
    "Democraten in handen":
        governor_holdovers["Democratic"] + governor_counts["D_won"],
    "Democraten leiden":
        governor_counts["D_leads"],
    "Nog geen uitslag":
        governor_counts["unreported"],
    "Andere kandidaten leiden":
        governor_counts["O_leads"],
    "Andere kandidaten verkozen":
        governor_counts["O_won"],
    "Republikeinen leiden":
        governor_counts["R_leads"],
    "Republikeinen in handen":
        governor_holdovers["Republican"] + governor_counts["R_won"],
}]

    if sum(int(house_seats[0][field]) for field in HOUSE_SEAT_FIELDS[1:]) != 435:
        raise RuntimeError("De House-zetelgrafiek telt niet op tot 435")
    if sum(int(senate_seats[0][field]) for field in SENATE_SEAT_FIELDS[1:]) != 100:
        raise RuntimeError("De Senate-zetelgrafiek telt niet op tot 100")
        if sum(
    int(governors_seats[0][field])
    for field in GOVERNORS_SEAT_FIELDS[1:]
) != 50:
    raise RuntimeError("De gouverneursgrafiek telt niet op tot 50")

    write_csv(DATA_DIR / "house.csv", MAP_FIELDS, house_rows)
    write_csv(DATA_DIR / "senate.csv", MAP_FIELDS, senate_rows)
    write_csv(DATA_DIR / "house_seats.csv", HOUSE_SEAT_FIELDS, house_seats)
    write_csv(DATA_DIR / "senate_seats.csv", SENATE_SEAT_FIELDS, senate_seats)
write_csv(
    DATA_DIR / "governors_seats.csv",
    GOVERNORS_SEAT_FIELDS,
    governors_seats,
)

    print("Vier CSV-bestanden zijn bijgewerkt.")
    print(f"House: {len(house_rows)} districten; zetels: {house_seats[0]}")
    print(f"Senate: {len(senate_regions)} races; zetels: {senate_seats[0]}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"FOUT: {error}", file=sys.stderr)
        raise
