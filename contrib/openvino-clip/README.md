# OpenVINO image-text server (SigLIP 2)

Photo search by meaning without Immich: ZettNAS sends each photo's stored thumbnail here and gets
a vector back, and does the same for a search question; photos close to the question are found
even when no caption or file name says what they show. SigLIP 2 learned many languages, so
"Sonnenuntergang am Meer" finds the same photos as "sunset at the sea".

## Model

```bash
pip install torch transformers openvino nncf pillow sentencepiece
python3 contrib/openvino-clip/export.py google/siglip2-base-patch16-224 <dir>
```

This writes `<dir>/vision.xml`, `<dir>/text.xml`, `<dir>/tokenizer` and `<dir>/info.json`, with int8
weights (`--fp32` keeps full precision), and checks OpenVINO's vectors against PyTorch's
(0.9997 cosine in testing). The model is Apache-2.0 and about 400 MB.

## Run

On the app's Docker network with no published port; the token is optional:

```bash
docker build -t zettnas-clip contrib/openvino-clip
docker run -d --name zettnas-clip --restart unless-stopped --device /dev/dri \
  --network <the app's network> -e TOKEN=<a long random string> -v <dir>:/models:ro zettnas-clip
```

Give ZettNAS the same value as `PHOTO_VECTOR_TOKEN`, and set the address in AI settings,
"Photo search by meaning": `http://zettnas-clip:11436`. Vectors are then made in the background
while the machine is idle; AI settings shows how many photos have one.

## API

`POST /v1/embeddings` with `{"model": "siglip2", "input": [...]}`, where each input is a text or
`{"image": "<base64 JPEG, PNG or WebP>"}`; the answer has one unit vector per input, in order.
Settings: `MODEL_DIR`, `DEVICE` (GPU, CPU), `BATCH` (8), `PORT` (11436), `TOKEN`.
