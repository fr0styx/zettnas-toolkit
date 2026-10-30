# Document search and Ask Zetty

How ZettNAS indexes your files, searches them, and uses them in chat. Everything here
describes what the code does today; the numbers come from `tests/rag_eval`, which CI runs.

## What gets indexed

- Only folders you add under **AI → Watched folders**. Folders in *Excluded* are never read.
- Text-like files: Markdown, plain text, CSV, JSON, YAML, HTML, code, `.pdf`, Word (`.docx`),
  Excel (`.xlsx`), PowerPoint (`.pptx`, with speaker notes), OpenDocument (`.odt`, `.ods`,
  `.odp`), e-books (`.epub`), e-mail (`.eml`, `.mbox`: headers, text and attachment names)
  and `.rtf`. Each part is capped at 64 MiB uncompressed, so a small file can't expand into
  gigabytes.
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
- Each file is split into sections of about 875 tokens, and those into chunks of at most
  about 240 tokens, with a little overlap (up to 20 tokens, two sentences at most). Tokens
  are counted by script: one per Chinese/Japanese/Korean character, about 2.5 characters
  for Cyrillic and Greek, 3.2 for accented Latin text, 4 for plain English. Lines longer than
  a chunk are cut at sentence ends, and a sentence longer than a chunk at spaces, so a PDF
  extracted as one long line becomes normal chunks. Each chunk is stored with its file title
  in front (`title: … | text: …`).
- When the way files are chunked changes (index version 4 brought the above), files that
  didn't change are re-made overnight only, between 01:00 and 06:00, while nobody is chatting,
  and only on disks that are awake; a file that changed is re-indexed right away.
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

## How results are ranked

Each embedding model has a profile (`SIMILARITY_PROFILES` in `rag_engine.py`):

- **Lexical vectors** blend vector, keyword (BM25) and title matches, and drop weak
  coincidences: a 3+ word query that matches at most one word of the text, or a document
  without a title match when the query reads like a photo search.
- **Neural vectors** rank by vector similarity with a small keyword tie-break, without
  those word rules. A neural model matches across languages and wording, so requiring
  shared words threw away good matches.

Search asks the vector index for more neighbours until enough of them are files the
person may read in the chosen folder, so access and folder filters apply while searching
rather than to a global top 60. With a vector index there is no "newest files first"
window.

## Measured retrieval quality

`tests/rag_eval` has 40 home-NAS files in English, German, Chinese, French and Spanish
and 200 hand-written questions, 5 per file. They go through the real indexer and search.
Today's scores, per language and per kind of question, are on [Search quality](SEARCH_QUALITY.md),
generated from `tests/rag_eval/baseline*.json`.

Chinese, Japanese and Korean text is split into overlapping character pairs, so words
match without spaces between them (Chinese was 0.03 before this).
CI fails if any of these numbers drops by more than 0.01. To measure a
neural model on your NAS:

```bash
python -m tests.rag_eval.run_eval --model embeddinggemma --set all
```

Two more sets measure what lexical vectors can't do: 50 **cross-language** questions
(asked in one language about a file in another) and 40 **paraphrases** that share few
words with the file. Lexical vectors score low on these by nature; the nightly run measures
them with EmbeddingGemma on GitHub's runners, with 2,000 extra distractor files (scores on
[Search quality](SEARCH_QUALITY.md)). Plain reciprocal-rank fusion and the title and word boosts
were measured too and scored lower for neural models, so they are not used.

### How a neural search ranks (AI-41)

Measured against DigUp, which uses the same EmbeddingGemma 2, with the eval sets and 2,000
distractor files:

- **A chunk is embedded as `title: <document title > section> | text: <its own text>`**.
  The chunk text kept for keyword search and answers starts with a `[Folder: .. | Doc: ..]`
  breadcrumb; embedding that too made every chunk look alike. An index embedded the old way is
  re-embedded once, at night, from the index on the SSD (no disk reads), and search keeps the old
  vectors until the new ones are all in.
- **Questions get the search prompt.** Only text shaped like code (a definition, a call,
  operators, `SELECT * FROM`, a command line or a file name) gets the code prompt; "where did
  we stay" used to.
- **Meaning first, then the query's words.** A file's score is its best chunk's similarity
  plus `2 x spread x coverage^1.5`, where coverage is the share of the query's meaningful words
  (stop words of all five languages left out) in the chunk and its title, and spread is how
  much this query's similarities vary across the index: DigUp's z-score plus keyword coverage,
  in cosine units. The late-interaction bonuses used with lexical vectors are not applied.
- **Speed.** Searches share one warm read connection whose page cache holds the vector index
  (the index is encrypted, so a cold connection decrypted every page again), and the
  full-text index ranks its matches on its own before they are kept to the folder and to what
  the person may read.

**Nightly.** `.github/workflows/ai-eval-nightly.yml` runs all sets with EmbeddingGemma
served by Ollama and 2,000 distractors, and answers the 97 questions in `qa.json` with a
small chat model. An answer counts as right when it contains the fact
(`answer_any`); the report also says how often the right file was cited and how often a
model answered at all. Results are kept as workflow artifacts and compared with
`tests/rag_eval/baseline_nightly*.json`.

Asking for the answer first, in the question's language, without a stock "could not find"
sentence to copy, raised the share of right answers clearly with small models; most remaining
misses are a small model misreading a number.

### Long, Office and scanned documents (AI-16)

A third set asks about files people actually keep: a 48-section house handbook, a 12-page
works agreement (PDF) and a 30-article building regulation (Word), where the fact asked
for sits deep inside; Excel, PowerPoint (with speaker notes), OpenDocument, RTF and email
files, one of them in Chinese; and **scanned** PDFs and a photo of a receipt, whose text
only the vision model can read. Five **multi-hop** questions need two files (was the boiler
repair within the heating budget? the invoice is a scan, the budget a spreadsheet). The
files are generated by `tests/rag_eval/documents.py`, the same bytes every run, so every
fact is written down there.

Per commit, scanned pages go through the real vision queue with a stand-in that returns
each page's known text: everything from the scan to the search result is checked except the
model itself. The scores by kind are on [Search quality](SEARCH_QUALITY.md).

Multi-hop is the weak spot: the second file is often in another language or shares few
words with the question, which neural vectors handle. CI fails if any of these drops. With
the vision model and a neural embedder:

```bash
python -m tests.rag_eval.run_eval --set documents --model embeddinggemma \
    --host http://127.0.0.1:11434 --ocr vision --answers qwen3:4b
```

A multi-hop answer counts as right only when it holds every fact it needs (`answer_all`),
and its sources count only when both files are cited.

### Held-out questions

One query or question in five is held out, fixed by a hash of its id, so adding or
reordering questions moves nobody between the halves. Ranking and prompts are tuned on the
rest: `--misses` lists only those misses (`--show-heldout` shows all, for a release review),
and every result reports both halves (`by_split`). A change that helps the tuning half but
not the held-out half has been fitted to the questions, not improved. CI keeps both from
getting worse; [Search quality](SEARCH_QUALITY.md) shows both halves.

## How answers are checked

**Grounding** is scored on the model's final answer, sentence by sentence. A sentence
is backed by a source when every number in it appears in that source and the rest of it
matches the source: by shared words, or by meaning when a neural embedder is set, so an
English answer about a German file can count. The chat shows "N of M sentences backed by
the sources" and lists the others under **Not found in the sources**.

**Routing.** Hardware, Docker, network and similar questions run their tool; everything
else searches your files, in any language. Words match as whole words ("ram" is not in
"program"), and "temperature" counts as a hardware question only next to a hardware word.
If nothing matches, the model answers without system status filling the gap. Tool
definitions go to the model only when the router found nothing, which keeps prompts
short. The context window is fixed at 8,192 tokens (`ZETTNAS_AI_NUM_CTX` changes it):
Ollama reloads the model whenever it changes, so the prompt is fitted to the window,
oldest history first, instead.

**Follow-ups** such as "and the warranty?" search with the previous question's words
added, so the search knows the topic.

**What leaves the NAS.** A web search (only when you allow web access) carries the
question without addresses, e-mail addresses, file paths, long numbers or keys, and a
search the model asks for is refused when it repeats text from your files. When an
answer contains a Compose file with risky settings (privileged mode, the Docker socket,
host networking, system folders, raw disks, default passwords) it ends with a note
listing them.


**How much of your files a question uses (AI-7).** At most about 2,000 tokens of passages go
into the prompt, counted as the model sees them (with each file's title, path and section).
They are spent best source first: a document keeps its whole section when it fits, else the
passage that matched, and lower-ranked documents get what is left. Small local models answer
better from less, better-chosen text, and the answer starts sooner. On the eval files the
passages stay under this (at most about 1,850 tokens), so it matters for long documents with
large sections; `tests/test_ai7_evidence_budget.py` checks it on those.

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
- The index and the conversations are encrypted at rest with the install's data key
  (`ZETTNAS_DATA_KEY`); keep that key and the data folder private, and back the key up:
  without it the index has to be rebuilt and old conversations can't be read.

## Chat models

Ask Zetty uses a chat model served by Ollama or OpenVINO Model Server on this NAS. The
built-in catalog lists mainstream models with their licences; **Install** downloads one
into Ollama and checks it's there. If the selected model isn't installed, the answer says
so instead of using another model. Without a model, Ask Zetty can still show system
status, search your files and do calculations, and it says that no model answered.
