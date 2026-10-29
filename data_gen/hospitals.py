"""True hospitals (hidden), the customer master, and messy monthly GPO rosters."""

import random
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from data_gen.reference import random_date
from data_gen.settings import GenSettings

N_HOSPITALS = 200
CUSTOMER_SHARE = 0.6  # share of hospitals that buy from us
DUPLICATE_CUSTOMER_RATE = 0.05  # hospitals with two records in our own master
MOVE_RATE = 0.05
RENAME_RATE = 0.04
MULTI_GPO_RATE = 0.15
JOIN_RATE = 0.08  # join a GPO mid-period
LEAVE_RATE = 0.05  # leave a GPO mid-period

# Repeated city names in different states are deliberate look-alike traps.
CITIES: list[tuple[str, str, str]] = [
    ("Indianapolis", "IN", "462"),
    ("Lafayette", "IN", "479"),
    ("Richmond", "IN", "473"),
    ("Richmond", "VA", "232"),
    ("Springfield", "IL", "627"),
    ("Springfield", "MO", "658"),
    ("Columbus", "OH", "432"),
    ("Cleveland", "OH", "441"),
    ("Chicago", "IL", "606"),
    ("Louisville", "KY", "402"),
    ("Nashville", "TN", "372"),
    ("Detroit", "MI", "482"),
    ("Grand Rapids", "MI", "495"),
    ("Milwaukee", "WI", "532"),
    ("St. Louis", "MO", "631"),
    ("Pittsburgh", "PA", "152"),
    ("Charlotte", "NC", "282"),
    ("Atlanta", "GA", "303"),
]
SAINTS = ["Mary", "Joseph", "Luke", "Francis", "Vincent", "Anne", "Elizabeth", "John"]
NAME_ROOTS = [
    "Riverside",
    "Lakeview",
    "Mercy",
    "Good Samaritan",
    "Providence",
    "Sacred Heart",
    "Valley",
    "Northside",
    "Baptist",
    "Methodist",
]
SUFFIXES = [
    "Hospital",
    "Medical Center",
    "Regional Medical Center",
    "Community Hospital",
    "Memorial Hospital",
]
STREETS = ["Main", "Oak", "Maple", "Washington", "Lincoln", "Park", "University", "Lake"]
STREET_TYPES = ["Street", "Avenue", "Boulevard", "Road", "Drive", "Parkway"]
HEALTH_SYSTEMS = [
    "Riverbend Health",
    "Crestline Health System",
    "Unity Care Partners",
    "Harborview Health",
    "Prairie Health Network",
]
NAME_ABBREVIATIONS = [
    ("Saint ", "St. "),
    ("Medical Center", "Med Ctr"),
    ("Regional", "Reg"),
    ("Hospital", "Hosp"),
    ("Memorial", "Mem"),
    ("Community", "Comm"),
]
STREET_ABBREVIATIONS = [
    ("Street", "St"),
    ("Avenue", "Ave"),
    ("Boulevard", "Blvd"),
    ("Road", "Rd"),
    ("Drive", "Dr"),
    ("Parkway", "Pkwy"),
]


@dataclass
class Hospital:
    hospital_id: str
    name: str  # current name
    address: str  # current address
    city: str
    state: str
    zip_code: str
    health_system: str | None
    hin: str
    is_customer: bool
    old_name: str | None = None
    renamed_on: date | None = None
    old_address: str | None = None
    moved_on: date | None = None


@dataclass
class Membership:
    hospital_id: str
    gpo_id: str
    effective_from: date
    effective_to: date | None
    roster_lag_days: int  # delay before a new member shows up on the roster
    update_lag_days: int  # how stale the GPO's name/address data is
    states_eligibility_start: bool


def name_on(h: Hospital, day: date) -> str:
    if h.old_name is not None and h.renamed_on is not None and day < h.renamed_on:
        return h.old_name
    return h.name


def address_on(h: Hospital, day: date) -> str:
    if h.old_address is not None and h.moved_on is not None and day < h.moved_on:
        return h.old_address
    return h.address


def typo(rng: random.Random, text: str) -> str:
    """Swap two neighbouring characters, like a fast typist would."""
    if len(text) < 5:
        return text
    i = rng.randrange(1, len(text) - 2)
    return text[:i] + text[i + 1] + text[i] + text[i + 2 :]


def messy_name(rng: random.Random, name: str, intensity: float) -> str:
    out = name
    for full, short in NAME_ABBREVIATIONS:
        if full in out and rng.random() < 0.5 * intensity:
            out = out.replace(full, short)
    if rng.random() < 0.2 * intensity:
        out = out.upper()
    if rng.random() < 0.1 * intensity:
        out = out.replace("'", "").replace(".", "")
    if rng.random() < 0.08 * intensity:
        out = typo(rng, out)
    return out


def messy_address(rng: random.Random, address: str, intensity: float) -> str:
    out = address
    for full, short in STREET_ABBREVIATIONS:
        if full in out and rng.random() < 0.6 * intensity:
            out = out.replace(full, short)
    if rng.random() < 0.15 * intensity:
        out += f" Suite {rng.randint(100, 999)}"
    if rng.random() < 0.05 * intensity:
        out = typo(rng, out)
    return out


def make_name(rng: random.Random, city: str) -> str:
    style = rng.random()
    if style < 0.35:
        return f"Saint {rng.choice(SAINTS)} {rng.choice(SUFFIXES)}"
    if style < 0.7:
        return f"{rng.choice(NAME_ROOTS)} {rng.choice(SUFFIXES)}"
    return f"{city} {rng.choice(['General Hospital', 'Medical Center', 'Community Hospital'])}"


def make_address(rng: random.Random) -> str:
    return f"{rng.randint(100, 9999)} {rng.choice(STREETS)} {rng.choice(STREET_TYPES)}"


def make_hospitals(rng: random.Random, settings: GenSettings) -> list[Hospital]:
    event_start = settings.start_date + timedelta(days=60)
    event_end = settings.end_date - timedelta(days=60)
    hospitals: list[Hospital] = []
    seen: set[tuple[str, str, str]] = set()
    while len(hospitals) < N_HOSPITALS:
        city, state, zip_prefix = rng.choice(CITIES)
        name = make_name(rng, city)
        if (name, city, state) in seen:
            continue  # no two true hospitals share a name in the same city
        seen.add((name, city, state))
        h = Hospital(
            hospital_id=f"H{len(hospitals) + 1:04d}",
            name=name,
            address=make_address(rng),
            city=city,
            state=state,
            zip_code=f"{zip_prefix}{rng.randint(0, 99):02d}",
            health_system=rng.choice(HEALTH_SYSTEMS) if rng.random() < 0.4 else None,
            hin=f"{rng.randint(0, 999_999_999):09d}",
            is_customer=rng.random() < CUSTOMER_SHARE,
        )
        if rng.random() < MOVE_RATE:
            h.old_address = h.address
            h.address = make_address(rng)
            h.moved_on = random_date(rng, event_start, event_end)
        if rng.random() < RENAME_RATE:
            system = rng.choice(HEALTH_SYSTEMS)
            h.old_name = h.name
            h.name = f"{system.split()[0]} {h.name}"  # e.g. acquired by a health system
            h.health_system = system
            h.renamed_on = random_date(rng, event_start, event_end)
        hospitals.append(h)
    return hospitals


def make_memberships(
    rng: random.Random, hospitals: list[Hospital], gpo_ids: list[str], settings: GenSettings
) -> list[Membership]:
    result: list[Membership] = []
    for h in hospitals:
        primary = rng.choice(gpo_ids)
        gpos = [primary]
        if rng.random() < MULTI_GPO_RATE:
            gpos.append(rng.choice([g for g in gpo_ids if g != primary]))
        for g in gpos:
            effective_from = date(2020, 1, 1)
            effective_to: date | None = None
            roll = rng.random()
            if roll < JOIN_RATE:
                effective_from = random_date(
                    rng,
                    settings.start_date + timedelta(days=30),
                    settings.end_date - timedelta(days=90),
                )
            elif roll < JOIN_RATE + LEAVE_RATE:
                effective_to = random_date(
                    rng,
                    settings.start_date + timedelta(days=60),
                    settings.end_date - timedelta(days=30),
                )
            result.append(
                Membership(
                    hospital_id=h.hospital_id,
                    gpo_id=g,
                    effective_from=effective_from,
                    effective_to=effective_to,
                    roster_lag_days=rng.choice([0, 0, 0, 30, 45, 60]),
                    update_lag_days=rng.randint(30, 120),
                    states_eligibility_start=rng.random() < 0.6,
                )
            )
    return result


def make_customers(
    rng: random.Random, hospitals: list[Hospital]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, object]] = []
    labels: list[dict[str, object]] = []
    for h in hospitals:
        if not h.is_customer:
            continue
        n_records = 2 if rng.random() < DUPLICATE_CUSTOMER_RATE else 1
        for _ in range(n_records):
            customer_id = f"CUS{len(rows) + 1:05d}"
            rows.append(
                {
                    "customer_id": customer_id,
                    "customer_name": messy_name(rng, h.name, 0.5),
                    "address": messy_address(rng, h.address, 0.5),
                    "city": h.city,
                    "state": h.state,
                    "zip_code": h.zip_code,
                    "latitude": None,
                    "longitude": None,
                    "health_system": h.health_system,
                    "gln": None,
                    "hin": h.hin if rng.random() < 0.3 else None,
                    "dea": None,
                }
            )
            labels.append({"customer_id": customer_id, "hospital_id": h.hospital_id})
    return pd.DataFrame(rows), pd.DataFrame(labels)


def next_month(day: date) -> date:
    return date(day.year + day.month // 12, day.month % 12 + 1, 1)


def make_rosters(
    rng: random.Random,
    hospitals: list[Hospital],
    memberships: list[Membership],
    gpo_ids: list[str],
    settings: GenSettings,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    by_id = {h.hospital_id: h for h in hospitals}
    member_ids: dict[tuple[str, str], str] = {}
    has_hin: dict[tuple[str, str], bool] = {}
    styles: dict[tuple[str, str, str, str], tuple[str, str]] = {}
    files: list[dict[str, object]] = []
    records: list[dict[str, object]] = []
    labels: list[dict[str, object]] = []

    as_of = settings.start_date
    while as_of < settings.end_date:
        for g in gpo_ids:
            roster_file_id = f"RF{len(files) + 1:04d}"
            count = 0
            for m in memberships:
                if m.gpo_id != g:
                    continue
                if as_of < m.effective_from + timedelta(days=m.roster_lag_days):
                    continue  # not on the roster yet
                if m.effective_to is not None and as_of >= m.effective_to:
                    continue  # has left
                h = by_id[m.hospital_id]
                key = (g, h.hospital_id)
                if key not in member_ids:
                    member_ids[key] = f"{g}-M{len(member_ids) + 1:05d}"
                    has_hin[key] = rng.random() < 0.5

                # The GPO's data is stale: it shows the hospital as it was some time ago.
                seen_on = as_of - timedelta(days=m.update_lag_days)
                name, address = name_on(h, seen_on), address_on(h, seen_on)
                style_key = (g, h.hospital_id, name, address)
                if style_key not in styles:  # each GPO spells a hospital consistently
                    styles[style_key] = (
                        messy_name(rng, name, 1.0),
                        messy_address(rng, address, 1.0),
                    )
                messy_n, messy_a = styles[style_key]

                roster_record_id = f"RR{len(records) + 1:06d}"
                records.append(
                    {
                        "roster_record_id": roster_record_id,
                        "roster_file_id": roster_file_id,
                        "gpo_id": g,
                        "gpo_member_id": member_ids[key],
                        "member_name": messy_n,
                        "address": messy_a,
                        "city": h.city,
                        "state": h.state,
                        "zip_code": h.zip_code,
                        "health_system": h.health_system,
                        "gln": None,
                        "hin": h.hin if has_hin[key] else None,
                        "dea": None,
                        "eligibility_start": (
                            m.effective_from if m.states_eligibility_start else None
                        ),
                        "eligibility_end": m.effective_to,
                    }
                )
                labels.append({"roster_record_id": roster_record_id, "hospital_id": h.hospital_id})
                count += 1
            files.append(
                {
                    "roster_file_id": roster_file_id,
                    "gpo_id": g,
                    "as_of_date": as_of,
                    "received_at": as_of + timedelta(days=3),
                    "source_filename": f"{g}_roster_{as_of:%Y%m}.csv",
                    "row_count": count,
                }
            )
        as_of = next_month(as_of)

    return pd.DataFrame(files), pd.DataFrame(records), pd.DataFrame(labels)
