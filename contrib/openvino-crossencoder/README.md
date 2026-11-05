# OpenVINO cross-encoder server (reranker)

A cross-encoder reads the question together with each text, which orders search results better
than vectors alone. ZettNAS uses it as its **reranker** (`bge-reranker-v2-m3`, Apache-2.0, 100+
languages; AI config `rerank_endpoint`): it re-orders the top search results, and before Ask Zetty
answers it tells the model when none of the found documents looks like an answer (docs/RAG.md).

The server can also run an NLI model (`/nli`), for experiments; ZettNAS doesn't use it.

## Models

ONNX exports from Hugging Face; OpenVINO reads them directly, nothing to convert:

```bash
pip install huggingface_hub
python3 -c "from huggingface_hub import snapshot_download as get; get('onnx-community/bge-reranker-v2-m3-ONNX', local_dir='<dir>/rerank', allow_patterns=['onnx/model.onnx*', '*.json'])"
```

About 2.3 GB. `onnx/model_int8.onnx` (0.6 GB) runs on CPU instead (`DEVICE=CPU`, `RERANK_FILE=onnx/model_int8.onnx`).

## Run

On the app's Docker network with no published port:

```bash
docker build -t zettnas-xenc contrib/openvino-crossencoder
docker run -d --name zettnas-xenc --restart unless-stopped --device /dev/dri \
  --network <the app's network> -e DEVICE=GPU -e PRECISION=f16 \
  -e RERANK_DIR=/models/rerank \
  -v <dir>:/models:ro zettnas-xenc
```

Then in AI settings, Reranker: `http://zettnas-xenc:8000/v3/rerank`.

## API

- `POST /v3/rerank` (or `/rerank`): `{"query", "documents": [...]}` →
  `{"results": [{"index", "relevance_score"}]}`, best first, scores 0–1.
- `POST /nli` (only with `NLI_DIR`): `{"pairs": [[premise, hypothesis], ...]}` →
  `{"results": [{"entailment", "neutral", "contradiction"}]}`, probabilities.
- `GET /health`.

Settings: `RERANK_DIR`, `RERANK_FILE` (onnx/model.onnx), `NLI_DIR`, `NLI_FILE`, `DEVICE` (CPU, GPU),
`PRECISION` (f32, f16), `MAX_TOKENS` (512), `BATCH` (8), `RERANK_STATIC` / `NLI_STATIC` (a fixed token
length, for exports that compile only with fixed shapes),
`PORT` (8000). A model whose folder isn't set is left out.
