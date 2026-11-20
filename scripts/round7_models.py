"""CPU model runners used by the Round 7 evaluation and local shadow tool."""
import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from scipy.special import softmax


LABELS = ("CONFIRM", "DENY", "UNCLEAR", "MODIFICATION")
HYPOTHESES = (
    "The buyer unconditionally confirms shipment of the entire order as placed.",
    "The buyer refuses or cancels the entire order with immediate effect.",
    "The buyer's intention is uncertain, conditional, hypothetical or time-bound.",
    "The buyer requests a change to part of the order or its details.",
)


def _fasttext_text(text):
    # Keep apostrophes and Unicode letters. Space punctuation consistently.
    cleaned = " ".join(re.findall(r"[^\W_]+(?:['’][^\W_]+)*|[^\w\s]", (text or "").casefold()))
    return cleaned.replace("__label__", "label") or "<empty>"


def train_fasttext(rows, destination, *, lr=0.3, epoch=45, word_ngrams=2, minn=2, maxn=4):
    import fasttext

    with TemporaryDirectory(dir=destination.parent) as temp:
        training = Path(temp) / "train.txt"
        training.write_text("".join(f"__label__{row['label']} {_fasttext_text(row['text'])}\n"
                                    for row in rows), encoding="utf-8")
        model = fasttext.train_supervised(str(training), lr=lr, epoch=epoch, dim=48,
                                         wordNgrams=word_ngrams, minn=minn, maxn=maxn, bucket=16000,
                                         thread=1, verbose=0)
        model.save_model(str(destination))


def fasttext_predictor(path):
    import fasttext

    model = fasttext.load_model(str(path))
    if set(model.labels) != {f"__label__{label}" for label in LABELS}:
        raise ValueError("The fastText artifact must use the four Round 7 labels")

    def predict(text):
        labels, values = model.predict(_fasttext_text(text), k=len(LABELS))
        raw = dict(zip(labels, values))
        probabilities = np.array([raw[f"__label__{label}"] for label in LABELS])
        return probabilities / probabilities.sum()

    return predict


def _tokenizer(path, max_length, *, padding=False):
    from tokenizers import Tokenizer

    tokenizer = Tokenizer.from_file(str(path))
    tokenizer.enable_truncation(max_length=max_length)
    if padding:
        pad = tokenizer.token_to_id("<pad>")
        if pad is None:
            pad = tokenizer.token_to_id("[PAD]")
        tokenizer.enable_padding(pad_id=pad, pad_token=tokenizer.id_to_token(pad))
    return tokenizer


def _session(path):
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    return ort.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"])


def _inputs(encodings):
    return {name: np.array([getattr(row, source) for row in encodings], dtype=np.int64)
            for name, source in (("input_ids", "ids"), ("attention_mask", "attention_mask"),
                                 ("token_type_ids", "type_ids"))}


def _run(session, inputs):
    return session.run(None, {item.name: inputs[item.name] for item in session.get_inputs()})


def minilm_predictor(folder):
    tokenizer = _tokenizer(folder / "tokenizer.json", 64)
    session = _session(folder / "decision.int8.onnx")

    def predict(text):
        logits, = _run(session, _inputs([tokenizer.encode(text or "")]))
        return softmax(logits[0].astype(float))

    return predict


def zero_shot_predictor(folder):
    tokenizer = _tokenizer(folder / "tokenizer.json", 96, padding=True)
    session = _session(folder / "onnx/model_int8.onnx")
    labels = json.loads((folder / "config.json").read_text(encoding="utf-8"))["label2id"]
    entailment = next(index for name, index in labels.items() if name.lower() == "entailment")

    def predict(text):
        batch = tokenizer.encode_batch([(text or "", hypothesis) for hypothesis in HYPOTHESES])
        logits, = _run(session, _inputs(batch))
        return softmax(logits[:, entailment].astype(float))

    return predict


def dm_predictor(folder):
    tokenizer = _tokenizer(folder / "tokenizer.json", 512)
    encoder = _session(folder / "onnx/encoder_model_int8.onnx")
    decoder = _session(folder / "onnx/decoder_model_int8.onnx")
    pad, end = (tokenizer.token_to_id(token) for token in ("<pad>", "</s>"))

    def predict(text, field):
        prompt = (f"Extract the buyer's final {field} from this shop chat. Answer with its exact "
                  f"value only. If missing, answer UNKNOWN.\nChat:\n{text}\nAnswer:")
        inputs = _inputs([tokenizer.encode(prompt)])
        hidden, = _run(encoder, inputs)
        tokens = [pad]
        for _ in range(48):
            results = _run(decoder, {
                "input_ids": np.array([tokens], dtype=np.int64),
                "encoder_hidden_states": hidden, "encoder_attention_mask": inputs["attention_mask"],
            })
            token = int(results[0][0, -1].argmax())
            if token == end:
                break
            tokens.append(token)
        return tokenizer.decode(tokens).strip()

    return predict
