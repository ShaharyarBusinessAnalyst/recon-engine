"""Run the whole generator: python -m data_gen.generate"""

import random
from dataclasses import asdict

import pandas as pd

from data_gen.contracts import make_contracts, make_prices_and_amendments, make_tier_bands
from data_gen.hospitals import make_customers, make_hospitals, make_memberships, make_rosters
from data_gen.membership import make_affiliations, make_tier_assignments
from data_gen.reference import (
    make_distributor,
    make_gpo,
    make_product,
    make_product_wac,
    write_table,
)
from data_gen.sales import make_sales
from data_gen.settings import GenSettings


def build_tables(settings: GenSettings) -> dict[str, pd.DataFrame]:
    rng = random.Random(settings.seed)

    gpo = make_gpo()
    distributor = make_distributor()
    products = make_product(rng, settings)
    product_wac = make_product_wac(rng, products, settings)
    contracts = make_contracts(rng, gpo, settings)
    tier_bands = make_tier_bands(contracts)
    prices, amendments = make_prices_and_amendments(rng, contracts, products, product_wac, settings)

    gpo_ids = [str(g) for g in gpo["gpo_id"]]
    hospitals = make_hospitals(rng, settings)
    memberships = make_memberships(rng, hospitals, gpo_ids, settings)
    customers, customer_labels = make_customers(rng, hospitals)
    roster_files, rosters, roster_labels = make_rosters(
        rng, hospitals, memberships, gpo_ids, settings
    )
    affiliations, primary_gpo_truth = make_affiliations(rng, memberships, customer_labels)
    tier_assignments, short_notice = make_tier_assignments(
        rng, memberships, contracts, customer_labels, settings
    )

    distributor_ids = [str(d) for d in distributor["distributor_id"]]
    sales_tables = make_sales(
        rng,
        settings,
        hospitals,
        customer_labels,
        products,
        product_wac,
        contracts,
        prices,
        tier_assignments,
        primary_gpo_truth,
        distributor_ids,
    )

    tables = {
        "gpo": gpo,
        "distributor": distributor,
        "product": products,
        "product_wac": product_wac,
        "contract": contracts,
        "contract_tier_band": tier_bands,
        "contract_price": prices,
        "contract_amendment": amendments,
        "customer": customers,
        "roster_file": roster_files,
        "gpo_roster": rosters,
        "primary_gpo_affiliation": affiliations,
        "tier_assignment": tier_assignments,
        "labels/truth_hospital": pd.DataFrame([asdict(h) for h in hospitals]),
        "labels/truth_membership": pd.DataFrame([asdict(m) for m in memberships]),
        "labels/truth_customer_hospital": customer_labels,
        "labels/truth_roster_hospital": roster_labels,
        "labels/truth_primary_gpo": primary_gpo_truth,
        "labels/planted_short_notice": short_notice,
    }
    tables.update(sales_tables)
    return tables


def main() -> None:
    settings = GenSettings()
    for name, df in build_tables(settings).items():
        write_table(df, name, settings)


if __name__ == "__main__":
    main()
