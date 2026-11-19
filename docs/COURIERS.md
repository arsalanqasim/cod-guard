# Courier outcomes (WS-E)

## CSV baseline

Upload UTF-8 CSV as multipart field `file` to `POST /integrations/couriers/outcomes/import` with a shadow tenant operator key. Use your existing queue order ID, not the store's order number. Confirm each shipment belongs to your store and each status is final. Up to 500 rows or 1 MiB; invalid rows reject the whole batch. This is an illustrative fixture:

```csv
order_id,courier,tracking_number,outcome,billed_fee_pkr
shop-order-1,postex,FIXTURE-001,delivered,180.50
shop-order-2,leopards,FIXTURE-002,returned,
shop-order-3,trax,FIXTURE-003,refused,170
```

`courier` accepts `postex`, `leopards`, `tcs`, `trax`, `other`. `billed_fee_pkr` is optional and must be the actual charge on a courier statement; blank is unknown, and zero requires explicit statement evidence. It is not COD amount or avoided cost. Replays do not add labels. Resolve conflicting labels through the existing audited order outcome correction before reimporting; mismatched evidence is excluded from retraining. The initial decision snapshot follows the existing outcome path; for retrospective imports it is not proof of what the operator saw before dispatch.

## TCS

After confirming access and the request contract with TCS, supply merchant bearer tokens via `COD_GUARD_TCS` (JSON keyed by tenant ID). `POST /integrations/couriers/tcs/orders/{order_id}/refresh` with `{ "tracking_number": "12345" }` reads only that shipment; the operator must supply the correct consignment for the order. Only a newest, unambiguous `Delivered` in the matching delivery history auto-labels. Unknown or non-final statuses never become failure labels; use CSV for returns and refusals pending provider-confirmed mappings. No shipment booking or automatic polling. See [API evidence](COURIER_API_EVIDENCE.md) for each carrier's gate. The request and label logic are fixture-tested, not merchant-tested.

## Shadow retraining

On the pilot host, after confirming the merchant has authorized this use, run `python backend/app/courier_evaluation.py --tenant TENANT --authorized-training`. It fits a local candidate using eligible outcome feedback in the existing trainer and reports both models' results on the same hash-locked synthetic holdout. It publishes neither the candidate nor any shipment-level data. Complete stored feature snapshots are required. A non-regression result is necessary, not evidence of live performance. New phone history, city×courier rates and seller rates stay off: there is no versioned point-in-time history for those features on the locked evaluation, and computing them from current outcomes would leak future labels. Before shipping any such feature, preregister an as-of history and independent evaluation; do not swap the old test set to make it pass.
