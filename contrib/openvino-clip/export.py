"""Exports SigLIP 2 (its image and text towers) to OpenVINO for contrib/openvino-clip.

    pip install torch transformers openvino nncf pillow sentencepiece
    python export.py google/siglip2-base-patch16-224 /path/to/model [--fp32]

Writes <out>/vision.xml, <out>/text.xml (int8 weights unless --fp32), <out>/tokenizer and
<out>/info.json (image size, normalisation, text length), and checks that OpenVINO's vectors
match PyTorch's.
"""

import json
import os
import sys

import numpy as np
import openvino as ov
import torch
from transformers import AutoImageProcessor, AutoModel, AutoTokenizer

args = [a for a in sys.argv[1:] if not a.startswith("--")]
name, out = args[0], args[1]
int8 = "--fp32" not in sys.argv
MAX_LEN = 64  # SigLIP's text length: always padded to it

os.makedirs(out, exist_ok=True)
model = AutoModel.from_pretrained(name, torch_dtype=torch.float32).eval()
tok = AutoTokenizer.from_pretrained(name)
proc = AutoImageProcessor.from_pretrained(name)
size = int(model.config.vision_config.image_size)


class Vision(torch.nn.Module):
    def __init__(self, m):
        super().__init__()
        self.m = m

    def forward(self, pixel_values):
        return self.m.get_image_features(pixel_values=pixel_values)


class Text(torch.nn.Module):
    def __init__(self, m):
        super().__init__()
        self.m = m

    def forward(self, input_ids):
        return self.m.get_text_features(input_ids=input_ids)


pix = torch.randn(2, 3, size, size)
ids = tok(
    ["a photo of a dog", "ein foto von einem hund"],
    padding="max_length",
    max_length=MAX_LEN,
    truncation=True,
    return_tensors="pt",
)["input_ids"]
with torch.no_grad():
    vision = ov.convert_model(
        Vision(model),
        example_input={"pixel_values": pix},
        input=[("pixel_values", ov.PartialShape([-1, 3, size, size]), ov.Type.f32)],
    )
    text = ov.convert_model(
        Text(model),
        example_input={"input_ids": ids},
        input=[("input_ids", ov.PartialShape([-1, MAX_LEN]), ov.Type.i64)],
    )
    want_v = model.get_image_features(pixel_values=pix).numpy()
    want_t = model.get_text_features(input_ids=ids).numpy()
if int8:
    import nncf

    vision = nncf.compress_weights(vision, mode=nncf.CompressWeightsMode.INT8_ASYM)
    text = nncf.compress_weights(text, mode=nncf.CompressWeightsMode.INT8_ASYM)
ov.save_model(vision, f"{out}/vision.xml", compress_to_fp16=False)
ov.save_model(text, f"{out}/text.xml", compress_to_fp16=False)
tok.save_pretrained(f"{out}/tokenizer")
info = {
    "model": name,
    "image_size": size,
    "image_mean": list(proc.image_mean),
    "image_std": list(proc.image_std),
    "max_length": MAX_LEN,
    "lowercase": True,  # SigLIP 2 was trained on lower-cased text
    "weights": "int8" if int8 else "fp32",
}
with open(f"{out}/info.json", "w") as f:
    json.dump(info, f, indent=1)

core = ov.Core()


def cos(a, b):
    a = a / np.linalg.norm(a, axis=1, keepdims=True)
    b = b / np.linalg.norm(b, axis=1, keepdims=True)
    return (a * b).sum(axis=1)


got_v = next(iter(core.compile_model(f"{out}/vision.xml", "CPU")({"pixel_values": pix.numpy()}).values()))
got_t = next(iter(core.compile_model(f"{out}/text.xml", "CPU")({"input_ids": ids.numpy()}).values()))
print("vision match:", cos(got_v, want_v).round(4), "text match:", cos(got_t, want_t).round(4), "dim:", got_v.shape[1])
print(f"exported {name} to {out} ({info['weights']} weights)")
