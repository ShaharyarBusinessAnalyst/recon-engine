"""True sales, distributor tracing reports and clean chargeback claims."""

import random
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, TypeVar

import pandas as pd

from data_gen.contracts import build_wac_lookup, wac_on
from data_gen.hospitals import (
    Hospital,
    address_on,
    messy_address,
    messy_name,
    name_on,
    next_month,
)
from data_gen.membership import customers_by_hospital
from data_gen.reference import random_date, to_money
from data_gen.settings import GenSettings

MAIN_DISTRIBUTOR_SHARE = 0.8  # most hospitals buy mainly through one distributor
LINES_PER_MONTH = (2, 10)
QUANTITY = (1, 20)
REPORTED_HIN_RATE = 0.4

T = TypeVar("T")
PeriodIndex = dict[tuple[str, ...], list[tuple[date, date | None, Any]]]


def active(periods: Sequence[tuple[date, date | None, T]], day: date) -> T | None:
    """The value whose half-open period contains the day, or None."""
    for start, end, value in periods:
        if start <= day and (end is None or day < end):
            return value
    return None


def index_periods(
    df: pd.DataFrame,
    keys: list[str],
    value: str,
    start: str = "effective_from",
    end: str = "effective_to",
) -> PeriodIndex:
    """Group a table's effective periods by key, for fast 'what was true on day X' lookups."""
    index: PeriodIndex = {}
    for row in df.to_dict("records"):
        key = tuple(str(row[k]) for k in keys)
        index.setdefault(key, []).append((row[start], row[end], row[value]))
    return index


def make_sales(
    rng: random.Random,
    settings: GenSettings,
    hospitals: list[Hospital],
    customer_labels: pd.DataFrame,
    products: pd.DataFrame,
    product_wac: pd.DataFrame,
    contracts: pd.DataFrame,
    prices: pd.DataFrame,
    tiers: pd.DataFrame,
    primary_gpo_truth: pd.DataFrame,
    distributor_ids: list[str],
) -> dict[str, pd.DataFrame]:
    wac_lookup = build_wac_lookup(product_wac)
    contract_index = index_periods(
        contracts, ["gpo_id", "product_category"], "contract_id", "start_date", "expiration_date"
    )
    price_index = index_periods(prices, ["contract_id", "item_id", "tier"], "unit_price")
    tier_index = index_periods(tiers, ["customer_id", "contract_id"], "tier")
    primary_index = index_periods(primary_gpo_truth, ["hospital_id", "product_category"], "gpo_id")
    contract_info = {str(c["contract_id"]): c for c in contracts.to_dict("records")}
    customer_ids = customers_by_hospital(customer_labels)
    items = products.to_dict("records")

    our_hospitals = [h for h in hospitals if h.hospital_id in customer_ids]
    main_distributor = {h.hospital_id: rng.choice(distributor_ids) for h in our_hospitals}
    styles: dict[tuple[str, str, str, str], tuple[str, str]] = {}
    sends_hin: dict[tuple[str, str], bool] = {}
    invoice_counter = dict.fromkeys(distributor_ids, 0)

    sales: list[dict[str, object]] = []
    tracing_files: list[dict[str, object]] = []
    tracing_lines: list[dict[str, object]] = []
    claims: list[dict[str, object]] = []
    cb_lines: list[dict[str, object]] = []

    month = settings.start_date
    while month < settings.end_date:
        month_end = next_month(month)

        # One tracing file and one chargeback claim per distributor per month.
        tracing_file_ids: dict[str, str] = {}
        month_claims: dict[str, dict[str, object]] = {}
        totals = dict.fromkeys(distributor_ids, Decimal("0.00"))
        counts = dict.fromkeys(distributor_ids, 0)
        for d in distributor_ids:
            tracing_file_ids[d] = f"TF{len(tracing_files) + 1:04d}"
            tracing_files.append(
                {
                    "tracing_file_id": tracing_file_ids[d],
                    "distributor_id": d,
                    "period_start": month,
                    "period_end": month_end,
                    "received_at": month_end + timedelta(days=rng.randint(3, 10)),
                    "source_filename": f"{d}_tracing_{month:%Y%m}.csv",
                }
            )
            claim = {
                "claim_id": f"CLM{len(claims) + 1:05d}",
                "distributor_id": d,
                "distributor_claim_number": f"{d}-CB-{month:%Y%m}",
                "submitted_date": month_end + timedelta(days=rng.randint(5, 20)),
                "total_amount_claimed": Decimal("0.00"),
                "line_count": 0,
            }
            claims.append(claim)
            month_claims[d] = claim

        for h in our_hospitals:
            customer_id = customer_ids[h.hospital_id][0]  # duplicates share the same truth
            available = [
                i
                for i in items
                if i["launched_on"] <= month
                and (i["discontinued_on"] is None or i["discontinued_on"] > month)
            ]
            invoices: dict[str, tuple[str, date]] = {}
            line_numbers: dict[str, int] = {}

            for _ in range(rng.randint(*LINES_PER_MONTH)):
                main = main_distributor[h.hospital_id]
                dist = (
                    main if rng.random() < MAIN_DISTRIBUTOR_SHARE else rng.choice(distributor_ids)
                )
                if dist not in invoices:  # one invoice per hospital, distributor and month
                    invoice_counter[dist] += 1
                    invoices[dist] = (
                        f"{dist}-INV{invoice_counter[dist]:07d}",
                        random_date(rng, month, month_end),
                    )
                    line_numbers[dist] = 0
                line_numbers[dist] += 1
                invoice_number, invoice_date = invoices[dist]

                item = rng.choice(available)
                item_id = str(item["item_id"])
                category = str(item["product_category"])
                quantity = rng.randint(*QUANTITY)
                wac = wac_on(wac_lookup, item_id, invoice_date)

                # The truth chain: primary GPO -> contract -> tier -> price.
                gpo_id = active(primary_index.get((h.hospital_id, category), []), invoice_date)
                contract_id = (
                    active(contract_index.get((str(gpo_id), category), []), invoice_date)
                    if gpo_id is not None
                    else None
                )
                tier = (
                    active(tier_index.get((customer_id, str(contract_id)), []), invoice_date)
                    if contract_id is not None
                    else None
                )
                price_key = (str(contract_id), item_id, str(tier))
                price = (
                    active(price_index.get(price_key, []), invoice_date)
                    if tier is not None
                    else None
                )
                on_contract = price is not None
                unit_price = Decimal(str(price)) if on_contract else wac
                extended = to_money(unit_price * quantity)

                # How this distributor writes the hospital's name and address.
                name, address = name_on(h, invoice_date), address_on(h, invoice_date)
                style_key = (dist, h.hospital_id, name, address)
                if style_key not in styles:
                    styles[style_key] = (
                        messy_name(rng, name, 0.8),
                        messy_address(rng, address, 0.8),
                    )
                if (dist, h.hospital_id) not in sends_hin:
                    sends_hin[(dist, h.hospital_id)] = rng.random() < REPORTED_HIN_RATE
                reported_name, reported_address = styles[style_key]
                reported: dict[str, object] = {
                    "reported_customer_name": reported_name,
                    "reported_address": reported_address,
                    "reported_city": h.city,
                    "reported_state": h.state,
                    "reported_zip": h.zip_code,
                    "reported_hin": h.hin if sends_hin[(dist, h.hospital_id)] else None,
                    "reported_dea": None,
                }
                invoice_fields: dict[str, object] = {
                    "distributor_id": dist,
                    "distributor_invoice_number": invoice_number,
                    "invoice_line_number": line_numbers[dist],
                    "invoice_date": invoice_date,
                    "item_id": item_id,
                    "quantity": quantity,
                }

                tracing_line_id = f"TL{len(tracing_lines) + 1:06d}"
                tracing_lines.append(
                    {
                        "tracing_line_id": tracing_line_id,
                        "tracing_file_id": tracing_file_ids[dist],
                        **invoice_fields,
                        "unit_price": unit_price,
                        "extended_amount": extended,
                        **reported,
                    }
                )

                chargeback_line_id: str | None = None
                chargeback = Decimal("0.00")
                admin_fee = Decimal("0.00")
                if on_contract and contract_id is not None:
                    contract = contract_info[str(contract_id)]
                    chargeback = to_money((wac - unit_price) * quantity)
                    admin_fee = to_money(extended * Decimal(str(contract["admin_fee_rate"])))
                    chargeback_line_id = f"CBL{len(cb_lines) + 1:06d}"
                    cb_lines.append(
                        {
                            "chargeback_line_id": chargeback_line_id,
                            "claim_id": month_claims[dist]["claim_id"],
                            "contract_number_claimed": contract["contract_number"],
                            **invoice_fields,
                            "wac_claimed": wac,
                            "contract_price_claimed": unit_price,
                            "amount_claimed": chargeback,
                            **reported,
                            "is_resubmission": False,
                            "original_chargeback_line_id": None,
                        }
                    )
                    totals[dist] += chargeback
                    counts[dist] += 1

                sales.append(
                    {
                        "sale_id": f"S{len(sales) + 1:06d}",
                        "hospital_id": h.hospital_id,
                        "customer_id": customer_id,
                        **invoice_fields,
                        "true_gpo_id": gpo_id,
                        "true_contract_id": contract_id,
                        "true_tier": tier,
                        "true_unit_price": unit_price,
                        "true_wac": wac,
                        "true_chargeback": chargeback,
                        "true_admin_fee": admin_fee,
                        "tracing_line_id": tracing_line_id,
                        "chargeback_line_id": chargeback_line_id,
                    }
                )

        for d in distributor_ids:
            month_claims[d]["total_amount_claimed"] = totals[d]
            month_claims[d]["line_count"] = counts[d]
        month = month_end

    return {
        "tracing_file": pd.DataFrame(tracing_files),
        "sales_tracing_line": pd.DataFrame(tracing_lines),
        "chargeback_claim": pd.DataFrame(claims),
        "chargeback_line": pd.DataFrame(cb_lines),
        "labels/truth_sale": pd.DataFrame(sales),
    }
