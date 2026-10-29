"""Primary GPO affiliations (our records vs. the truth) and tier assignments."""

import random
from datetime import date, timedelta

import pandas as pd

from data_gen.contracts import CATEGORY_CODES
from data_gen.hospitals import Membership
from data_gen.settings import GenSettings

CONFIRMATION_RATE = 0.7  # multi-GPO hospitals that confirmed their primary GPO
TIER_WEIGHTS = [0.4, 0.3, 0.2, 0.1]  # initial tiers 1-4
REVIEW_CHANGE_RATE = 0.15  # chance a quarterly review changes the tier
SHORT_NOTICE_RATE = 0.03  # planted A4: change recorded with under 90 days' notice
OPEN_END = date(9999, 12, 31)  # stands in for "no end date" while sorting


def customers_by_hospital(customer_labels: pd.DataFrame) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for row in customer_labels.to_dict("records"):
        result.setdefault(str(row["hospital_id"]), []).append(str(row["customer_id"]))
    return result


def add_months(day: date, months: int) -> date:
    """Shift a first-of-month date by whole months."""
    total = day.month - 1 + months
    return date(day.year + total // 12, total % 12 + 1, day.day)


def quarter_starts(start: date, end: date) -> list[date]:
    """1 Jan, 1 Apr, 1 Jul and 1 Oct dates in [start, end)."""
    day = date(start.year, ((start.month - 1) // 3) * 3 + 1, 1)
    if day < start:
        day = add_months(day, 3)
    result = []
    while day < end:
        result.append(day)
        day = add_months(day, 3)
    return result


def make_affiliations(
    rng: random.Random, memberships: list[Membership], customer_labels: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    customer_ids = customers_by_hospital(customer_labels)
    by_hospital: dict[str, list[Membership]] = {}
    for m in memberships:
        by_hospital.setdefault(m.hospital_id, []).append(m)

    rows: list[dict[str, object]] = []
    truth: list[dict[str, object]] = []
    for hospital_id in sorted(customer_ids):
        ms = by_hospital[hospital_id]
        options = sorted({m.gpo_id for m in ms})
        preferred = {cat: rng.choice(options) for cat in CATEGORY_CODES}
        confirmed = {cat: rng.random() < CONFIRMATION_RATE for cat in CATEGORY_CODES}

        # Split time at every date a membership starts or ends.
        boundaries = sorted(
            {m.effective_from for m in ms} | {m.effective_to or OPEN_END for m in ms}
        )
        for seg_start, seg_end in zip(boundaries, boundaries[1:], strict=False):
            active = sorted(
                m.gpo_id
                for m in ms
                if m.effective_from <= seg_start
                and (m.effective_to is None or seg_start < m.effective_to)
            )
            if not active:
                continue
            effective_to = None if seg_end == OPEN_END else seg_end
            for category in CATEGORY_CODES:
                true_gpo = preferred[category] if preferred[category] in active else active[0]
                if len(active) == 1:
                    recorded, is_confirmed, source = true_gpo, True, "contract"
                elif confirmed[category]:
                    recorded, is_confirmed, source = true_gpo, True, rng.choice(["email", "portal"])
                else:
                    recorded, is_confirmed, source = rng.choice(active), False, "none"  # a guess
                truth.append(
                    {
                        "hospital_id": hospital_id,
                        "product_category": category,
                        "gpo_id": true_gpo,
                        "effective_from": seg_start,
                        "effective_to": effective_to,
                    }
                )
                for customer_id in customer_ids[hospital_id]:
                    rows.append(
                        {
                            "affiliation_id": f"AFF{len(rows) + 1:05d}",
                            "customer_id": customer_id,
                            "product_category": category,
                            "gpo_id": recorded,
                            "effective_from": seg_start,
                            "effective_to": effective_to,
                            "confirmed_by_customer": is_confirmed,
                            "confirmation_source": source,
                        }
                    )
    return pd.DataFrame(rows), pd.DataFrame(truth)


def make_tier_assignments(
    rng: random.Random,
    memberships: list[Membership],
    contracts: pd.DataFrame,
    customer_labels: pd.DataFrame,
    settings: GenSettings,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    customer_ids = customers_by_hospital(customer_labels)
    rows: list[dict[str, object]] = []
    short_notice: list[dict[str, object]] = []

    for m in memberships:
        if m.hospital_id not in customer_ids:
            continue  # not our customer: no tier with us
        for c in contracts[contracts["gpo_id"] == m.gpo_id].to_dict("records"):
            start: date = max(c["start_date"], m.effective_from)
            end: date = c["expiration_date"]
            if m.effective_to is not None:
                end = min(end, m.effective_to)
            if start >= end:
                continue

            # Each period: (tier, reason, notice_date, effective_from, is_short_notice)
            tier = rng.choices([1, 2, 3, 4], weights=TIER_WEIGHTS)[0]
            periods: list[tuple[int, str, date | None, date, bool]] = [
                (tier, "initial_negotiated", None, start, False)
            ]
            review_from = max(start, settings.start_date)
            for notice in quarter_starts(review_from, min(end, settings.end_date)):
                if rng.random() >= REVIEW_CHANGE_RATE:
                    continue
                new_tier = min(4, max(1, tier + rng.choice([-1, 1])))
                if new_tier == tier:
                    continue
                short = rng.random() < SHORT_NOTICE_RATE
                effective = notice + timedelta(days=60) if short else add_months(notice, 3)
                if effective >= end or effective <= periods[-1][3]:
                    continue
                periods.append((new_tier, "quarterly_review", notice, effective, short))
                tier = new_tier

            for i, (tier_i, reason, notice_date, eff_from, short) in enumerate(periods):
                eff_to = periods[i + 1][3] if i + 1 < len(periods) else end
                for customer_id in customer_ids[m.hospital_id]:
                    tier_assignment_id = f"TA{len(rows) + 1:06d}"
                    rows.append(
                        {
                            "tier_assignment_id": tier_assignment_id,
                            "customer_id": customer_id,
                            "contract_id": c["contract_id"],
                            "tier": tier_i,
                            "reason": reason,
                            "notice_date": notice_date,
                            "effective_from": eff_from,
                            "effective_to": eff_to,
                        }
                    )
                    if short and notice_date is not None:
                        short_notice.append(
                            {
                                "tier_assignment_id": tier_assignment_id,
                                "recorded_effective_from": eff_from,
                                "true_effective_from": notice_date + timedelta(days=90),
                            }
                        )
    return pd.DataFrame(rows), pd.DataFrame(short_notice)
