"""Run the whole generator: python -m data_gen.generate"""

import random

from data_gen.contracts import make_contracts, make_prices_and_amendments, make_tier_bands
from data_gen.reference import (
    make_distributor,
    make_gpo,
    make_product,
    make_product_wac,
    write_table,
)
from data_gen.settings import GenSettings


def main() -> None:
    settings = GenSettings()
    rng = random.Random(settings.seed)

    gpo = make_gpo()
    distributor = make_distributor()
    products = make_product(rng, settings)
    product_wac = make_product_wac(rng, products, settings)
    contracts = make_contracts(rng, gpo, settings)
    tier_bands = make_tier_bands(contracts)
    prices, amendments = make_prices_and_amendments(rng, contracts, products, product_wac, settings)

    tables = {
        "gpo": gpo,
        "distributor": distributor,
        "product": products,
        "product_wac": product_wac,
        "contract": contracts,
        "contract_tier_band": tier_bands,
        "contract_price": prices,
        "contract_amendment": amendments,
    }
    for name, df in tables.items():
        write_table(df, name, settings)


if __name__ == "__main__":
    main()
