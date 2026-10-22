# Document search and Ask Zetty

How ZettNAS indexes your files, searches them, and uses them in chat. Everything here
describes what the code does today; the numbers come from `tests/rag_eval`, which CI runs.

## What gets indexed

- Only folders you add under **AI → Watched folders**. Folders in *Excluded* are never read.
- Text-like files: Markdown, plain text, CSV, JSON, YAML, HTML, code, `.docx` and `.pdf`.
  Photos get colour and scene tags plus any text found in them.
- **Photo captions.** When a vision model is installed in Ollama (for example
  `gemma3:4b` or `qwen2.5vl:3b`), ZettNAS describes each photo in one sentence and copies
  any readable text (receipts, signs, screenshots). Both go into photo search. It works
  one photo at a time and only while the NAS is idle: load under half the CPU cores, CPU
  under 75 °C, inside the learning schedule if you set one, and never on a sleeping disk.
  Captions are stored by file content, so re-indexing or moving a photo keeps them.
  Scanned PDFs (pages that are only images) are read the same way, up to 8 pages
  each, so their text becomes searchable.
  Turn it off under **AI → Describe photos and read their text**; pin a model with
  `vision_model` in the AI config.
- Each file is split into sections of about 3,500 characters, and those into chunks of
  about 950 characters with 80 characters of overlap. Each chunk is stored with its file
  title in front (`title: … | text: …`).
- The index lives in `rag_index.db` in the data folder, normally on the SSD cache. Search
  reads only this database, not your array disks.
- With **Standby-safe learning** on, files on a sleeping disk are queued and indexed when
  the disk spins up, instead of waking it. ZettNAS finds the real disks under a folder on
  Unraid, ZFS, Btrfs, mdadm, LVM/LUKS and plain partitions, checks each with the
  non-waking `smartctl -n standby`, and ignores SSDs. Network and cloud mounts are never
  treated as sleeping. If it can't tell which disk holds a folder, it assumes the disk may
  be asleep and waits; set `ZETTNAS_STANDBY_UNKNOWN=allow` to index such folders anyway.

## Vectors

Two kinds, and a file never mixes them:

| | Built-in lexical | Neural (Ollama) |
|---|---|---|
| Model | `zett_lexical_384d`, a hashed word/character vector computed in ZettNAS | an embedding model you install, e.g. `embeddinggemma` or `nomic-embed-text` |
| Needs | nothing | Ollama running and the model installed |
| Good at | exact words, names, numbers | paraphrases and synonyms |
| Weak at | wording that doesn't appear in the file | short exact codes |

**EmbeddingGemma** is Google's 300M-parameter text embedding model. It reads at most
2,048 tokens, so ZettNAS sends at most 6,000 characters per chunk (2,500 for mostly
Chinese/Japanese text). Its vectors can be shortened to 768, 512, 256 or 128 numbers
(Matryoshka); ZettNAS re-normalises them after shortening.

Chunks are embedded in batches of 32. If the model fails partway through a file, the
whole file falls back to lexical vectors and is labelled that way, and the embedder is
skipped for 60 seconds. Re-embed from **AI settings** once the model is back.

## Optional reranker

A cross-encoder reranker (for example `bge-reranker-v2-m3`) reads the query together
with each of the top results and orders them better than vector similarity alone.
Ollama can't serve one, but OpenVINO Model Server, Infinity and Hugging Face TEI can.
Set `rerank_endpoint` in the AI config to its rerank URL (OVMS:
`http://zettnas-ovms:8000/v3/rerank`, TEI/Infinity: `http://host:port/rerank`) and, if
the server needs it, `rerank_model`. The top `rerank_top_n` results (default 30) are
re-ordered; if the reranker is down, search keeps its usual order.

## Measured retrieval quality

`tests/rag_eval` has 40 home-NAS files in English, German, Chinese, French and Spanish
and 200 hand-written questions, 5 per file. They go through the real indexer and search.
Built-in lexical vectors, today:

| Language | Right file first | Right file in top 5 | MRR@10 |
|---|---|---|---|
| English | 0.80 | 0.80 | 0.80 |
| German | 0.70 | 0.82 | 0.75 |
| French | 0.65 | 0.85 | 0.73 |
| Spanish | 0.75 | 0.90 | 0.79 |
| Chinese | 0.85 | 0.85 | 0.85 |
| **All** | **0.75** | **0.84** | **0.79** |

Chinese, Japanese and Korean text is split into overlapping character pairs, so words
match without spaces between them (Chinese was 0.03 before this).
CI fails if any of these numbers drops by more than 0.01. To measure a
neural model on your NAS:

```bash
python -m tests.rag_eval.run_eval --model embeddinggemma
```

## Who sees what

Search results and chat answers only include files from shares the signed-in user can
open. In chat, the AI only gets the tools the user's role allows (the same permissions as
the matching pages), and anything that changes the system waits for you to click
**Confirm**. Text from files and web pages is passed to the model as data, marked so the
model is told not to follow instructions inside it.

## Forgetting and retention

- **Forget** on a watched folder deletes everything learned from it (files, chunks,
  vectors, photo data, folder summaries) and adds it to the excluded folders.
- **Delete chats not used for…** removes unpinned conversations after 7, 30, 90 or 365 days.
- **Flush index** deletes the whole index.
- The index and conversations are not encrypted at rest; protect the data folder like
  any other private data.

## Chat models

Ask Zetty uses a chat model served by Ollama or OpenVINO Model Server on this NAS. The
built-in catalog lists mainstream models with their licences; **Install** downloads one
into Ollama and checks it's there. If the selected model isn't installed, the answer says
so instead of using another model. Without a model, Ask Zetty can still show system
status, search your files and do calculations, and it says that no model answered.
