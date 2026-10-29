import pandas as pd
import pytest

from data_gen.generate import build_tables
from data_gen.settings import GenSettings


@pytest.fixture(scope="module")
def tables() -> dict[str, pd.DataFrame]:
    return build_tables(GenSettings())


def test_chargeback_math_is_correct(tables: dict[str, pd.DataFrame]) -> None:
    for row in tables["chargeback_line"].to_dict("records"):
        expected = (row["wac_claimed"] - row["contract_price_claimed"]) * row["quantity"]
        assert abs(row["amount_claimed"] - expected) <= 0.01


def test_clean_claims_match_the_truth(tables: dict[str, pd.DataFrame]) -> None:
    """Before errors are planted, every claimed price must equal the true price."""
    truth = tables["labels/truth_sale"].dropna(subset=["chargeback_line_id"])
    merged = tables["chargeback_line"].merge(truth, on="chargeback_line_id", suffixes=("", "_t"))
    assert len(merged) == len(tables["chargeback_line"])
    assert (merged["contract_price_claimed"] == merged["true_unit_price"]).all()


def test_invoice_lines_are_unique(tables: dict[str, pd.DataFrame]) -> None:
    keys = ["distributor_id", "distributor_invoice_number", "invoice_line_number"]
    assert not tables["chargeback_line"].duplicated(keys).any()


def test_some_sales_are_off_contract(tables: dict[str, pd.DataFrame]) -> None:
    """Off-contract sales are real; without them the engine is never tested on them."""
    assert tables["labels/truth_sale"]["chargeback_line_id"].isna().any()
