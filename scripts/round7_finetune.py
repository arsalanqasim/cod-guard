"""Fine-tune the last multilingual MiniLM encoder block and export an INT8 model."""
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from round7_models import LABELS


def train_minilm(rows, checkpoint, output):
    import torch
    from onnxruntime.quantization import QuantType, quantize_dynamic
    from torch import nn
    from transformers import AutoModel, AutoTokenizer

    torch.manual_seed(7)
    torch.set_num_threads(4)
    tokenizer = AutoTokenizer.from_pretrained(checkpoint, local_files_only=True)
    encoder = AutoModel.from_pretrained(checkpoint, local_files_only=True, attn_implementation="eager")
    encoder.requires_grad_(False)
    encoder.encoder.layer[-1].requires_grad_(True)

    class ReplyClassifier(nn.Module):
        def __init__(self):
            super().__init__()
            self.encoder = encoder
            self.head = nn.Linear(encoder.config.hidden_size, len(LABELS))

        def forward(self, input_ids, attention_mask):
            hidden = self.encoder(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state
            mask = attention_mask.unsqueeze(-1)
            pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1)
            return self.head(pooled)

    model = ReplyClassifier()
    optimizer = torch.optim.AdamW([
        {"params": encoder.encoder.layer[-1].parameters(), "lr": 3e-5},
        {"params": model.head.parameters(), "lr": 2e-3},
    ])
    model.train()
    for _ in range(6):
        for indices in torch.randperm(len(rows)).split(16):
            batch = [rows[int(index)] for index in indices]
            inputs = tokenizer([row["text"] for row in batch], padding=True, truncation=True,
                               max_length=64, return_tensors="pt")
            labels = torch.tensor([LABELS.index(row["label"]) for row in batch])
            optimizer.zero_grad()
            logits = model(inputs["input_ids"], inputs["attention_mask"])
            nn.functional.cross_entropy(logits, labels).backward()
            optimizer.step()

    output.mkdir(parents=True, exist_ok=True)
    model.eval()
    sample = tokenizer(["Send the whole order."], return_tensors="pt")
    with TemporaryDirectory(dir=output) as temp:
        raw = Path(temp) / "decision.onnx"
        torch.onnx.export(model, (sample["input_ids"], sample["attention_mask"]), str(raw),
                          input_names=["input_ids", "attention_mask"], output_names=["logits"],
                          dynamic_axes={"input_ids": {1: "tokens"}, "attention_mask": {1: "tokens"}},
                          opset_version=17, dynamo=False)
        quantize_dynamic(raw, output / "decision.int8.onnx", weight_type=QuantType.QInt8,
                         op_types_to_quantize=["MatMul", "Gather"])
    shutil.copyfile(checkpoint / "tokenizer.json", output / "tokenizer.json")
