#!/usr/bin/env python3
import csv, json, re, sys, urllib.request
from pathlib import Path

HOUSE_URL = "https://civicapi.org/api/v2/race/87524"
SENATE_URL = "https://civicapi.org/api/v2/race/87528"
GOVERNORS_URL = "https://civicapi.org/api/v2/race/87535"
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
LIVE_RESULTS_ENABLED = True
USER_AGENT = "DS-election-data/1.0"

MAP_FIELDS = ["code", "district", "rating", "zetel", "marge", "democraat", "republikein"]
HOUSE_FIELDS = ["status", "Democraten verkozen", "Democraten leiden", "Nog geen uitslag", "Andere kandidaten leiden", "Andere kandidaten verkozen", "Republikeinen leiden", "Republikeinen verkozen"]
POWER_FIELDS = ["status", "Democraten in handen", "Democraten leiden", "Nog geen uitslag", "Andere kandidaten leiden", "Andere kandidaten verkozen", "Republikeinen leiden", "Republikeinen in handen"]


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.load(response)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path, fields, rows):
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    temp.replace(path)


def house_code(code):
    state, district = code.lower().split("-", 1)
    return state.upper() + ("00" if district == "al" else district.zfill(2))


def group(party):
    if party == "Democratic":
        return "D"
    if party == "Republican":
        return "R"
    return "O"


def status(region):
    candidates = region.get("candidates") or []
    if not LIVE_RESULTS_ENABLED:
        return "Nog geen uitslag", None
    winners = [c for c in candidates if c.get("winner")]
    votes = sum(int(c.get("votes") or 0) for c in candidates)
    reporting = float(region.get("percent_reporting") or 0)
    if winners:
        leader = max(winners, key=lambda c: int(c.get("votes") or 0))
        suffix = "verkozen"
    elif candidates and (votes > 0 or reporting > 0):
        leader = max(candidates, key=lambda c: (int(c.get("votes") or 0), float(c.get("percent") or 0)))
        suffix = "leidt"
    else:
        return "Nog geen uitslag", None
    prefix = {"D": "Democraat", "R": "Republikein", "O": "Andere kandidaat"}[group(leader.get("party"))]
    return f"{prefix} {suffix}", leader


def margin(region, leader):
    if leader is None:
        return ""
    candidates = sorted(region.get("candidates") or [], key=lambda c: float(c.get("percent") or 0), reverse=True)
    first = float(candidates[0].get("percent") or 0)
    second = float(candidates[1].get("percent") or 0) if len(candidates) > 1 else 0
    return f"{group(leader.get('party'))} +{first-second:.1f} procentpunt".replace(".", ",")


def seat_type(region):
    incumbents = [c for c in region.get("candidates") or [] if c.get("incumbent")]
    if not incumbents:
        return "Open zetel"
    parties = {c.get("party") for c in incumbents}
    if parties == {"Democratic"}:
        return "Democratische zetel"
    if parties == {"Republican"}:
        return "Republikeinse zetel"
    return "Andere zetel"


def candidate_text(region, party):
    candidates = [c for c in region.get("candidates") or [] if c.get("party") == party]
    candidates.sort(key=lambda c: (-int(c.get("votes") or 0), clean(c.get("name"))))
    texts = []
    for candidate in candidates:
        pct = f"{float(candidate.get('percent') or 0):.1f}%".replace(".", ",")
        text = f"{clean(candidate.get('name'))}: {pct}"
        votes = int(candidate.get("votes") or 0)
        if votes:
            text += f" · {votes:,} stemmen".replace(",", ".")
        texts.append(text)
    return " | ".join(texts)


def map_row(template, region):
    label, leader = status(region)
    return {"code": template["code"], "district": template["district"], "rating": label, "zetel": seat_type(region), "marge": margin(region, leader), "democraat": candidate_text(region, "Democratic"), "republikein": candidate_text(region, "Republican")}


def counts(regions):
    result = {"D_won": 0, "D_leads": 0, "none": 0, "O_leads": 0, "O_won": 0, "R_leads": 0, "R_won": 0}
    mapping = {"Democraat verkozen": "D_won", "Democraat leidt": "D_leads", "Nog geen uitslag": "none", "Andere kandidaat leidt": "O_leads", "Andere kandidaat verkozen": "O_won", "Republikein leidt": "R_leads", "Republikein verkozen": "R_won"}
    for region in regions.values():
        label, _ = status(region)
        result[mapping[label]] += 1
    return result


def validate(house, senate, governors):
    expected = [(house, 435, "House"), (senate, 35, "Senate"), (governors, 36, "Governors")]
    for source, number, name in expected:
        regions = source.get("region_results") or {}
        if len(regions) != number:
            raise RuntimeError(f"{name}: verwacht {number} races, ontvangen {len(regions)}")
        if len({r.get('election_id') for r in regions.values()}) != number:
            raise RuntimeError(f"{name}: ontbrekende of dubbele election_id's")


def power_row(counter, dem_hold, rep_hold, label):
    return {"status": label, "Democraten in handen": dem_hold + counter["D_won"], "Democraten leiden": counter["D_leads"], "Nog geen uitslag": counter["none"], "Andere kandidaten leiden": counter["O_leads"], "Andere kandidaten verkozen": counter["O_won"], "Republikeinen leiden": counter["R_leads"], "Republikeinen in handen": rep_hold + counter["R_won"]}


def main():
    house_template = read_csv(DATA_DIR / "house.csv")
    senate_template = read_csv(DATA_DIR / "senate.csv")
    if len(house_template) != 435 or len(senate_template) != 51:
        raise RuntimeError("De bestaande kaarttemplates hebben een onverwacht aantal rijen")

    house, senate, governors = fetch(HOUSE_URL), fetch(SENATE_URL), fetch(GOVERNORS_URL)
    for name, source in [
        ("House", house),
        ("Senate", senate),
        ("Governors", governors),
    ]:
        regions = source.get("region_results") or {}
        races_with_votes = 0
        races_reporting = 0
        races_with_winner = 0
        races_with_percentages = 0

        for region in regions.values():
            candidates = region.get("candidates") or []

            if any(int(candidate.get("votes") or 0) > 0 for candidate in candidates):
                races_with_votes += 1

            if float(region.get("percent_reporting") or 0) > 0:
                races_reporting += 1

            if any(candidate.get("winner") for candidate in candidates):
                races_with_winner += 1

            if any(float(candidate.get("percent") or 0) > 0 for candidate in candidates):
                races_with_percentages += 1

        print(
            f"{name}: {len(regions)} races, "
            f"{races_with_votes} met stemmen, "
            f"{races_reporting} met rapportering, "
            f"{races_with_winner} met winnaar, "
            f"{races_with_percentages} met percentages"
        )

    validate(house, senate, governors)

    house_regions = {house_code(code): region for code, region in house["region_results"].items()}
    if {r["code"] for r in house_template} != set(house_regions):
        raise RuntimeError("De House-codes komen niet overeen met de Datawrapper-template")
    house_rows = [map_row(row, house_regions[row["code"]]) for row in house_template]

    senate_regions = {code.upper(): region for code, region in senate["region_results"].items()}
    senate_rows = []
    for row in senate_template:
        if row["code"] in senate_regions:
            senate_rows.append(map_row(row, senate_regions[row["code"]]))
        else:
            senate_rows.append({"code": row["code"], "district": row["district"], "rating": "Geen race", "zetel": "Geen race in 2026", "marge": "", "democraat": "", "republikein": ""})

    hc = counts(house["region_results"])
    house_seats = [{"status": "zetels", "Democraten verkozen": hc["D_won"], "Democraten leiden": hc["D_leads"], "Nog geen uitslag": hc["none"], "Andere kandidaten leiden": hc["O_leads"], "Andere kandidaten verkozen": hc["O_won"], "Republikeinen leiden": hc["R_leads"], "Republikeinen verkozen": hc["R_won"]}]
    senate_seats = [power_row(counts(senate["region_results"]), 34, 31, "zetels")]
    governors_seats = [power_row(counts(governors["region_results"]), 6, 8, "posten")]

    totals = [sum(int(house_seats[0][f]) for f in HOUSE_FIELDS[1:]), sum(int(senate_seats[0][f]) for f in POWER_FIELDS[1:]), sum(int(governors_seats[0][f]) for f in POWER_FIELDS[1:])]
    if totals != [435, 100, 50]:
        raise RuntimeError(f"Ongeldige totalen: House {totals[0]}, Senate {totals[1]}, Governors {totals[2]}")

    write_csv(DATA_DIR / "house.csv", MAP_FIELDS, house_rows)
    write_csv(DATA_DIR / "senate.csv", MAP_FIELDS, senate_rows)
    write_csv(DATA_DIR / "house_seats.csv", HOUSE_FIELDS, house_seats)
    write_csv(DATA_DIR / "senate_seats.csv", POWER_FIELDS, senate_seats)
    write_csv(DATA_DIR / "governors_seats.csv", POWER_FIELDS, governors_seats)
    print("Vijf CSV-bestanden zijn bijgewerkt.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"FOUT: {error}", file=sys.stderr)
        raise
