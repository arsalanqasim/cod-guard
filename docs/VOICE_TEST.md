# Real Urdu audio smoke test — 19 November 2026

Command: `python scripts/test_voice.py` (exit 0), using the bundled, attributed
Google FLEURS Urdu/Pakistan recording, test row 0, record ID 1806. This is general
read speech, not a COD customer note. See `data/voice_samples/ATTRIBUTION.md`.

Backend: faster-whisper 1.2.1, multilingual `small`, CPU / int8; cached weights,
offline inference; PyAV 16.1.0. The transcript below is the actual output,
including its errors. It has not been replaced with the dataset reference text.

## Transcript (verbatim)

```text
ان کے دور میں خفیب تلو اس ایزا مسئلہ نہیں تھا جیسا کہ وہ آج ہے ان کی سقونت ایسے شہروں یا حوزات میں ہے جہاں تک بہسانی پہنچا جا سکتا ہے بہنسبتین مقامات کے جو مادرن زمانے میں تعمیر کی گئے گئے
```

Intent: `UNCLEAR`. This sample does not confirm or deny a COD order. It is a
pipeline smoke test, not an Urdu ASR accuracy benchmark or a customer-study result.

## Failure found and repaired

The initial install resolved PyAV 19.0.2. The real transcription and a minimal
decoder regression both failed with:

```text
TypeError: open() got an unexpected keyword argument 'metadata_errors'
```

faster-whisper 1.2.1 passes that argument to PyAV. Pinning PyAV 16.1.0 repaired
the decoder and the same audio then transcribed successfully. The regression
decodes an actual WAV without downloading model weights, so CI catches this
dependency breakage cheaply. Other voice tests cover missing/oversized input,
verbatim output, and explicit model-unavailable errors.

The dashboard and API preview transcripts before applying them. Silence or
low-confidence output requests another reply; it cannot be applied by the voice
action. The parser is conservative offline rules, not a claimed multilingual LLM.
