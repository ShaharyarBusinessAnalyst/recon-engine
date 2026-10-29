import random

import pandas as pd
import pytest

from data_gen.hospitals import make_hospitals, make_memberships, make_rosters
from data_gen.settings import GenSettings

GPO_IDS = ["GPO01", "GPO02", "GPO03", "GPO04"]


@pytest.fixture(scope="module")
def rosters() -> dict[str, pd.DataFrame]:
    settings = GenSettings()
    rng = random.Random(settings.seed)
    hospitals = make_hospitals(rng, settings)
    memberships = make_memberships(rng, hospitals, GPO_IDS, settings)
    files, records, labels = make_rosters(rng, hospitals, memberships, GPO_IDS, settings)
    truth = pd.DataFrame([{"name": h.name, "city": h.city} for h in hospitals])
    return {"records": records, "labels": labels, "truth": truth}


def test_every_roster_record_has_one_true_hospital(rosters: dict[str, pd.DataFrame]) -> None:
    assert len(rosters["records"]) == len(rosters["labels"])
    assert rosters["labels"]["roster_record_id"].is_unique


def test_no_hospital_listed_twice_in_one_file(rosters: dict[str, pd.DataFrame]) -> None:
    merged = rosters["records"].merge(rosters["labels"], on="roster_record_id")
    assert not merged.duplicated(["roster_file_id", "hospital_id"]).any()


def test_lookalike_names_exist(rosters: dict[str, pd.DataFrame]) -> None:
    """The data must contain same-name hospitals in different cities, or matching is too easy."""
    cities_per_name = rosters["truth"].groupby("name")["city"].nunique()
    assert (cities_per_name > 1).any()
