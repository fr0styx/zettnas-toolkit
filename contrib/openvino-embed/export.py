"""Exports a sentence-transformers embedding model (transformer, pooling, projection) to OpenVINO.

    pip install sentence-transformers openvino
    python export.py google/embeddinggemma-2 /path/to/models

Writes <out>/model/model.{xml,bin} (full precision) and <out>/tokenizer.
"""

import sys

import openvino as ov
import torch
from sentence_transformers import SentenceTransformer

name, out = sys.argv[1], sys.argv[2]
st = SentenceTransformer(name, device="cpu", model_kwargs={"torch_dtype": torch.float32})


class Pipeline(torch.nn.Module):
    def __init__(self, model):
        super().__init__()
        self.model = model

    def forward(self, input_ids, attention_mask):
        return self.model({"input_ids": input_ids, "attention_mask": attention_mask})["sentence_embedding"]


example = st.tokenize(["task: search result | query: hello world", "title: none | text: a longer example document"])
with torch.no_grad():
    model = ov.convert_model(
        Pipeline(st).eval(),
        example_input={"input_ids": example["input_ids"], "attention_mask": example["attention_mask"]},
        input=[
            ("input_ids", ov.PartialShape([-1, -1]), ov.Type.i64),
            ("attention_mask", ov.PartialShape([-1, -1]), ov.Type.i64),
        ],
    )
ov.save_model(model, f"{out}/model/model.xml", compress_to_fp16=False)
st.tokenizer.save_pretrained(f"{out}/tokenizer")
print(f"exported {name} to {out}")
