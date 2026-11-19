# COD-Guard — exhibition walkthrough

All displayed orders and measured benchmark results are **SYNTHETIC**. The
conversation is a local simulator; no WhatsApp messages are sent.

1. Open **Orders & risk**. Filter RED and explain the two distinct adverse
   signal groups required by the pre-reply policy for complete orders. The
   two address checks share one group. Show the rules score and the separate
   ML probability.
2. In **Verification**, select a RED order and enter `Ji theek hai, bhej dein`.
   Show SHIP and the durable reply history. Select a GREEN order and enter
   `جی نہیں`. Show HOLD_CANCEL. A denial overrides a pass and confirmation
   overrides a flag. `Kal bataunga` needs clarification and cannot erase an
   earlier explicit reply.
3. Under voice, select **Bundled Urdu sample**, then **Transcribe Urdu**.
   Explain that this is a CC BY 4.0 FLEURS read-speech example, not a customer
   note. Show the actual imperfect transcript and UNCLEAR intent. Alternatively,
   rehearse a short Urdu order reply and the microphone before the show. The
   dashboard shows a verbatim preview before **Apply transcript to this order**.
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
