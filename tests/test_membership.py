import pandas as pd
import pytest

from data_gen.generate import build_tables
from data_gen.settings import GenSettings


@pytest.fixture(scope="module")
def tables() -> dict[str, pd.DataFrame]:
    return build_tables(GenSettings())


def test_tier_periods_never_overlap(tables: dict[str, pd.DataFrame]) -> None:
    tiers = tables["tier_assignment"].sort_values(["customer_id", "contract_id", "effective_from"])
    for _, group in tiers.groupby(["customer_id", "contract_id"]):
        rows = group.to_dict("records")
        for earlier, later in zip(rows, rows[1:], strict=False):
            assert earlier["effective_to"] <= later["effective_from"]


def test_reviews_give_90_days_notice_unless_planted(tables: dict[str, pd.DataFrame]) -> None:
    tiers = tables["tier_assignment"]
    reviews = tiers[tiers["reason"] == "quarterly_review"]
    planted = set(tables["labels/planted_short_notice"]["tier_assignment_id"])
    for row in reviews.to_dict("records"):
        days = (row["effective_from"] - row["notice_date"]).days
        if row["tier_assignment_id"] in planted:
            assert days < 90
        else:
            assert days >= 90


def test_some_affiliations_are_unconfirmed_guesses(tables: dict[str, pd.DataFrame]) -> None:
    """Without unconfirmed multi-GPO cases, E12 and A1 could never be tested."""
    assert (~tables["primary_gpo_affiliation"]["confirmed_by_customer"]).any()
