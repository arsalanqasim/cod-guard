# Urdu voice accuracy

On **12 held-out Google FLEURS Urdu (Pakistan) read-speech clips**, the local
Whisper small pipeline made **134 word edits across 427 reference words (31.38% WER)**.
Whisper followed by the deployed reply rules returned the expected
`UNCLEAR` on **12/12** clips. Every reference is general speech and
has the same intent. This measures abstention on the sampled read speech.
Buyer confirmations, denials and in-domain COD audio remain unmeasured.

## Selection and method

The [frozen reference manifest](../data/urdu_voice_test.v1.json) records the
official test filenames, reference transcripts, expected parser labels and
original WAV hashes. Selection took the first 12 distinct sentence IDs in
SHA-256 order of filename, excluding the existing bundled sentence ID
1806. Manifest SHA-256 with LF line endings is
`4e11458a613731931dffcced95fd7c9f76ea7e4c22476abc7f1dd110efd2b744`.
The sample comes from FLEURS revision `4683b04`, configuration `ur_pk`,
split `test`, under CC BY 4.0. The spoken audio came from the original WAV
members. [Google FLEURS](https://huggingface.co/datasets/google/fleurs) ·
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)

The production path used cached Whisper small, CPU INT8, Urdu decoding and
VAD. WER uses word-level Levenshtein distance after Unicode normalization,
Arabic/Persian yeh and kaf normalization, and removal of punctuation and
combining marks. The denominator is the sum of reference words. An audio
failure counts against intent accuracy. An ASR warning routes the clip to
UNCLEAR, matching the serving path. Timings include the initial cached
model load on the first clip.

## Per-clip errors

All 12 clips had transcription errors. The table lists every clip and
its word-edit count. The observed transcripts are in the
[measurement file](../data/urdu_voice_measurements.v1.json).

| FLEURS ID | Reference words | Word edits | Expected intent | Observed intent | Warning | CPU seconds |
| --- | ---: | ---: | --- | --- | --- | ---: |
| 2009 | 35 | 9 | UNCLEAR | UNCLEAR | — | 13.53 |
| 1847 | 36 | 17 | UNCLEAR | UNCLEAR | — | 9.66 |
| 1932 | 76 | 19 | UNCLEAR | UNCLEAR | — | 19.05 |
| 1711 | 52 | 12 | UNCLEAR | UNCLEAR | — | 10.13 |
| 1769 | 31 | 10 | UNCLEAR | UNCLEAR | — | 9.20 |
| 1768 | 24 | 10 | UNCLEAR | UNCLEAR | — | 7.98 |
| 1829 | 31 | 10 | UNCLEAR | UNCLEAR | — | 8.75 |
| 1869 | 49 | 17 | UNCLEAR | UNCLEAR | — | 10.61 |
| 1817 | 17 | 6 | UNCLEAR | UNCLEAR | — | 6.49 |
| 1721 | 22 | 8 | UNCLEAR | UNCLEAR | — | 7.05 |
| 1705 | 21 | 8 | UNCLEAR | UNCLEAR | — | 9.43 |
| 1954 | 33 | 8 | UNCLEAR | UNCLEAR | — | 10.78 |

## Reproduce

Cache the voice weights with `python scripts/prepare_voice.py`. Fetch the
[official test archive](https://huggingface.co/datasets/google/fleurs/resolve/4683b04/data/ur_pk/audio/test.tar.gz)
and run with the checked-in manifest.

```text
python scripts/experiments/evaluate_urdu_voice.py PATH_TO_TEST_TAR_GZ --output voice-results.json
```
