import random
from datetime import date, timedelta
from decimal import Decimal

import pandas as pd

from data_gen.settings import GenSettings

GPO_NAMES = [
    "Meridian Health Alliance",
    "Keystone Purchasing Partners",
    "Summit Care Collaborative",
    "Northstar Supply Network",
]

DISTRIBUTOR_NAMES = [
    "Atlas Medical Supply",
    "Harbor Health Distribution",
    "Pinnacle Surgical Logistics",
]

# Each category has its own item types and sizes, so names look realistic.
CATALOG: dict[str, tuple[list[str], list[str]]] = {
    "Surgical Instruments": (
        ["Retractor", "Forceps", "Needle Holder", "Scissors", "Clamp"],
        ["12 cm", "14 cm", "18 cm", "20 cm"],
    ),
    "Electrosurgery": (
        ["Electrode", "Pencil", "Grounding Pad", "Smoke Evacuator Tip"],
        ["Standard", "Extended", "Pediatric"],
    ),
    "Wound Closure": (
        ["Skin Stapler", "Staple Remover", "Closure Strip", "Tissue Adhesive"],
        ["Small", "Medium", "Large"],
    ),
    "Sutures": (
        ["Absorbable Suture", "Nylon Suture", "Silk Suture", "Polypropylene Suture"],
        ["2-0", "3-0", "4-0", "5-0"],
    ),
}

CENT = Decimal("0.01")


def to_money(value: float | Decimal) -> Decimal:
    """Round to exact cents."""
    return Decimal(str(value)).quantize(CENT)


def random_date(rng: random.Random, start: date, end: date) -> date:
    """A random date in [start, end): start included, end excluded."""
    span_days = (end - start).days
    return start + timedelta(days=rng.randrange(span_days))


def make_gpo() -> pd.DataFrame:
    rows = [
        {
            "gpo_id": f"GPO{i:02d}",
            "gpo_name": name,
            "admin_fee_report_template": f"template_gpo{i:02d}",
        }
        for i, name in enumerate(GPO_NAMES, start=1)
    ]
    return pd.DataFrame(rows)


def make_distributor() -> pd.DataFrame:
    rows = [
        {"distributor_id": f"DST{i:02d}", "distributor_name": name}
        for i, name in enumerate(DISTRIBUTOR_NAMES, start=1)
    ]
    return pd.DataFrame(rows)


def make_product(rng: random.Random, settings: GenSettings) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for i in range(1, settings.n_items + 1):
        category = rng.choice(list(CATALOG))
        nouns, sizes = CATALOG[category]
        item_name = f"{rng.choice(nouns)} {rng.choice(sizes)}"

        # About 10% launch during the period: these become amendment candidates.
        launched_mid_period = rng.random() < 0.10
        if launched_mid_period:
            launched_on = random_date(rng, settings.start_date, settings.end_date)
        else:
            launched_on = random_date(rng, date(2018, 1, 1), settings.start_date)

        # About 5% of established items are discontinued during the period.
        discontinued_on: date | None = None
        if not launched_mid_period and rng.random() < 0.05:
            discontinued_on = random_date(
                rng, settings.start_date + timedelta(days=90), settings.end_date
            )

        rows.append(
            {
                "item_id": f"ITM{i:04d}",
                "item_name": item_name,
                "product_category": category,
                "launched_on": launched_on,
                "discontinued_on": discontinued_on,
            }
        )
    return pd.DataFrame(rows)


def make_product_wac(
    rng: random.Random, products: pd.DataFrame, settings: GenSettings
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    wac_id = 1
    for item_id, launched_on in zip(products["item_id"], products["launched_on"], strict=True):
        wac = to_money(rng.uniform(20, 2000))
        period_start: date = max(launched_on, settings.start_date)

        # A price increase every 1 January strictly inside the period.
        for year in range(period_start.year + 1, settings.end_date.year + 1):
            increase_date = date(year, 1, 1)
            if increase_date >= settings.end_date:
                break
            rows.append(
                {
                    "product_wac_id": f"WAC{wac_id:05d}",
                    "item_id": item_id,
                    "wac": wac,
                    "effective_from": period_start,
                    "effective_to": increase_date,
                }
            )
            wac_id += 1
            pct = Decimal(str(round(rng.uniform(0.02, 0.06), 4)))
            wac = to_money(wac * (1 + pct))
            period_start = increase_date

        # The current WAC is open-ended: effective_to is empty.
        rows.append(
            {
                "product_wac_id": f"WAC{wac_id:05d}",
                "item_id": item_id,
                "wac": wac,
                "effective_from": period_start,
                "effective_to": None,
            }
        )
        wac_id += 1
    return pd.DataFrame(rows)


def write_table(df: pd.DataFrame, name: str, settings: GenSettings) -> None:
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    path = settings.output_dir / f"{name}.csv"
    df.to_csv(path, index=False)
    print(f"wrote {len(df):>6} rows -> {path}")


def main() -> None:
    settings = GenSettings()
    rng = random.Random(settings.seed)

    write_table(make_gpo(), "gpo", settings)
    write_table(make_distributor(), "distributor", settings)

    products = make_product(rng, settings)
    write_table(products, "product", settings)
    write_table(make_product_wac(rng, products, settings), "product_wac", settings)


if __name__ == "__main__":
    main()
