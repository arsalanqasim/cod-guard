# Round 7 decision model evaluation

**Keep the rules parser for automated verification.** All three local contenders failed the adoption gate. Fine-tuned MiniLM was the only model with a validated operating threshold. It committed 49 held-out decisions and got 26 wrong, including four `CONFIRM → HOLD` cases. The rules committed 26 and got zero wrong on this corpus. FastText is the smallest measured candidate for shadow evaluation. Hosted candidates remain unmeasured.

## WS-1 · Reply benchmark

[Reply corpus v1](../data/reply_intents.v1.jsonl) contains 493 rows. The [SHA-256 lock](../data/reply_evaluation.v1.lock.json) covers both corpora. The evaluator verifies canonical UTF-8 with LF line endings, split sizes, reply IDs, and family and normalized text separation. The reply corpus digest is `2c1db743167c41f979ad300103cbb47318c983cd3d531c3f547d4255fd902313`.

- **198 train**, **72 validation**, **144 novel test**, **79 known regressions**. Novel test has 48 rows per language and 36 per label. All generated variants of each phrasing family, including its three language forms, live in one split. The known cases come from parser, voice, and webhook tests and both production reviews (historical commits `0286ce1` and `ad0d3af`). The rules were designed with known cases in view, so the novel test is reported separately.
- Labels represent whole-order `CONFIRM` or `DENY`, a requested `MODIFICATION`, or `UNCLEAR`. Scoped changes are modifications. Conditional, hypothetical, timed and contradictory replies require clarification. Roman Urdu includes spelling variants such as `g`, `jee`, and `ji`, code-switching, and indirect refusals. The non-linguistic rows are empty and null legacy regression inputs. Transport commands such as STOP are still handled separately by WhatsApp.
- **Top-1 accuracy** covers all four labels. **Brier** is mean summed squared probability error across those labels, and **ECE** uses ten equal-width top-confidence bins. The rules use one-hot scores for a deterministic reference. **Coverage** is the fraction with an above-threshold CONFIRM or DENY. **Committed error** includes commitments on any gold UNCLEAR or MODIFICATION. A zero denominator leaves the rate undefined.
- The supervised models use temperature scaling fit on validation only (fastText 0.491, fine-tuned MiniLM 0.742). The zero-shot model uses softmax over four fixed NLI entailment logits with no task training. Each model takes the lowest fixed-grid cutoff from 0.60 to 0.99 that yields at least one commit and zero validation commit errors. When no cutoff qualifies, 0.99 is shown for comparison.
- The evaluation requires nonempty novel-test commitments in both critical families, zero wrong commitments across those families, overall committed error at or below rules, higher novel-test top-1 accuracy, and ECE of at most 0.10. Local models also need warm CPU p95 below 100 ms and serving artifacts below 250 MB. The benchmark measures single replies after ten warmups on Windows with an Intel Core i7-13620H. ONNX uses two inference threads. Serving sizes include tokenizers and exclude training-only files and shared runtime packages.

| Contender | Serving artifact | Cutoff | Validation commits | Verdict |
| --- | ---: | ---: | ---: | --- |
| Rules | Built-in | 1.00 | 0/72 | Baseline |
| fastText | 3.17 MB | 0.99 (no validated threshold) | 0/72 | Did not pass |
| Fine-tuned MiniLM INT8 | 127.16 MB | 0.85 | 13/72 | Did not pass |
| Zero-shot MiniLMv2 NLI INT8 | 124.50 MB | 0.99 (no validated threshold) | 0/72 | Did not pass |
| Ollama Qwen2.5 0.5B / Llama 3.2 1B | 398 MB / 1.3 GB published | — | — | Size screen failed |
| Celeris-1.1 Decision | Hosted | — | — | Billing and credentials unavailable |
| Jev 1.14 | Hosted | — | — | Credentials unavailable |
| d1.2-ultra | Hosted | — | — | Credentials unavailable |

The published Ollama tags exceeded the size budget, so CPU latency and accuracy were unmeasured. Celeris documents an activated workspace, payment method, and prepaid credit. No approved provider key or no-commitment premium access was available in this run. Published Decision Index results are in the brief as candidate leads. [Qwen Ollama tag](https://ollama.com/library/qwen2.5:0.5b) · [Llama Ollama tag](https://ollama.com/library/llama3.2:1b) · [Celeris setup](https://docs.celeris.ai/quickstart) · [Liquid availability](https://www.liquid.ai/blog/d1-2)

### Held-out results, novel test and regressions combined

| Contender | Language | N | Top-1 accuracy | Brier | ECE | Wrong / committed | Coverage | Warm CPU p95 (ms) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Rules | All | 223 | 45.3% | 1.094 | 0.547 | 0/26 (0.0%) | 26/223 (11.7%) | 0.02 |
| Rules | English | 96 | 52.1% | 0.958 | 0.479 | 0/11 (0.0%) | 11/96 (11.5%) | 0.01 |
| Rules | Roman Urdu | 61 | 37.7% | 1.246 | 0.623 | 0/7 (0.0%) | 7/61 (11.5%) | 0.01 |
| Rules | Urdu script | 64 | 40.6% | 1.188 | 0.594 | 0/8 (0.0%) | 8/64 (12.5%) | 0.02 |
| Rules | Other | 2 | 100.0% | 0.000 | 0.000 | — | 0/2 (0.0%) | 0.01 |
| fastText | All | 223 | 52.0% | 0.663 | 0.121 | — | 0/223 (0.0%) | 0.03 |
| fastText | English | 96 | 52.1% | 0.718 | 0.198 | — | 0/96 (0.0%) | 0.03 |
| fastText | Roman Urdu | 61 | 50.8% | 0.636 | 0.172 | — | 0/61 (0.0%) | 0.03 |
| fastText | Urdu script | 64 | 51.6% | 0.607 | 0.099 | — | 0/64 (0.0%) | 0.03 |
| fastText | Other | 2 | 100.0% | 0.612 | 0.668 | — | 0/2 (0.0%) | 0.02 |
| Fine-tuned MiniLM INT8 | All | 223 | 48.0% | 0.696 | 0.181 | 26/49 (53.1%) | 49/223 (22.0%) | 5.88 |
| Fine-tuned MiniLM INT8 | English | 96 | 47.9% | 0.788 | 0.302 | 24/42 (57.1%) | 42/96 (43.8%) | 5.90 |
| Fine-tuned MiniLM INT8 | Roman Urdu | 61 | 39.3% | 0.776 | 0.162 | 1/1 (100.0%) | 1/61 (1.6%) | 5.70 |
| Fine-tuned MiniLM INT8 | Urdu script | 64 | 57.8% | 0.484 | 0.132 | 1/6 (16.7%) | 6/64 (9.4%) | 5.58 |
| Fine-tuned MiniLM INT8 | Other | 2 | 0.0% | 0.607 | 0.500 | — | 0/2 (0.0%) | 2.41 |
| Zero-shot MiniLMv2 NLI INT8 | All | 223 | 22.9% | 0.880 | 0.326 | — | 0/223 (0.0%) | 18.74 |
| Zero-shot MiniLMv2 NLI INT8 | English | 96 | 24.0% | 0.818 | 0.287 | — | 0/96 (0.0%) | 18.69 |
| Zero-shot MiniLMv2 NLI INT8 | Roman Urdu | 61 | 23.0% | 0.932 | 0.354 | — | 0/61 (0.0%) | 18.60 |
| Zero-shot MiniLMv2 NLI INT8 | Urdu script | 64 | 21.9% | 0.918 | 0.349 | — | 0/64 (0.0%) | 18.61 |
| Zero-shot MiniLMv2 NLI INT8 | Other | 2 | 0.0% | 1.025 | 0.578 | — | 0/2 (0.0%) | 12.80 |

### Novel-test results

| Contender | Language | N | Top-1 accuracy | Brier | ECE | Wrong / committed | Coverage | Warm CPU p95 (ms) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Rules | All | 144 | 25.0% | 1.500 | 0.750 | — | 0/144 (0.0%) | 0.02 |
| Rules | English | 48 | 25.0% | 1.500 | 0.750 | — | 0/48 (0.0%) | 0.01 |
| Rules | Roman Urdu | 48 | 25.0% | 1.500 | 0.750 | — | 0/48 (0.0%) | 0.01 |
| Rules | Urdu script | 48 | 25.0% | 1.500 | 0.750 | — | 0/48 (0.0%) | 0.02 |
| fastText | All | 144 | 54.9% | 0.594 | 0.064 | — | 0/144 (0.0%) | 0.03 |
| fastText | English | 48 | 62.5% | 0.552 | 0.142 | — | 0/48 (0.0%) | 0.04 |
| fastText | Roman Urdu | 48 | 50.0% | 0.642 | 0.172 | — | 0/48 (0.0%) | 0.03 |
| fastText | Urdu script | 48 | 52.1% | 0.590 | 0.105 | — | 0/48 (0.0%) | 0.03 |
| Fine-tuned MiniLM INT8 | All | 144 | 56.3% | 0.583 | 0.101 | 7/21 (33.3%) | 21/144 (14.6%) | 5.94 |
| Fine-tuned MiniLM INT8 | English | 48 | 68.8% | 0.481 | 0.148 | 5/16 (31.3%) | 16/48 (33.3%) | 6.08 |
| Fine-tuned MiniLM INT8 | Roman Urdu | 48 | 41.7% | 0.773 | 0.157 | 1/1 (100.0%) | 1/48 (2.1%) | 6.06 |
| Fine-tuned MiniLM INT8 | Urdu script | 48 | 58.3% | 0.494 | 0.189 | 1/4 (25.0%) | 4/48 (8.3%) | 5.54 |
| Zero-shot MiniLMv2 NLI INT8 | All | 144 | 25.0% | 0.882 | 0.318 | — | 0/144 (0.0%) | 20.62 |
| Zero-shot MiniLMv2 NLI INT8 | English | 48 | 25.0% | 0.850 | 0.302 | — | 0/48 (0.0%) | 20.20 |
| Zero-shot MiniLMv2 NLI INT8 | Roman Urdu | 48 | 25.0% | 0.904 | 0.327 | — | 0/48 (0.0%) | 19.62 |
| Zero-shot MiniLMv2 NLI INT8 | Urdu script | 48 | 25.0% | 0.892 | 0.324 | — | 0/48 (0.0%) | 20.32 |

### Dispatch-critical errors

Each critical family is defined by the gold whole-order intent. A wrong accepted label causes a dispatch override in the opposite direction. Review-only commitments are measured separately. The last column shows opposite top-1 labels before applying abstention, including ones the operating cutoff rejected.

| Contender | DENY → SHIP wrong / committed | CONFIRM → HOLD wrong / committed | Review-only commitments | Unthresholded opposite labels (DENY / CONFIRM gold) |
| --- | ---: | ---: | ---: | ---: |
| Rules | 0/16 (52 total) | 0/10 (46 total) | 0 | 0 / 0 |
| fastText | 0/0 (52 total) | 0/0 (46 total) | 0 | 6 / 17 |
| Fine-tuned MiniLM INT8 | 0/16 (52 total) | 4/11 (46 total) | 22 | 5 / 15 |
| Zero-shot MiniLMv2 NLI INT8 | 0/0 (52 total) | 0/0 (46 total) | 0 | 0 / 0 |

Fine-tuned MiniLM's validation cutoff accepted 13 replies with zero wrong. In novel test it accepted 21 with seven wrong. It held orders for unqualified confirmations such as “No cancellation please, get the complete order out to me” and committed to conditional cancellation in “Cancel the whole order next week if you haven't sent it.” It also committed on 19 known review-only cases. FastText and zero-shot MiniLM found no usable operating point. Agreement with the existing rules would limit commits to the rules’ existing recognized phrases. Keep both the signed-button authority and operator review flow. Collect operator labels and evaluate a fresh, independently labeled merchant holdout before revisiting adoption. The synthetic corpus gives no estimate of merchant error rates or operator load.

## WS-3 · DM extraction

The [DM corpus](../data/dm_extraction.v1.jsonl) contains 18 synthetic chats, six in each language form. It includes labeled lines, normal chat, seller versus buyer numbers, missing values, and later corrections. Evaluate the final buyer name, phone, address and items. Scores use casefolded, whitespace-normalized exact matches and existing Pakistani phone normalization. Correctly blank fields count in per-field accuracy. The present-field column excludes missing gold values.

| Extractor | All four exact | Name | Phone | Address | Items | Present fields correct | Missing / wrong / spurious |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Rules | 4/18 | 12/18 | 12/18 | 13/18 | 8/18 | 17/44 | 25 / 2 / 0 |
| LaMini-Flan-T5 | 1/18 | 3/18 | 4/18 | 4/18 | 4/18 | 1/44 | 14 / 29 / 14 |

The labeled-line parser usually omitted unlabeled details. It kept an older item count and an older address when a later turn changed them. LaMini-Flan-T5 often emitted commentary, copied the wrong field, or returned prose for missing fields. It extracted one of 44 present values and got one conversation fully right by leaving all four fields empty. Keep seller-reviewed extraction. [LaMini-Flan-T5 ONNX checkpoint](https://huggingface.co/Xenova/LaMini-Flan-T5-77M)

## Reproduce on CPU

Use the base requirements and optional benchmark dependencies below in an activated virtual environment. The application and normal checks do not load the experiment dependencies or model weights.

```powershell
python -m pip install fasttext-community==0.11.8 tokenizers==0.23.3 onnxruntime==1.32.0 transformers==5.23.0 onnx==1.23.2 onnxscript==0.7.2
python -m pip install torch==2.15.0+cpu --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple
hf download sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 config.json model.safetensors tokenizer.json tokenizer_config.json special_tokens_map.json --revision e8f8c211226b894fcb81acc59f3b34ba3efd5f42 --local-dir .venv/round7/original
hf download onnx-community/multilingual-MiniLMv2-L6-mnli-xnli-ONNX config.json tokenizer.json onnx/model_int8.onnx --revision ca5daf3d11b6c4b3143b1f4602a2edfb64c3ad7e --local-dir .venv/round7/zero
hf download Xenova/LaMini-Flan-T5-77M tokenizer.json onnx/encoder_model_int8.onnx onnx/decoder_model_int8.onnx --revision ac7ed8d --local-dir .venv/round7/dm
$env:HF_HUB_OFFLINE = '1'
python scripts/experiments/evaluate_reply_models.py --work-dir .venv/round7/run --minilm-checkpoint .venv/round7/original --zero-shot .venv/round7/zero --dm-model .venv/round7/dm
```

The script writes per-split and per-language metrics, threshold decisions, wrong commit IDs and DM failure examples to `metrics.json` in the work directory. FastText uses word and character n-grams. MiniLM trains the final encoder block and a linear head for six epochs, then exports and evaluates dynamic INT8 ONNX. LaMini-Flan-T5 gets one extractive prompt per field with greedy decoding. The model downloads contain public weights and tokenizers. Scoring uses local inference. [MiniLM source checkpoint](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2) · [Zero-shot ONNX checkpoint](https://huggingface.co/onnx-community/multilingual-MiniLMv2-L6-mnli-xnli-ONNX)

## Round 8 addendum · Reply-model rematch

**The rules retain verification authority.** Both ensemble policies failed
the frozen gate. These are offline experiments. The policies’ proposed
commits include the errors introduced when a model expands beyond the
rules.

### What was frozen before scoring

The reply manifest and its original 198 train, 72 validation, 144 novel
test and 79 known regression rows stayed fixed. Round 7 had already
reported the held-out results on these corpora. The Round 8 run used the
train and validation rows for fitting and selection, wrote the configuration
and artifact hashes to a plan, then scored both finalists in one holdout
pass. The plan’s SHA-256 was
`c499fdaf3ae5822084aa59908344073dfcdafd8587cdcfab56ecc6aac9ddaf1c`.

- FastText swept 12 combinations of word and character n-grams, learning
  rate (0.15 or 0.35), and epochs (30 or 80). Four word-only fits
  produced NaN. Selection among the eight completed runs maximized the
  number of safe validation commits, then top-1 validation accuracy.
  The selected fit used word bigrams, character 2–4-grams, 0.35 learning
  rate and 80 epochs.
- MiniLM fine-tuned the last encoder block for 14 epochs and ran the INT8
  export. Both models were temperature-scaled on validation.
- Per-language cutoffs allow a model commit when rules agree and the
  agreement cutoff is met, or when rules abstain and the strictly higher
  expansion cutoff is met. A conflict abstains. Cutoffs maximize the
  number of error-free validation commitments with ties favoring higher
  cutoffs. 1.01 disables expansion.

| Policy | English agreement / expansion | Roman Urdu | Urdu script | Validation wrong / committed |
| --- | --- | --- | --- | ---: |
| fastText | 0.90 / 1.01 | 0.70 / 0.80 | 0.70 / 0.80 | 0/3 |
| MiniLM | 0.70 / 0.80 | 0.90 / 0.95 | 0.70 / 0.80 | 0/14 |

### Final policy results

| Policy | All commits | All wrong / committed | Novel commits | Novel wrong / committed | DENY → SHIP wrong / committed | CONFIRM → HOLD wrong / committed | Review-only commits | Raw ECE |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Rules | 26/223 | 0/26 (0.0%) | 0/144 | — | 0/16 | 0/10 | 0 | — |
| fastText policy | 28/223 | 7/28 (25.0%) | 19/144 | 7/19 (36.8%) | 0/18 | 4/7 | 3 | 0.129 |
| MiniLM policy | 63/223 | 30/63 (47.6%) | 27/144 | 8/27 (29.6%) | 0/24 | 4/13 | 26 | 0.177 |

| Novel-test wrong / committed | English | Roman Urdu | Urdu script |
| --- | ---: | ---: | ---: |
| fastText policy | — | 4/9 (44.4%) | 3/10 (30.0%) |
| MiniLM policy | 6/18 (33.3%) | 1/1 (100.0%) | 1/8 (12.5%) |

FastText expanded to 19 novel replies and got seven wrong. MiniLM
expanded to 27 novel replies and got eight wrong. Each caused four false
holds in the confirmation family. The MiniLM policy also committed on
26 review-only cases across the novel and regression sets. No model
authorized dispatch in the application. Warm CPU p95 was
0.08 ms for fastText and 16.93 ms for MiniLM. Artifacts were
3.17 MB and 127.16 MB. Both fit the serving budgets and exceeded the
0.10 calibration ceiling. Wrong holdout IDs are emitted in
`test-results.json` by the evaluator.

Use the Round 7 dependencies and checkpoint. Run `tune` with
`--checkpoint`, then run `test` in the same work directory. The test
command refuses to overwrite an existing run.

```text
python scripts/experiments/rematch_reply_models.py tune --work-dir PATH_TO_RUN --checkpoint PATH_TO_ORIGINAL_MINILM
python scripts/experiments/rematch_reply_models.py test --work-dir PATH_TO_RUN
```

## Round 8 addendum · Synthetic address quality

The [44-address synthetic set](../data/address_quality.v1.jsonl) is
[frozen by SHA-256](../data/address_quality.v1.lock.json). The rules
matched clear-versus-flagged on **41/44 (93.18%)**, with 24 true flags,
17 true clears, two false flags, and one missed flag. The complete
reason set matched on 41/44. Errors included a two-edit city typo
and false missing-identifier findings for an alphabetic house number
and a building number. These labels are generated examples.

| Reason | True positives | False positives | False negatives |
| --- | ---: | ---: | ---: |
| Missing identifier | 14 | 2 | 0 |
| Too short | 6 | 0 | 0 |
| Landmark only | 8 | 0 | 0 |
| City mismatch | 6 | 0 | 0 |
| City misspelling | 5 | 0 | 1 |

[Shadow prepaid and courier results, address rollout and reproduction](DISPATCH_ADVICE.md)
