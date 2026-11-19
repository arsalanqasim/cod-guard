# Synthetic evaluation protocol

Choose features, candidate models, thresholds and any capacity or utilization
policy using training and validation only. Record the validation objective and
cost assumptions before evaluating a candidate on the test split.

The committed test lock hashes the sorted order IDs and the sorted pairs of
order ID and binary label. The test split measures the frozen policy. Test
threshold sweeps and oracle estimates are diagnostics. Use fresh held-out data
to confirm a change prompted by a test result. A changed split or corrected
label set requires a separately versioned benchmark and an explicit lock review.

The baseline v1 evaluation is kept in `data/evaluation.json` and
`docs/EVAL_REPORT.md`. Outcome-fed models receive their own versioned report.
Report their holdout counts, model ID and feedback count in a fresh section
with any differences from baseline v1. Marked demo outcomes remain synthetic.
