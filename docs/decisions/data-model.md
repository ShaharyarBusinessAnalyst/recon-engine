# Data model: GPO domain

This document defines every table the engine reads, what one row means, how the tables connect, which errors the engine detects, and how ambiguous cases are ruled.

## Reference and contract tables

### gpo
Grain: one row = one GPO.
Primary key: gpo_id
Columns: gpo_id, gpo_name, admin_fee_report_template (config key for that GPO's report layout)

### distributor
Grain: one row = one distributor.
Primary key: distributor_id
Columns: distributor_id, distributor_name

### product
Grain: one row = one item (catalog number).
Primary key: item_id
Columns: item_id, item_name, product_category, launched_on, discontinued_on (nullable)

### product_wac
Grain: one row = one WAC for one item for one effective period.
Primary key: product_wac_id
Columns: product_wac_id, item_id (FK → product), wac, effective_from, effective_to
Rule: periods never overlap for the same item_id.

### contract
Grain: one row = one contract (one GPO, one product category).
Primary key: contract_id
Columns: contract_id, contract_number (the external number distributors cite), contract_name,
         gpo_id (FK → gpo), product_category, admin_fee_rate, start_date, expiration_date
Rule: start_date < expiration_date. One active contract per gpo_id and product_category on any date.

### contract_amendment
Grain: one row = one signed amendment to one contract.
Primary key: amendment_id
Columns: amendment_id, contract_id (FK → contract), amendment_number, amendment_type (item_add | price_change | term_extension),
         signed_date, effective_date
Rule: effective_date may be earlier than signed_date. That is a retroactive amendment, and it triggers re-adjudication of past lines.

### contract_tier_band
Grain: one row = one tier's annual spend range on one contract.
Primary key: contract_tier_band_id
Columns: contract_tier_band_id, contract_id (FK → contract), tier (1–4), min_annual_spend, max_annual_spend (nullable for the top tier)
Rule: bands on a contract are contiguous, with no gaps and no overlaps. Tier 1 starts at 0.

### contract_price
Grain: one row = one price for one item at one tier on one contract, for one effective period.
Primary key: contract_price_id
Columns: contract_price_id, contract_id (FK → contract), item_id (FK → product), tier (1–4),
         unit_price, effective_from, effective_to, source_amendment_id (FK → contract_amendment, nullable)
Rules: periods never overlap for the same contract_id, item_id and tier. A higher tier never has a higher price than a lower tier on the same date. unit_price < WAC on the same date.

---

## Customer and membership tables

### customer
Grain: one row = one customer in the manufacturer's customer master.
Primary key: customer_id
Columns: customer_id, customer_name, address, city, state, zip_code, latitude, longitude,
         health_system (parent IDN, nullable), gln (nullable), hin (nullable), dea (nullable)
Note: no GPO column. GPO membership changes over time and can differ by category, so it lives in primary_gpo_affiliation.

### roster_file
Grain: one row = one roster file received from one GPO.
Primary key: roster_file_id
Columns: roster_file_id, gpo_id (FK → gpo), as_of_date, received_at, source_filename, row_count

### gpo_roster (raw snapshot)
Grain: one row = one member as listed in one roster file.
Primary key: roster_record_id
Columns: roster_record_id, roster_file_id (FK → roster_file), gpo_id (FK → gpo), gpo_member_id,
         member_name, address, city, state, zip_code, health_system, gln, hin, dea,
         eligibility_start, eligibility_end (as stated by the GPO, nullable)
Rule: gpo_id + gpo_member_id + roster_file_id never repeats.
Note: effective ranges per member are computed later in dbt from consecutive snapshots.

### customer_member_match (derived: entity resolution output)
Grain: one row = one customer and roster-record pair evaluated in one matching run.
Primary key: match_id
Columns: match_id, match_run_id, customer_id (FK → customer), roster_record_id (FK → gpo_roster),
         name_score, address_score, city_state_score, overall_score,
         method (exact | fuzzy | llm | human), outcome (match | no_match | needs_review),
         decided_by (rule | model name | reviewer id), model_version (nullable), prompt_version (nullable),
         rationale (text: which fields drove the decision), decided_at
Rule: within one match_run_id, a roster record has at most one outcome = match.

### primary_gpo_affiliation
Grain: one row = one customer's primary GPO for one product category, for one effective period.
Primary key: affiliation_id
Columns: affiliation_id, customer_id (FK → customer), product_category, gpo_id (FK → gpo),
         effective_from, effective_to, confirmed_by_customer (bool), confirmation_source (email | portal | contract | none),
         confirmed_on (nullable)
Rule: periods never overlap for the same customer_id and product_category.

### tier_assignment
Grain: one row = one tier for one customer on one contract, for one effective period.
Primary key: tier_assignment_id
Columns: tier_assignment_id, customer_id (FK → customer), contract_id (FK → contract), tier (1–4),
         reason (initial_negotiated | quarterly_review), notice_date (nullable), effective_from, effective_to
Rules: periods never overlap for the same customer_id and contract_id. When reason = quarterly_review, effective_from >= notice_date + 90 days. An initial negotiated assignment needs no notice.

---

## Transaction tables (raw)

### tracing_file
Grain: one row = one sales tracing file received from one distributor.
Primary key: tracing_file_id
Columns: tracing_file_id, distributor_id (FK → distributor), period_start, period_end, received_at, source_filename

### sales_tracing_line (raw, 867-style)
Grain: one row = one invoice line reported by one distributor.
Primary key: tracing_line_id
Columns: tracing_line_id, tracing_file_id (FK → tracing_file), distributor_id (FK → distributor),
         distributor_invoice_number, invoice_line_number, invoice_date,
         item_id (FK → product), quantity, unit_price, extended_amount,
         reported_customer_name, reported_address, reported_city, reported_state, reported_zip,
         reported_hin (nullable), reported_dea (nullable)
Rule: distributor_id + distributor_invoice_number + invoice_line_number never repeats.

### chargeback_claim (raw, 844 header)
Grain: one row = one chargeback submission from one distributor.
Primary key: claim_id
Columns: claim_id, distributor_id (FK → distributor), distributor_claim_number, submitted_date, total_amount_claimed, line_count

### chargeback_line (raw, 844 detail)
Grain: one row = one invoice line claimed in one chargeback submission.
Primary key: chargeback_line_id
Columns: chargeback_line_id, claim_id (FK → chargeback_claim), distributor_id (FK → distributor),
         contract_number_claimed, distributor_invoice_number, invoice_line_number, invoice_date,
         item_id (FK → product), quantity, wac_claimed, contract_price_claimed, amount_claimed,
         reported_customer_name, reported_address, reported_city, reported_state, reported_zip,
         reported_hin (nullable), reported_dea (nullable),
         is_resubmission (bool), original_chargeback_line_id (FK → chargeback_line, nullable)
Duplicate key: distributor_id + distributor_invoice_number + invoice_line_number may appear only once across claims that were not rejected.
Why not a hard unique constraint: a distributor can legitimately resubmit a line after a rejection. A resubmission must be flagged (is_resubmission) and point to the original. A repeat that does neither is a duplicate claim.
Note: a negative quantity is a credit (a return) and reverses an earlier line.

---

## Derived tables (built in later phases)

- **chargeback_decision:** one row per chargeback line per adjudication run: expected values, decision, exception codes, amount approved.
- **exception:** one row per detected error on a line: error code, dollars at risk, route, status.
- **admin_fee_line:** one row per tracing line: resolved customer, attributed GPO, fee amount, attribution confidence.
- **audit_log:** append-only; one row per decision or human action (who, what, when, why).

---

## Error taxonomy

"True" values are always looked up as of the line's `invoice_date`, using half-open effective periods.

| # | Error | Detection rule |
|---|---|---|
| E01 | Wrong tier price | Resolve the customer, then find the true tier in `tier_assignment` and the true price in `contract_price` (contract, item, tier). Flag when `contract_price_claimed` ≠ the true price **and** equals a different tier's valid price. |
| E02 | New tier claimed before effective | `contract_price_claimed` equals the price for a tier whose `tier_assignment` for this customer has `effective_from > invoice_date` (notice given, change not yet effective). |
| E03 | Ineligible member | The resolved customer is not on the contract GPO's roster snapshot covering the invoice date, **or** their primary GPO for the contract's category on that date is a different GPO. |
| E04 | Expired contract | `invoice_date` is before `start_date` or on/after `expiration_date`, with no term-extension amendment covering it. |
| E05 | Item not on contract | No `contract_price` row exists for (contract, item) active on the invoice date. This includes items added by an amendment whose effective date is later. |
| E06 | Duplicate claim | The same distributor + invoice number + line number already exists in a non-rejected claim, and this line is not a flagged resubmission of a rejected original. |
| E07 | Extension math error | `amount_claimed` ≠ (`wac_claimed` − `contract_price_claimed`) × `quantity`, beyond a $0.01 tolerance. |
| E08 | Price matches no valid tier | `contract_price_claimed` matches no tier's price on the contract on the invoice date (typically below every valid price, inflating the claim). |
| E09 | WAC mismatch | `wac_claimed` ≠ the `product_wac` active on the invoice date (e.g. the post-increase WAC claimed on a pre-increase invoice). |
| E10 | Missed retro credit | A retroactive amendment (`effective_date < signed_date`) lowers a price. Lines invoiced between those dates and already paid at the old price are owed an additional credit. Found by re-adjudication after the amendment loads. |
| E11 | Admin fee to wrong hospital | A tracing line is attributed to a customer whose match is wrong. In production, this surfaces as a roster member matched to two customers, a name-only match with an address conflict, or a match below the confidence threshold. In evals, it is scored against generator truth. |
| E12 | Admin fee to wrong GPO | The fee is attributed to a GPO other than the customer's confirmed primary GPO for the item's category on the invoice date, or attributed at all when the customer has several GPOs and no confirmed primary. |

Planted error rate in the generator: about 7% of lines, spread across E01–E12, with labels kept as ground truth.

---

## Ambiguous cases and rulings

Each ruling is also written into the generator's labels, so the matching engine is scored against it.

| # | Case | Ruling |
|---|---|---|
| A1 | Hospital is on two GPO rosters for the same category, with no confirmed primary GPO. | Chargeback: valid if the hospital is on the roster of the GPO whose contract was cited. Admin fee: **held and escalated** until the customer confirms a primary GPO; never guessed. |
| A2 | Invoice dated before contract expiry; claim submitted after expiry. | Valid. The invoice date governs, provided the claim arrives within the claim window (default 90 days, set in config). After the window: auto-reject. |
| A3 | Hospital first appears in the March roster file, but the invoice is dated in February. | Escalate. If the roster states an `eligibility_start` on or before the invoice date, accept; otherwise treat it as ineligible (E03). |
| A4 | Tier change recorded with less than 90 days' notice (an internal data error, not a distributor error). | The change is not effective until notice + 90 days. Claims at the old tier are valid. Flag the assignment row as an internal data-quality issue. |
| A5 | Same invoice and line number, but a different quantity, not flagged as a resubmission. | Not an automatic duplicate (E06), since the values differ. Escalate as a possible correction. |
| A6 | Negative quantity (credit/return). | Valid only if a matching original line was claimed and paid. Reverse that amount; otherwise escalate. |
| A7 | Hospital renamed or merged mid-year (old name in the roster, new name in tracing). | Entity resolution decides. A match supported by address and health system goes to the LLM grey zone, then human review if confidence is below threshold. |
| A8 | Claimed price equals the contract price exactly, but the item was added by an amendment signed after the invoice date with a retroactive effective date. | Valid. The amendment's effective date governs, not its signed date. |
