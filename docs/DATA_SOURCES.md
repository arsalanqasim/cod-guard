# Round 9 data sources

## [PK-REAL] Pakistan’s Largest E-Commerce Dataset

Retrieved the Kaggle publisher’s version 2 archive on **20 November 2026**.
Kaggle metadata lists “Data files © Original Authors” and provides no
reuse licence. The licence is **unstated**. Round 9 uses the archive only
for development evaluation. The owner chose private local storage. The
repository contains aggregate counts and SHA-256 locks, and the host only
accepts tenant-bound artifacts built from each seller’s own authorized
data. [Kaggle dataset](https://www.kaggle.com/datasets/zusmani/pakistans-largest-ecommerce-dataset) ·
[Publisher metadata](https://www.kaggle.com/api/v1/datasets/view/zusmani/pakistans-largest-ecommerce-dataset)

[PK-REAL] The source contains 584,524 line items across 408,782 order IDs
and 115,326 customer IDs. The 271,960 COD line items represent 182,449
distinct orders and 76,068 customer IDs. The brief’s rounded line-item
count is larger than the distinct COD order count.

| Source field | COD-Guard mapping and use |
| --- | --- |
| `increment_id` | Private `order_id`. One basket per distinct ID. |
| `item_id` | Rejects repeated or missing source item records. No serving feature or published identifier. |
| `Customer ID` | Private cohort key. A strictly earlier distinct COD order day supplies `is_repeat_customer`. Same-day ties supply no repeat flag. |
| `created_at` | Purchase date for chronological partitions and repeat history. The source provides days, so `order_hour` is unavailable. |
| `grand_total` | `amount_pkr`, once per basket. The order total must agree across its rows and be positive. |
| `qty_ordered` | `items_count`, the sum of positive integer line quantities. |
| `payment_method` | Strictly `cod`, with consistent method across each basket. |
| `status` | `label_failed`. All `complete` lines label a success proxy. Lines in `canceled`, `refund`, or `order_refunded` label a noncollection proxy. Every line in a basket must have the same binary label. Other statuses remain unlabelled. |
| `sku`, `category_name_1`, `price`, `discount_amount`, `sales_commission_code` | No shared serving features. The basket total already represents the full amount. |
| `Working Date`, `Year`, `Month`, `Customer Since`, `M-Y`, `FY` | Source calendar and signup summaries. Purchase-day chronology comes from `created_at`. |
| `BI Status`, ` MV ` | Source accounting fields excluded from purchase-time scoring. |
| `Unnamed: 21` through `Unnamed: 25` | Empty source columns. |

The source provides no customer names, product names, phones, phone
validity, phone-linked failures, phone velocity, delivery address,
address-word or landmark measurements, city, or timestamped past
delivery/refusal counts. All remain unavailable to the incumbent
evaluation. Order fulfilment statuses are proxies for settlement. A
cancellation may precede dispatch. The source lacks delivery timestamp,
remittance, courier invoice, verification attempts and dispatch history.
The candidate uses only amount, item count and the purchase-time repeat
flag. `data_source` is assigned by the evaluator.

[PK-REAL] Projection excluded 920 structurally invalid baskets, 18,246
with incomplete or ambiguous labels and zero with mixed binary labels,
leaving 163,283 eligible distinct orders. The cohort procedure first
assigns a stable SHA-256 customer bucket, then includes only the order
dates within that bucket's chronological window. Orders outside the
intersection are excluded. The train and validation boundaries are
whole purchase days, and every customer belongs to at most one split.
The test window cannot contribute labels, rows, or model selection to
the earlier windows. [Frozen source and cohort lock](../data/pk_real.v1.lock.json)

| [PK-REAL] cohort | Dates inclusive | Orders | Customers | Failed proxies |
| --- | --- | ---: | ---: | ---: |
| Train | 2016-07-01 to 2017-06-02 | 60,628 | 22,405 | 17,465 |
| Validation | 2017-06-03 to 2017-11-23 | 6,581 | 3,935 | 2,916 |
| Test | 2017-11-24 to 2018-08-27 | 6,211 | 4,036 | 2,778 |

[PK-REAL] The customer/date intersection excluded a further 89,863
otherwise eligible orders. This restricts external generalization.
Local reproduction verifies the archive and all three cohort hashes
before fitting.

## [PK-SYNTH] COD-Guard synthetic benchmark

The checked-in generator, rows and split lock retain their merged Round
8 content. Round 9 uses the original synthetic holdout as the second
test set and the original incumbent training procedure. Only the three
portable purchase-time features reach the real-trained candidate. These
are generated examples with modeled outcomes. [Metric protocol](METRIC_PROTOCOL.md) ·
[Synthetic test lock](../data/test_split.lock.json)
