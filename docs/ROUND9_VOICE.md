# Round 9 Urdu voice evaluation

Loudness.ai's Urdu Sukhan ASR v1 CTranslate2 checkpoint was downloaded
with approved access at revision `f829afb90418c5cf29915f55761485b098a88142`.
All five checkpoint files matched the published sizes. The SHA-256 of
`model.bin` matched Hugging Face's download metadata
(`177bd667fafcb0af5f47e2556830c4026400d2342616e0ca00e532ca19aefc84`).
The checkpoint is licensed CC BY-NC 4.0 and was used here for offline,
noncommercial evaluation. [Model card](https://huggingface.co/Loudness-ai/urdu-sukhan-asr-v1)

## Measured comparison

| Set | Whisper Small WER | Urdu Sukhan WER | Public Urdu Tiny WER |
| --- | ---: | ---: | ---: |
| [PK-REAL] FLEURS Urdu read speech | 134/427 (31.38%) | 60/427 (14.05%) | 204/427 (47.78%) |
| [PK-SYNTH] Short Urdu replies | 17/19 (89.47%) | 13/19 (68.42%) | 19/19 (100.00%) |

[PK-REAL] The FLEURS comparison uses the 12 frozen WAVs from Round 8.
All three models returned the expected UNCLEAR on all 12 clips.
[Round 8 measurements and clip hashes](VOICE_ACCURACY.md)

[PK-SYNTH] The short set has four confirmations, three denials and five
unclear replies, all generated with the single-speaker MMS VITS
checkpoint. All three models returned UNCLEAR on all five ambiguous
replies. Across both sets, Urdu Sukhan and Whisper Small returned UNCLEAR
on all 17 clips where abstention was expected. Whisper Small and Public
Urdu Tiny also returned UNCLEAR on all seven explicit replies. Urdu
Sukhan correctly identified one of four confirmations and one of three
denials and returned UNCLEAR on the other five. That gave it 7/12 correct
intents, compared with 5/12 for each comparator.
[Versioned prompts](../data/urdu_short_replies.v1.json) ·
[Urdu MMS checkpoint](https://huggingface.co/facebook/mms-tts-urd-script_arabic)

The runner verified the input WAV hashes and used offline CPU INT8
decoding, the current VAD and transcript warning gates, the existing
reply parser, and the Round 8 WER normalization. An audio failure
counts as an incorrect intent. Urdu Sukhan decoded all 24 clips
successfully. The secondary Apache-2.0 Urdu Tiny checkpoint was pinned
at revision `ad901b65fb2a711bc0ed4c7a3409a15eeab86cc8` and converted to
CTranslate2 INT8. [Public Urdu Tiny checkpoint](https://huggingface.co/sharjeel103/whisper-tiny-urdu)

## Recommendation

Keep Whisper Small in the live pipeline and retain Urdu Sukhan for
non-commercial evaluation under CC BY-NC 4.0. Urdu Sukhan lowered FLEURS
WER by 17.33 percentage points and abstained on five of seven explicit
synthetic replies. The sample covers read speech and one synthetic voice.
An adoption decision requires evaluation on real buyer audio and separate
commercial rights.

## Reproduce

Cache stock Whisper weights with `python scripts/prepare_voice.py`.
Keep WAVs and licensed weights in a private evaluation directory.
If the frozen short-reply WAVs are unavailable, use the pinned
[MMS revision](https://huggingface.co/facebook/mms-tts-urd-script_arabic/tree/4c4f53d52e4f0b40cb8e7f36dcef66a2a73619c5)
with Transformers and CPU PyTorch to generate a new set, then use the
same WAVs for both runs.

```text
python scripts/experiments/evaluate_round9_voice.py --tts-checkpoint PATH_TO_MMS --short PATH_TO_NEW_WAV_SET
python scripts/experiments/evaluate_round9_voice.py --short PATH_TO_WAV_SET --fleurs PATH_TO_FLEURS_TAR_GZ --output PATH_TO_STOCK_RESULT
python scripts/experiments/evaluate_round9_voice.py --short PATH_TO_WAV_SET --fleurs PATH_TO_FLEURS_TAR_GZ --checkpoint PATH_TO_APPROVED_CTRANSLATE2 --output PATH_TO_CANDIDATE_RESULT
```
