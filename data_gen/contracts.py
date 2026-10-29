"""Contracts, tier bands, contract prices and amendments (truth tables)."""

import random
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from decimal import Decimal

import pandas as pd

from data_gen.reference import random_date, to_money
from data_gen.settings import GenSettings

CATEGORY_CODES = {
    "Surgical Instruments": "SI",
    "Electrosurgery": "ES",
    "Wound Closure": "WC",
    "Sutures": "SU",
}

# Annual spend bands, from Shahar's US Surgitech contracts.
TIER_BANDS: list[tuple[int, Decimal, Decimal | None]] = [
    (1, Decimal("0"), Decimal("25000")),
    (2, Decimal("25000"), Decimal("50000")),
    (3, Decimal("50000"), Decimal("75000")),
    (4, Decimal("75000"), None),
]

CONTRACT_TERM_YEARS = 3
GPO_CATEGORY_COVERAGE = 0.8  # share of GPO x category pairs with a contract
RENEWAL_RATE = 0.5  # share of in-period expirations that get renewed
PRICE_CHANGE_RATE = 0.25  # share of contracts with a mid-term price cut
RETRO_RATE = 0.4  # share of amendments signed after their effective date


@dataclass
class WacPeriod:
    effective_from: date
    effective_to: date | None
    wac: Decimal


@dataclass
class PriceRow:
    contract_price_id: str
    contract_id: str
    item_id: str
    tier: int
    unit_price: Decimal
    effective_from: date
    effective_to: date
    source_amendment_id: str | None


@dataclass
class AmendmentRow:
    amendment_id: str
    contract_id: str
    amendment_number: str
    amendment_type: str
    signed_date: date
    effective_date: date


def pct_factor(pct: float) -> Decimal:
    """Turn a discount like 0.2 into an exact multiplier like 0.8000."""
    return Decimal(str(round(1 - pct, 4)))


def build_wac_lookup(product_wac: pd.DataFrame) -> dict[str, list[WacPeriod]]:
    lookup: dict[str, list[WacPeriod]] = {}
    for row in product_wac.to_dict("records"):
        period = WacPeriod(
            effective_from=row["effective_from"],
            effective_to=row["effective_to"],
            wac=Decimal(str(row["wac"])),
        )
        lookup.setdefault(str(row["item_id"]), []).append(period)
    return lookup


def wac_on(lookup: dict[str, list[WacPeriod]], item_id: str, day: date) -> Decimal:
    """The WAC active on a given day (half-open periods)."""
    periods = lookup[item_id]
    for p in periods:
        if p.effective_from <= day and (p.effective_to is None or day < p.effective_to):
            return p.wac
    return periods[0].wac  # before WAC history starts: use the earliest known WAC


def make_contracts(rng: random.Random, gpo: pd.DataFrame, settings: GenSettings) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for g in gpo.to_dict("records"):
        gpo_id = str(g["gpo_id"])
        gpo_name = str(g["gpo_name"])
        gpo_code = "".join(word[0] for word in gpo_name.split())
        for category, cat_code in CATEGORY_CODES.items():
            if rng.random() > GPO_CATEGORY_COVERAGE:
                continue
            start = date(rng.randint(2022, 2024), rng.randint(1, 12), 1)
            while start < settings.end_date:
                expiration = date(start.year + CONTRACT_TERM_YEARS, start.month, 1)
                n = len(rows) + 1
                rows.append(
                    {
                        "contract_id": f"CTR{n:03d}",
                        "contract_number": f"{gpo_code}-{cat_code}-{start.year}-{n:03d}",
                        "contract_name": f"{gpo_name} {category} Agreement",
                        "gpo_id": gpo_id,
                        "product_category": category,
                        "admin_fee_rate": Decimal(str(round(rng.uniform(0.01, 0.03), 4))),
                        "start_date": start,
                        "expiration_date": expiration,
                    }
                )
                renewed = expiration < settings.end_date and rng.random() < RENEWAL_RATE
                if not renewed:
                    break
                start = expiration  # the renewal starts the day the old one ends
    return pd.DataFrame(rows)


def make_tier_bands(contracts: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for contract_id in contracts["contract_id"]:
        for tier, low, high in TIER_BANDS:
            rows.append(
                {
                    "contract_tier_band_id": f"TB{len(rows) + 1:05d}",
                    "contract_id": contract_id,
                    "tier": tier,
                    "min_annual_spend": low,
                    "max_annual_spend": high,
                }
            )
    return pd.DataFrame(rows)


def make_prices_and_amendments(
    rng: random.Random,
    contracts: pd.DataFrame,
    products: pd.DataFrame,
    product_wac: pd.DataFrame,
    settings: GenSettings,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    wac_lookup = build_wac_lookup(product_wac)
    prices: list[PriceRow] = []
    amendments: list[AmendmentRow] = []

    def tier_prices(item_id: str, day: date) -> dict[int, Decimal]:
        """Tier 1 is 15-35% below WAC; each higher tier is another 2-5% lower."""
        price = wac_on(wac_lookup, item_id, day) * pct_factor(rng.uniform(0.15, 0.35))
        result: dict[int, Decimal] = {}
        for tier, _, _ in TIER_BANDS:
            result[tier] = to_money(price)
            price = price * pct_factor(rng.uniform(0.02, 0.05))
        return result

    def add_price(
        contract_id: str,
        item_id: str,
        tier: int,
        unit_price: Decimal,
        effective_from: date,
        effective_to: date,
        amendment_id: str | None,
    ) -> None:
        prices.append(
            PriceRow(
                contract_price_id=f"CP{len(prices) + 1:06d}",
                contract_id=contract_id,
                item_id=item_id,
                tier=tier,
                unit_price=unit_price,
                effective_from=effective_from,
                effective_to=effective_to,
                source_amendment_id=amendment_id,
            )
        )

    def add_amendment(
        contract_id: str, contract_number: str, amendment_type: str, effective: date
    ) -> str:
        if rng.random() < RETRO_RATE:
            signed = effective + timedelta(days=rng.randint(15, 60))  # retroactive
        else:
            signed = effective - timedelta(days=rng.randint(7, 30))
        seq = sum(1 for a in amendments if a.contract_id == contract_id) + 1
        amendment_id = f"AMD{len(amendments) + 1:05d}"
        amendments.append(
            AmendmentRow(
                amendment_id=amendment_id,
                contract_id=contract_id,
                amendment_number=f"{contract_number}-A{seq:02d}",
                amendment_type=amendment_type,
                signed_date=signed,
                effective_date=effective,
            )
        )
        return amendment_id

    for c in contracts.to_dict("records"):
        contract_id = str(c["contract_id"])
        contract_number = str(c["contract_number"])
        start: date = c["start_date"]
        expiration: date = c["expiration_date"]
        category_items = products[products["product_category"] == c["product_category"]]

        # 1. Items on the contract from day one, or added later by amendment.
        for item in category_items.to_dict("records"):
            item_id = str(item["item_id"])
            launched: date = item["launched_on"]
            if launched <= start:
                for tier, price in tier_prices(item_id, start).items():
                    add_price(contract_id, item_id, tier, price, start, expiration, None)
            elif launched < expiration:
                amendment_id = add_amendment(contract_id, contract_number, "item_add", launched)
                for tier, price in tier_prices(item_id, launched).items():
                    add_price(contract_id, item_id, tier, price, launched, expiration, amendment_id)

        # 2. Some contracts get a mid-term price cut on part of their items.
        if rng.random() >= PRICE_CHANGE_RATE:
            continue
        window_start = max(start, settings.start_date) + timedelta(days=30)
        window_end = min(expiration, settings.end_date) - timedelta(days=30)
        if window_start >= window_end:
            continue
        change_day = random_date(rng, window_start, window_end)
        active = [
            p
            for p in prices
            if p.contract_id == contract_id and p.effective_from < change_day < p.effective_to
        ]
        item_ids = sorted({p.item_id for p in active})
        if not item_ids:
            continue
        amendment_id = add_amendment(contract_id, contract_number, "price_change", change_day)
        cut_items = set(rng.sample(item_ids, max(1, len(item_ids) * 3 // 10)))
        cut = pct_factor(rng.uniform(0.03, 0.08))
        for p in active:
            if p.item_id in cut_items:
                old_end = p.effective_to
                p.effective_to = change_day  # close the old price period
                add_price(
                    contract_id,
                    p.item_id,
                    p.tier,
                    to_money(p.unit_price * cut),
                    change_day,
                    old_end,
                    amendment_id,
                )

    return (
        pd.DataFrame([asdict(p) for p in prices]),
        pd.DataFrame([asdict(a) for a in amendments]),
    )
