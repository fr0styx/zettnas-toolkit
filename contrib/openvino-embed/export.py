"""Exports a sentence-transformers embedding model (transformer, pooling, projection) to OpenVINO.

    pip install sentence-transformers openvino nncf
    python export.py google/embeddinggemma-2 /path/to/models [--fp32]

Writes <out>/model/model.{xml,bin} and <out>/tokenizer. The weights are int8 (NNCF INT8_ASYM:
about a quarter of the size and faster on an iGPU, with the math still in full precision);
--fp32 keeps them in full precision.
"""

import sys

import openvino as ov
import torch
from sentence_transformers import SentenceTransformer

args = [a for a in sys.argv[1:] if not a.startswith("--")]
name, out = args[0], args[1]
int8 = "--fp32" not in sys.argv
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
if int8:
    import nncf

    model = nncf.compress_weights(model, mode=nncf.CompressWeightsMode.INT8_ASYM)
ov.save_model(model, f"{out}/model/model.xml", compress_to_fp16=False)
st.tokenizer.save_pretrained(f"{out}/tokenizer")
print(f"exported {name} to {out} ({'int8' if int8 else 'fp32'} weights)")
