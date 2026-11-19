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
   test diagnostic. State the current metrics as displayed, including the high
   FN rate and any baseline the model does not beat. Do not quote the original
   brief's subset recall as overall recall or claim real-world accuracy.
5. Mark a demo outcome, show the pending-learning count, then click **Retrain
   from marked outcomes**. Show the new model ID/version and consumed outcome
   count. The 80 demo orders were reserved outside training/validation/test; the
   evaluation holdout stays unchanged. Report updated measurements honestly,
   including worsening results.

The baseline model has FPR 16.47%, FNR 59.23%; illustrative cost PKR 274,600 on
1,184 synthetic test orders. It beats ship-everything (PKR 390,650), but not the
aggressive any-signal baseline (PKR 259,800). Outcome-fed versions can differ.
These are modelled costs using FN=PKR 650 and FP=PKR 450, not merchant losses.

Competitors exist: **Tasdeek, Botaura, OrderWitness, DukaanFlow**. Do not claim
being first or make unverified claims about their capabilities. This build
actually demonstrates outcome-fed retraining plus Urdu voice transcription;
there are no merchant pilots. Reference COD statistics from the mission brief
must remain distinguished from this project's generated data.
