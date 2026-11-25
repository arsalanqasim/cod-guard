# Dispatch advice and address clarification

Prepaid and courier advice run in shadow. Address quality has its own queue
reason and at most one clarification draft per order. Each is opt-in by
tenant, and the offline exhibition launcher disables all three. The
recorded dispatch decision and its risk explanation keep their existing
inputs and authority.

## Enable for a shadow tenant

Set `COD_GUARD_DISPATCH_EXPERIMENTS` to a JSON object keyed by operator
tenant ID. Supply only the options that tenant uses.

```json
{
  "seller-tenant": {
    "prepaid": {"discount_pct": 5, "payment_method": "JazzCash"},
    "courier_choice": true,
    "address_quality": true
  }
}
```

Supported payment wording is JazzCash and Easypaisa. The dashboard and
authenticated order routes show the advice. Start verification with
`POST /orders/{order_id}/verification/preview` or the WhatsApp workflow.
The simulated preview contains the proposed offer and address message.
Cloud mode returns them as separate draft metadata while its approved
verification message retains the usual wording. Operators can review and
relay the address draft through their approved channel.

### Prepaid offers

The offer applies to an open AMBER order awaiting verification. Each
shadow preview labels the offer and leaves the order's decision unchanged.
`POST /orders/{order_id}/prepaid/outcome` records explicitly reported
`{"stage":"sent"}`, `{"stage":"accepted"}`, then `{"stage":"paid"}`.
Each stage is timestamped and idempotent. These are seller-reported
events. The preview makes no offer claim and records no payment.

**Synthetic simulation.** On the 1,184-order locked risk benchmark,
200 orders would receive the example 5% offer. With 60% replying, 30% of
replies accepting and 80% of acceptances paying, the model projects 120
replies, 36 acceptances and **28.8 prepaid conversions**. That is 14.4% of
eligible orders or 2.43% of the full holdout. The discount is the offer
setting, and the conversion probabilities are adjustable assumptions.
The simulation measures neither merchant take-up nor savings.

### Courier choice

For an order ready to ship, use imported terminal courier outcomes from
the same seller and normalized city. Count the literal `returned`
outcome, with delivered and refused in the terminal denominator. The
latest audited outcome supersedes the original evidence label. Use
`(returns + 20 × seller-wide return rate) / (city-courier outcomes + 20)`.
Require at least two couriers with at least five outcomes each. Evidence
shows both the observed sample count and smoothed rate. The seller owns
courier selection.

**Synthetic replay.** With 900 generated history rows and 360 independent
synthetic orders, the policy picked a courier on 360/360 orders.
Among 303 collected orders, the suggested courier matched the one that
collected in **116/303 (38.28%)**. Observed assigned returns were 57/360
(15.83%). Using the generator's known probabilities for the same orders,
the assigned mix had a 16.80% expected return rate. The recommended mix
had 11.67%, a **5.13 percentage-point reduction under the simulation**.
The counterfactual result follows the simulator assumptions, including
different rates by courier and city. It gives no estimate of seller
outcomes or capacity.

| Synthetic city | Recommendation | Smoothed rates in generated history |
| --- | --- | --- |
| Lahore | Leopards | Leopards 15.33%, PostEx 18.67%, TCS 21.17% |
| Karachi | PostEx | PostEx 7.00%, TCS 17.83%, Leopards 22.00% |
| Multan | TCS | TCS 14.50%, Leopards 17.83%, PostEx 18.67% |

Each city and courier cell had 100 historical outcomes in that replay.

### Address quality

CSV intake accepts an optional `address` column. Reviewed DM intake and
storefronts derive the same reason codes from the address fields they
already receive. Only the reason codes are retained. Orders without
available address text show `unavailable`. The check covers a short
address, a missing house or street identifier, landmark-only wording,
and a recognized differing or one-edit city spelling.

Starting verification on an open flagged order creates one persisted
clarification draft. Repeated previews read the existing draft. The draft
contains a generic request for house or flat number, street, area and
city. It is separate from buyer intent and never changes the risk score
or dispatch decision. See the [synthetic accuracy and reason-level results](DECISION_MODEL_EVAL.md#round-8-addendum--synthetic-address-quality).

### Reproduce the synthetic reports

Build the baseline with `python scripts/build_demo.py`, then run the
evaluation with the scenario's assumptions.

```text
python scripts/experiments/evaluate_dispatch_advice.py --reply-rate 0.60 --accept-rate 0.30 --payment-rate 0.80 --output dispatch-results.json
```
