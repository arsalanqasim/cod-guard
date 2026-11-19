# COD-Guard — exhibition walkthrough

All displayed orders and measured benchmark results are **SYNTHETIC**. The
conversation is a local simulator; no WhatsApp messages are sent.

1. Open **Orders & risk**. Filter RED and explain the independent adverse signals.
   A lone signal, including an ML estimate, cannot stop dispatch. A rules score
   is not a probability.
2. In **Verification**, select a RED order and enter `Ji theek hai, bhej dein`.
   Show SHIP and the durable reply history. Select a GREEN order and enter
   `جی نہیں`. Show HOLD_CANCEL. A denial overrides a pass and confirmation
   overrides a flag. `Kal bataunga` needs clarification and cannot erase an
   earlier explicit reply.
3. Under voice, select **Bundled Urdu sample**, then **Transcribe Urdu**.
   Explain that this is a CC BY 4.0 FLEURS read-speech example, not a customer
   note. Show the actual imperfect transcript and UNCLEAR intent. Alternatively,
   let the judge record or upload a short Urdu order reply. Previewing does not
   alter the order; **Apply transcript to this order** is explicit.
4. In **Metrics & learning**, show BOTH FPR and FNR and the confusion matrix.
   Threshold selection used validation data; the shown threshold curve is a
   test diagnostic. State both current rates as displayed. For the verification
   and capacity comparisons, use the Round 2 sections in [the evaluation report](EVAL_REPORT.md).
   Introduce the response rates as assumptions before you show the results.
5. Mark a demo outcome, show the pending-learning count, then click **Retrain
   from marked outcomes**. Show the new model ID/version and consumed outcome
   count. The 80 demo orders were reserved outside training/validation/test; the
   evaluation holdout stays unchanged. Report updated measurements honestly,
   including worsening results.

On 1,184 synthetic test orders, the pre-reply policy has **16.47% FPR** and
**59.23% FNR**. The uncapped any-signal baseline has lower illustrative cost
(PKR 259,800 versus 274,600) and flags 907 of 1,184 orders. At an assumed
PKR 50 per attempt, one of the COD-Guard rankings has the lowest illustrative
cost at each equal flag cap (10%, 20%, and 30%).

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
there are no merchant pilots. Reference COD statistics from the mission brief
must remain distinguished from this project's generated data.
