# Data Dictionary — `financials.csv`

One row per Palo Alto Networks (PANW) fiscal quarter, **FY2021 Q3 → FY2026 Q3** (21 quarters). PANW's fiscal year ends **July 31** (Q1≈Oct, Q2≈Jan, Q3≈Apr, Q4≈Jul).

## Sourcing & integrity guarantees

- **Primary source:** every figure is extracted verbatim from PANW's quarterly earnings press release — **SEC Form 8-K, Item 2.02, Exhibit 99.1** (CIK 1327567). The exact filing for each quarter is listed in the provenance table below; per-field verbatim evidence quotes are retained in `data/raw/earnings_extracted.json`.
- **Independent cross-check:** total revenue is reconciled against the **SEC XBRL `companyfacts` API** (`us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax`), pulled separately in `src/ingest.py`. All 16 quarters that have a discrete quarterly XBRL fact match the press-release figure exactly (Q4 is not tagged as a discrete quarter in XBRL, only as the full fiscal year).
- **Segment reconciliation:** `revenue_product + revenue_subscription == revenue_total` holds for all 21 quarters (enforced by a test).
- **No fabrication / no interpolation.** Where a metric was not disclosed in a given release, the cell is **blank** (e.g., `billings` after FY2024 Q1; `ngs_arr` before FY2024 Q4). Blanks are never filled with estimates.

## Fields

| Column | Definition | Source | Notes |
|---|---|---|---|
| `fiscal_quarter` | PANW fiscal quarter label, e.g. `FY2026Q3` | derived | FY ends Jul 31 |
| `period_end_date` | Quarter-end date (YYYY-MM-DD) | 8-K Ex-99.1 | |
| `revenue_total` | Total revenue, $M | Condensed Statements of Operations | Cross-checked vs XBRL |
| `revenue_product` | Product revenue, $M | Statements of Operations | hardware + perpetual |
| `revenue_subscription` | "Subscription and support" revenue, $M | Statements of Operations | recurring software/support |
| `inorganic_revenue` | Acquisition-attributable revenue **only where explicitly disclosed**, $M | 8-K highlights | 0 except **FY2026Q3 = 388** (CyberArk + Chronosphere) |
| `revenue_organic` | `revenue_total − inorganic_revenue`, $M | derived | what the forecast targets |
| `ngs_arr` | Next-Generation Security Annual Recurring Revenue, $M | 8-K highlights (stated in $B) | Non-GAAP operational metric; **first disclosed FY2024Q4** |
| `rpo` | Total Remaining Performance Obligations, $M | 8-K highlights (stated in $B) | GAAP (ASC 606); primary exogenous driver (20 quarters) |
| `billings` | Total/calculated billings, $M | "Calculation of Billings" table | **Discontinued after FY2024Q1** — PANW de-emphasized billings; later quarters blank |
| `non_gaap_op_margin` | Non-GAAP operating margin, % | 8-K reconciliation | blank where the release omitted the quarterly line; FY2026Q3 computed from disclosed op-income/revenue |
| `non_gaap_eps_reported` | Non-GAAP diluted EPS **as reported in that release**, $ | 8-K | per-share basis differs across splits — see `split_basis` |
| `non_gaap_eps_split_adj` | Non-GAAP diluted EPS on the **current** post-split basis, $ | derived | `reported / SPLIT_FACTORS[split_basis]` |
| `gaap_eps_diluted_reported` | GAAP diluted EPS (loss) as reported, $ | 8-K | negative = loss |
| `gaap_eps_diluted_split_adj` | GAAP diluted EPS on current post-split basis, $ | derived | |
| `guidance_revenue_next_q_low/high` | Management revenue guidance for the **next** quarter, $M | 8-K outlook | used as a benchmark in Stage 2 backtest |
| `split_basis` | Which stock-split regime the reported EPS is on | derived | see below |
| `accn` | SEC accession number of the source 8-K | EDGAR | |

## Stock splits (EPS continuity)

PANW executed two forward splits: **3-for-1 (Sep 2022)** and **2-for-1 (Dec 2024)**. Revenue, RPO, NGS ARR, and billings are unaffected; only per-share metrics are. `split_basis` tags each quarter, and `SPLIT_FACTORS` in `src/config.py` converts as-reported EPS to the current basis. Validation: FY2022Q4 reported non-GAAP EPS of $2.39, restated to ~$0.80 in the later FY2023Q4 comparative (2.39 / 3 = 0.797), confirming the 3-for-1 factor.

## Known gaps & caveats (honest limits)

- `billings` is unusable as a continuous driver (discontinued after FY2024Q1) — a deliberate PANW reporting change, not missing data.
- `ngs_arr` has only ~8 quarters of history, so it is a recent-only driver; `rpo` (20 quarters) is the primary exogenous input.
- `rpo` for FY2021Q3 was not stated in that release → blank.
- `inorganic_revenue` is captured **only** where PANW explicitly disclosed a dollar figure. The CyberArk (closed Feb 11, 2026) and Chronosphere acquisitions make FY2026Q3 onward partly inorganic; the $388M figure is the only quarter with an explicit split as of this dataset.

## Provenance — source filing per quarter

| Fiscal quarter | Accession | Exhibit 99.1 (earnings release) |
|---|---|---|
| FY2021Q3 | `0001327567-21-000012` | [ex991q321earningsrelease.htm](https://www.sec.gov/Archives/edgar/data/1327567/000132756721000012/ex991q321earningsrelease.htm) |
| FY2021Q4 | `0001327567-21-000020` | [ex991q421earningsrelease.htm](https://www.sec.gov/Archives/edgar/data/1327567/000132756721000020/ex991q421earningsrelease.htm) |
| FY2022Q1 | `0001327567-21-000037` | [ex991q122earningsrelease.htm](https://www.sec.gov/Archives/edgar/data/1327567/000132756721000037/ex991q122earningsrelease.htm) |
| FY2022Q2 | `0001327567-22-000006` | [ex991q222earningsrelease.htm](https://www.sec.gov/Archives/edgar/data/1327567/000132756722000006/ex991q222earningsrelease.htm) |
| FY2022Q3 | `0001327567-22-000014` | [ex991q322earningsrelease.htm](https://www.sec.gov/Archives/edgar/data/1327567/000132756722000014/ex991q322earningsrelease.htm) |
| FY2022Q4 | `0001327567-22-000020` | [ex991q422earningsrelease.htm](https://www.sec.gov/Archives/edgar/data/1327567/000132756722000020/ex991q422earningsrelease.htm) |
| FY2023Q1 | `0001327567-22-000035` | [ex991q123earningsrelease.htm](https://www.sec.gov/Archives/edgar/data/1327567/000132756722000035/ex991q123earningsrelease.htm) |
| FY2023Q2 | `0001327567-23-000005` | [ex991q223earningsrelease.htm](https://www.sec.gov/Archives/edgar/data/1327567/000132756723000005/ex991q223earningsrelease.htm) |
| FY2023Q3 | `0001327567-23-000012` | [ex991q323earningsrelease.htm](https://www.sec.gov/Archives/edgar/data/1327567/000132756723000012/ex991q323earningsrelease.htm) |
| FY2023Q4 | `0001327567-23-000020` | [ex991q423earningsrelease.htm](https://www.sec.gov/Archives/edgar/data/1327567/000132756723000020/ex991q423earningsrelease.htm) |
| FY2024Q1 | `0001327567-23-000030` | [ex991q124earningsrelease.htm](https://www.sec.gov/Archives/edgar/data/1327567/000132756723000030/ex991q124earningsrelease.htm) |
| FY2024Q2 | `0001327567-24-000003` | [ex991q224earningsrelease.htm](https://www.sec.gov/Archives/edgar/data/1327567/000132756724000003/ex991q224earningsrelease.htm) |
| FY2024Q3 | `0001327567-24-000015` | [ex991q324earningsrelease.htm](https://www.sec.gov/Archives/edgar/data/1327567/000132756724000015/ex991q324earningsrelease.htm) |
| FY2024Q4 | `0001327567-24-000023` | [ex991q424earningsrelease.htm](https://www.sec.gov/Archives/edgar/data/1327567/000132756724000023/ex991q424earningsrelease.htm) |
| FY2025Q1 | `0001327567-24-000036` | [ex991q125earningsrelease.htm](https://www.sec.gov/Archives/edgar/data/1327567/000132756724000036/ex991q125earningsrelease.htm) |
| FY2025Q2 | `0001327567-25-000006` | [ex991q225earningsrelease.htm](https://www.sec.gov/Archives/edgar/data/1327567/000132756725000006/ex991q225earningsrelease.htm) |
| FY2025Q3 | `0001327567-25-000015` | [ex991q325earningsrelease.htm](https://www.sec.gov/Archives/edgar/data/1327567/000132756725000015/ex991q325earningsrelease.htm) |
| FY2025Q4 | `0001327567-25-000024` | [ex991q425earningsrelease.htm](https://www.sec.gov/Archives/edgar/data/1327567/000132756725000024/ex991q425earningsrelease.htm) |
| FY2026Q1 | `0001327567-25-000032` | [ex991q126earningsrelease.htm](https://www.sec.gov/Archives/edgar/data/1327567/000132756725000032/ex991q126earningsrelease.htm) |
| FY2026Q2 | `0001327567-26-000003` | [ex991q226earningsrelease.htm](https://www.sec.gov/Archives/edgar/data/1327567/000132756726000003/ex991q226earningsrelease.htm) |
| FY2026Q3 | `0001327567-26-000012` | [ex991q326earningsrelease.htm](https://www.sec.gov/Archives/edgar/data/1327567/000132756726000012/ex991q326earningsrelease.htm) |
