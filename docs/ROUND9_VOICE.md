# Round 9 Urdu voice evaluation

Whisper small remains the offline default. The audited checkpoint is
Loudness.ai’s Urdu Sukhan ASR v1. Its CTranslate2 weights returned
HTTP 401 without approved access. The model card states CC BY-NC 4.0
and requires separate permission for commercial use. Its published
accuracy figures are outside this evaluation.
[Model card and access request](https://huggingface.co/Loudness-ai/urdu-sukhan-asr-v1)

## Measured comparison

| Set | Stock small WER | Stock intent | Public Urdu Tiny WER | Public Urdu Tiny intent |
| --- | ---: | ---: | ---: | ---: |
| [PK-REAL] FLEURS Urdu read speech | 134/427 (31.38%) | 12/12 expected abstentions | 204/427 (47.78%) | 12/12 expected abstentions |
| [PK-SYNTH] Short Urdu replies | 17/19 (89.47%) | 5/12 correct | 19/19 (100.00%) | 5/12 correct |

The public, Apache-2.0 Urdu Tiny checkpoint is a secondary comparator.
It was pinned at revision `ad901b65fb2a711bc0ed4c7a3409a15eeab86cc8`
and converted to CTranslate2 INT8. Stock small had lower WER and tied
intent accuracy on both sets. The Urdu Sukhan comparison remains
unmeasured. [Public Urdu Tiny checkpoint](https://huggingface.co/sharjeel103/whisper-tiny-urdu)

[PK-REAL] The FLEURS row uses the exact frozen Round 8 stock run.
All reference labels are UNCLEAR. [Round 8 evidence and clip hashes](VOICE_ACCURACY.md)

[PK-SYNTH] The short set has 12 one- or two-word Urdu prompts with
four confirmations, three denials and five unclear replies. Audio was
generated locally using the single-speaker MMS VITS checkpoint.
Both pipelines routed every clip to UNCLEAR, including all seven
confirmations or denials. The short set measures a synthetic accent and
recording condition. Buyer audio and commercial model fitness remain
unmeasured. [Versioned prompts](../data/urdu_short_replies.v1.json) ·
[Urdu MMS checkpoint](https://huggingface.co/facebook/mms-tts-urd-script_arabic)

All scoring uses offline CPU INT8 decoding, the current VAD and transcript
warning gates, the unchanged reply parser, and the Round 8 WER
normalization. An audio failure counts as an incorrect intent.

## Reproduce and add the audited checkpoint

Cache stock Whisper weights using `python scripts/prepare_voice.py`.
For generating fresh short fixtures, use the pinned [MMS revision](https://huggingface.co/facebook/mms-tts-urd-script_arabic/tree/4c4f53d52e4f0b40cb8e7f36dcef66a2a73619c5)
with Transformers and CPU PyTorch. Keep WAVs and licensed weights in a
private evaluation directory. The runner writes and verifies clip
hashes. Both models should score the same generated WAVs.

```text
python scripts/evaluate_round9_voice.py --tts-checkpoint PATH_TO_MMS --short PATH_TO_NEW_WAV_SET
python scripts/evaluate_round9_voice.py --short PATH_TO_WAV_SET --fleurs PATH_TO_FLEURS_TAR_GZ --output PATH_TO_STOCK_RESULT
python scripts/evaluate_round9_voice.py --short PATH_TO_WAV_SET --fleurs PATH_TO_FLEURS_TAR_GZ --checkpoint PATH_TO_APPROVED_CTRANSLATE2 --output PATH_TO_CANDIDATE_RESULT
```

The audited comparison and any selection decision require the approved
checkpoint. Commercial deployment also requires the corresponding rights.
