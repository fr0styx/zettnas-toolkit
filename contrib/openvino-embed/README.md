# OpenVINO embedding server

A small server that speaks Ollama's embed API (`/api/embed`, `/api/embeddings`, `/api/tags`) and runs an
OpenVINO model, for embedding models Ollama can't run well, such as EmbeddingGemma 2 on an Intel Arc iGPU.
ZettNAS uses it through the AI config's `embedding_host`. Chat and other models stay on Ollama.

## Model

Export the whole sentence-transformers pipeline (pooling and projection included) in full precision:

```bash
python3 contrib/openvino-embed/export.py google/embeddinggemma-2 <dir>
```

This writes `<dir>/model` and `<dir>/tokenizer`.

## Run

```bash
docker build -t zettnas-eg2 contrib/openvino-embed
docker run -d --name zettnas-eg2 --restart unless-stopped --device /dev/dri -p 11435:11434 -v <dir>:/models:ro zettnas-eg2
```

Then re-embed the index onto it (AI settings, or `POST /api/ai/reindex` with
`{"embedding_model": "embeddinggemma-2-ov", "embedding_dim": 768, "embedding_host": "http://<host>:11435"}`).
Search keeps using the old vectors until every chunk is done.

## Notes

- EmbeddingGemma 2 scores clearly higher than EmbeddingGemma 1 on public retrieval benchmarks (SciFact),
  and batch 2 was the fastest setting on an Arc iGPU in testing (`BATCH` changes it).
- `PRECISION=f16` is faster but gives broken vectors (NaN) on Arc, with or without activation scaling.
- Texts in one batch are kept within 480 tokens of each other: EmbeddingGemma attends in 512-token
  windows, and padding a short text to a long one gives windows of only padding, which come out NaN.
- Searches (one or two texts) are served before the next batch of an indexing request, so a query
  waits at most one batch (about 0.3 s).
