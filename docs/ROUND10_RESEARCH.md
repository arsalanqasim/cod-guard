# Round 10 research

Past activity and links between accounts have improved return-to-origin
(RTO) ranking on Indian platforms that can observe those signals. The
frozen [PK-REAL] dataset supports an experiment on past purchases within a
customer account. It has no shared identity attributes, reliable outcome
availability timestamps, or verification action logs. Those gaps limit
what the frozen holdout can establish. [Source projection and cohort lock](DATA_SOURCES.md)

## What the published results show

| Primary source | Evidence | Relevance to COD-Guard |
| --- | --- | --- |
| Meesho, AAAI 2026 | On Meesho's offline RTO test, TRUST scored 0.47 AUCPR and 68.3% precision versus 0.34 and 58.7% for XGBoost. That comparison changes the entire model. Adding graph embeddings to its own behavioral variant raised precision from 66.4% to 68.1% on a cohort with ordinary personal histories but structural links, from 58.9% to 63.4% on linked users with no prior RTO or cancellation, and from 59.3% to 62.5% on users with four orders or fewer. Its authors also reported about 9.6 percentage points better live precision versus XGBoost at fixed recall. | The graph ablations support testing whether tenant-local links add value after purchase history is controlled for. Meesho used identifiers such as phone, email, device and payment accounts, as well as supplier relationships and outcome sequences. An account ID alone cannot reproduce the graph or establish a Pakistani merchant effect. [Paper, §§3–5 and Tables 2–3](https://ojs.aaai.org/index.php/AAAI/article/download/41450/45411) |
| Flipkart and IIIT, WWW 2023 Companion | Their history baseline used RTO ratios by buyer, product, seller, category and location over multiple windows. The history-based random forest scored 85.7% precision and 40.3% recall on their test set. Adding social profile signals yielded 88.8% and 60.2%. | The comparison measured the incremental contribution of social data over trends. The lift of history over order-only features is unmeasured. Seller-local counts and recency are testable using purchase histories. [Paper, §3.1 and Table 2](https://cdn.iiit.ac.in/cdn/precog.iiit.ac.in/pubs/Flipkart_RTO_WWW_workshop_Cameraready.pdf) |
| Lim, Wang and Webster, *Production and Operations Management*, 2023 | In a Singapore randomized field experiment, risk-informed routing reduced the share of failed delivery attempts by 10% and reported a cost cut of $13 per route. The study randomized allocation to routing algorithms and measured delivery attempts. | Routing can change outcomes after dispatch. This result applies to within-route sequencing and first attempts. A test of courier switching or address clarification needs its own comparison and a terminal delivery outcome. [Study and field experiment](https://journals.sagepub.com/doi/pdf/10.1111/poms.13926) |

GoKwik's API describes address intelligence, intent scoring and signals
from its shopper network. Razorpay's risk report lists address quality and
historical buyer or postal-code RTO behavior across stores. These are the
vendors' descriptions of their input coverage. A seller can supply its own
addresses and basket history, while a cross-store history signal requires
separate authorized access. [GoKwik API](https://cdn.gokwik.co/rto-doc/rto-predict-api.pdf) ·
[Razorpay risk report](https://razorpay.com/docs/payments/magic-checkout/analytics/rto/risk-report)

Shopify documents device and network signals and historical data from
across its stores for eligible card-order recommendations. Stripe Radar
uses payment details and network history to evaluate payment fraud.
The documentation describes signals for payment risk. COD delivery
failure requires courier data and a separate evaluation.
[Shopify fraud indicators](https://help.shopify.com/en/manual/fulfillment/managing-orders/protecting-orders/fraud-analysis) ·
[Stripe transaction risk](https://docs.stripe.com/radar/transaction-risk-prevention)

Pakistani provider Wavvy reports a merchant's returns falling from 28%
to 18.5% after introducing WhatsApp confirmation, landmark collection and
courier alerts. The provider's before-and-after case study reports the
combined change among shipments. The effect of confirmation alone, the
probability that a non-responder would collect an order and transferable
verification resolution rates remain unmeasured in the evidence reviewed.
[Wavvy case study and workflow](https://wavvy.pk/case-studies/urban-trendz)

## Experiments the available data can support

- **Past purchases.** Join by customer within tenant and use only strictly
  earlier purchase days for [PK-REAL], where order times are day-granular.
  Compare the current purchase fields and binary repeat flag with
  counts, recency, and basket history under the same customer and time
  splits. Report new-account and returning-account results separately.
  Terminal statuses define evaluation labels, but their availability at
  checkout cannot be reconstructed. A fixed maturity lag, if explored, is
  a sensitivity assumption. Future data should carry both the outcome
  event time and its ingestion time so a correction or late import cannot
  enter an earlier prediction. [PK-REAL field mapping](DATA_SOURCES.md) ·
  [Feast point-in-time join reference](https://github.com/feast-dev/feast/blob/master/docs/getting-started/concepts/point-in-time-joins.md)
- **Identity links.** A follow-up with authorized seller data could first
  compare exact links using stable customer and verified contact keys.
  Test exposure and outcome history separately before testing graph
  embeddings. Build an order's features from links known at its cutoff,
  and test on isolated identity components in a later time window. Measure
  key coverage, churn, unusually large shared-key groups and results on
  orders with and without earlier links. A shared phone or address is
  ambiguous evidence and can reflect a household, business or recycled
  number. The frozen [PK-REAL] archive has no fields for this ablation.
  [Meesho graph design and ablations](https://ojs.aaai.org/index.php/AAAI/article/download/41450/45411) ·
  [PK-REAL field mapping](DATA_SOURCES.md)
- **Selective verification.** Compare the risk score at equal verification
  volume as well as under modeled costs. Include verify-all and report
  verification volume, committed errors, and false holds. For a calibrated
  failure probability `p`, Round 9's assumed losses are `650p` for
  shipping, `450(1-p)` for holding, and `230-180p` for verifying. Without
  capacity or safety constraints, their crossings imply shipping below
  about 0.277 and holding above about 0.815. The verification loss embeds
  60% correct resolution and a delay penalty for unresolved genuine
  orders. These cutoffs describe that scenario. The assumed resolution
  and fallback for non-response can change the policy ranking.
  [Round 9 cost assumptions](ROUND9_EVAL.md) ·
  [Franc et al. on classification with rejection](https://jmlr.org/papers/v24/21-0048.html)

## Evidence needed for an intervention claim

GoKwik documents partial payment at checkout and reports lower RTO for
brands enabling it. Its write-up leaves the treatment allocation, sample
sizes and complete denominators unspecified. ProfitBox360's ₹99-deposit
example calculates 348 versus 364 delivered orders per 1,000 checkouts
from its stated conversion and return rates. The write-up attributes the
rates to client data and surveys and assumes every order ships in its
worked business example. Treat both as first-party commercial reports
with uncertain transferability. [GoKwik partial COD](https://www.gokwik.co/blog/partial-cash-on-delivery-your-tool-to-uplift-prepaid-conversions) ·
[ProfitBox360 deposit example](https://www.profitbox360.com/research/india/ecommerce/partial-cod-vs-full-cod-india)

Verification, address correction, courier allocation and prepayment
can change what is observed. A blocked order has no courier outcome under
shipping, and observed delivery among buyers who prepaid is selective.
Treat explicit denial, no response, and dispatch as separately timestamped
events. For an approved seller trial, assign eligible orders to a
documented existing workflow or an alternative, keep safety exclusions in
both arms, and record allocation probabilities when applying off-policy
estimators. Track net cost and delivered orders per eligible placed order,
including delays and orders that never ship. Prepaid conversions and RTO
among dispatched parcels alone miss the effect on genuine buyers who
leave. The frozen data can support scenario comparisons, while estimating
a causal effect requires actions, outcomes and overlap between policies.
[Lakkaraju et al. on selective labels](https://www.cs.cornell.edu/home/kleinber/kdd17-selective.pdf) ·
[Dudík et al. on historical policy evaluation](https://icml.cc/2011/papers/554_icmlpaper.pdf)
