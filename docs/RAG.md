# Document search and Ask Zetty

How ZettNAS indexes your files, searches them, and uses them in chat. Everything here
describes what the code does today; the numbers come from `tests/rag_eval`, which CI runs.

## What gets indexed

- Only folders you add under **AI → Watched folders**. Folders in *Excluded* are never read.
- Text-like files: Markdown, plain text, CSV, JSON, YAML, HTML, code, `.docx` and `.pdf`.
  Photos get colour and scene tags plus any text found in them.
- Each file is split into sections of about 3,500 characters, and those into chunks of
  about 950 characters with 80 characters of overlap. Each chunk is stored with its file
  title in front (`title: … | text: …`).
- The index lives in `rag_index.db` in the data folder, normally on the SSD cache. Search
  reads only this database, not your array disks.
- With **Standby-safe learning** on, files on a sleeping disk are queued and indexed when
  the disk spins up, instead of waking it.

## Vectors

Two kinds, and a file never mixes them:

| | Built-in lexical | Neural (Ollama) |
|---|---|---|
| Model | `zett_lexical_384d`, a hashed word/character vector computed in ZettNAS | an embedding model you install, e.g. `embeddinggemma` or `nomic-embed-text` |
| Needs | nothing | Ollama running and the model installed |
| Good at | exact words, names, numbers | paraphrases and synonyms |
| Weak at | wording that doesn't appear in the file; Chinese and Japanese (no word splitting yet) | short exact codes |

**EmbeddingGemma** is Google's 300M-parameter text embedding model. It reads at most
2,048 tokens, so ZettNAS sends at most 6,000 characters per chunk (2,500 for mostly
Chinese/Japanese text). Its vectors can be shortened to 768, 512, 256 or 128 numbers
(Matryoshka); ZettNAS re-normalises them after shortening.

Chunks are embedded in batches of 32. If the model fails partway through a file, the
whole file falls back to lexical vectors and is labelled that way, and the embedder is
skipped for 60 seconds. Re-embed from **AI settings** once the model is back.

## Measured retrieval quality

`tests/rag_eval` has 40 home-NAS files in English, German, Chinese, French and Spanish
and 200 hand-written questions, 5 per file. They go through the real indexer and search.
Built-in lexical vectors, today:

| Language | Right file first | Right file in top 5 | MRR@10 |
|---|---|---|---|
| English | 0.80 | 0.80 | 0.80 |
| German | 0.65 | 0.73 | 0.68 |
| French | 0.60 | 0.85 | 0.71 |
| Spanish | 0.75 | 0.90 | 0.80 |
| Chinese | 0.03 | 0.03 | 0.03 |
| **All** | **0.57** | **0.66** | **0.60** |

Chinese fails because the lexical tokeniser doesn't split Chinese text into words; that
is planned work. CI fails if any of these numbers drops by more than 0.01. To measure a
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
