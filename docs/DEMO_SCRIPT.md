# COD-Guard — exhibition walkthrough

All displayed orders and measured benchmark results are **SYNTHETIC**. The
conversation is a local simulator; no WhatsApp messages are sent.

Run `python scripts/build_demo.py` on the clean checkout once. Cache
Whisper with `python scripts/prepare_voice.py` while online. Start each
rehearsal or presentation with `python scripts/run_demo.py`. To reset,
close the running demo and run that same command. Each launch uses new
disposable SQLite and risk-model state with offline mode forced.

1. Open **Orders & risk**. Filter RED and explain the two distinct adverse
   signal groups required by the pre-reply policy for complete orders. The
   two address checks share one group. Show the rules score and the separate
   ML probability.
2. In **Verification**, select a RED order and enter `Ji theek hai, bhej dein`.
   Show SHIP and the durable reply history. Select a GREEN order and enter
   `جی نہیں`. Show HOLD_CANCEL. A denial overrides a pass and confirmation
   overrides a flag. `Kal bataunga` needs clarification and cannot erase an
   earlier explicit reply.
3. Use the typed Urdu reply as the live fallback for voice. The cached
   FLEURS clip is an optional station demo after the timed walkthrough.
   Select **Bundled Urdu sample**, then **Transcribe Urdu**, and show the
   imperfect read-speech transcript and UNCLEAR intent in the preview.
   The attributed clip and accuracy results are in [VOICE_ACCURACY.md](VOICE_ACCURACY.md).
4. In **Metrics & learning**, show BOTH FPR and FNR and the confusion matrix.
   Threshold selection used validation data; the shown threshold curve is a
   test diagnostic. Read the baseline v1 rates before retraining. Use the
   Round 2 verification and capacity sections in [the baseline report](EVAL_REPORT.md).
   Introduce the response rates as assumptions before you show the results.
5. Mark a demo outcome, show the pending-learning count, then click **Retrain
   from marked outcomes**. Show the new model ID/version and consumed outcome
   count. The 80 demo orders were reserved outside training/validation/test; the
   evaluation holdout stays unchanged. Report updated measurements honestly,
   including worsening results.

## Offline rehearsal · 20 November 2026

Measured using Streamlit AppTest on a clean Windows checkout at the Round 8
base, with the cached Whisper small model and a disposable launcher
session. The final pass verified that exhibition mode hid all three
features even with them enabled in tenant settings. Timings cover the
application actions. Browser, microphone and venue hardware were outside
this run.

| Action | Seconds |
| --- | ---: |
| Cold dashboard startup | 7.04 |
| RED filter and risk explanation | 0.74 |
| Roman Urdu confirmation | 0.81 |
| Urdu-script denial | 0.89 |
| Unclear reply preserves denial | 0.90 |
| Simulated voice unavailable through typed fallback | 1.72 |
| Baseline metrics and confusion matrix | 0.36 |
| Save outcome | 1.52 |
| Retrain and verify activated model | 7.55 |
| Restart and verify clean state | 1.14 |
| Cached real Urdu preview, optional | 17.32 |

The voice preview exceeded the 10-second live allowance and now sits
outside the timed sequence. It left the decision revision untouched.
Retraining consumed one marked outcome and preserved the 1,184-order
holdout. Restart restored the 80 seed orders, empty reply and outcome
history, and the baseline model. Reproduce with
`python scripts/rehearse_demo.py`.

See the [public benchmark](BENCHMARK.md) for the locked baseline and method.
On 1,184 synthetic test orders, baseline v1 has **16.47% FPR** and
**59.23% FNR**. A flag is AMBER or RED before a reply. The uncapped any-signal baseline has lower illustrative cost
(PKR 259,800 versus 274,600) and flags 907 of 1,184 orders. At an assumed
PKR 50 per attempt, a COD-Guard ranking had the lowest illustrative test cost
under each offline budget ceiling (10%, 20% and 30%) in two assumed response
settings. In the 30% comparison, the served candidate used 341 flags and the
winning experimental ranker used 355. The dashboard serves the threshold policy.

The six hypothetical outreach scenarios give **5.74%–17.83% FPR** and
**35.20%–64.01% FNR**. At the same assumed reply rates, flags-only outreach
gives 62.36% FNR and contacting every GREEN order as well gives 47.97% FNR.
These scenarios illustrate how a denial can catch a passed order. Customer
behavior and speech recognition accuracy require separate measurements.

“At a budget of about one in five ordinary synthetic orders, even an oracle
that knows how we generated the data captures just **28.75%** of expected
failures. A customer denial can give us information the risk score lacks.”

Competitors exist: **Tasdeek, Botaura, OrderWitness, DukaanFlow**. Do not claim
being first or make unverified claims about their capabilities. This build
actually demonstrates outcome-fed retraining plus Urdu voice transcription;
there are no merchant pilots. OrderNation's approximate 49–57 cash collections
per 100 COD orders came from one retailer across different measurement windows.
The exhibition uses generated orders.
