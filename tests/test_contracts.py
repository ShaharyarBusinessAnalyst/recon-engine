import random

import pandas as pd
import pytest

from data_gen.contracts import (
    build_wac_lookup,
    make_contracts,
    make_prices_and_amendments,
    wac_on,
)
from data_gen.reference import make_gpo, make_product, make_product_wac
from data_gen.settings import GenSettings


@pytest.fixture(scope="module")
def generated() -> dict[str, pd.DataFrame]:
    settings = GenSettings()
    rng = random.Random(settings.seed)
    products = make_product(rng, settings)
    product_wac = make_product_wac(rng, products, settings)
    contracts = make_contracts(rng, make_gpo(), settings)
    prices, amendments = make_prices_and_amendments(rng, contracts, products, product_wac, settings)
    return {"contracts": contracts, "prices": prices, "product_wac": product_wac}


def test_price_periods_never_overlap(generated: dict[str, pd.DataFrame]) -> None:
    prices = generated["prices"].sort_values(["contract_id", "item_id", "tier", "effective_from"])
    for _, group in prices.groupby(["contract_id", "item_id", "tier"]):
        rows = group.to_dict("records")
        for earlier, later in zip(rows, rows[1:], strict=False):
            assert earlier["effective_to"] <= later["effective_from"]


def test_higher_tier_never_costs_more(generated: dict[str, pd.DataFrame]) -> None:
    for _, group in generated["prices"].groupby(["contract_id", "item_id", "effective_from"]):
        by_tier = group.sort_values("tier")["unit_price"].tolist()
        assert by_tier == sorted(by_tier, reverse=True)


def test_contract_price_below_wac(generated: dict[str, pd.DataFrame]) -> None:
    lookup = build_wac_lookup(generated["product_wac"])
    for row in generated["prices"].to_dict("records"):
        assert row["unit_price"] < wac_on(lookup, str(row["item_id"]), row["effective_from"])


def test_one_active_contract_per_gpo_and_category(generated: dict[str, pd.DataFrame]) -> None:
    contracts = generated["contracts"].sort_values(["gpo_id", "product_category", "start_date"])
    for _, group in contracts.groupby(["gpo_id", "product_category"]):
        rows = group.to_dict("records")
        for earlier, later in zip(rows, rows[1:], strict=False):
            assert earlier["expiration_date"] <= later["start_date"]
