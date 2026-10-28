# AI for apps

Other apps on your network can use the chat model and the embedder this server already runs,
through one OpenAI-compatible address:

```
http://<your server>:8082/api/v1/ai/openai
```

| Path | What it does |
|---|---|
| `GET /models` | `zettnas-chat` and `zettnas-embed` |
| `POST /chat/completions` | a reply from the chat model; `"stream": true` streams it |
| `POST /embeddings` | vectors from the embedder (up to 64 texts at a time) |

Whatever model name an app sends, the model set in AI settings answers, so an app's settings
don't change when you switch models. When the chat server can't be reached, the Ollama fallback
model (if one is set) answers instead.

## Keys

Each app gets its own key: **Mission Control → AI → Configuration → AI for apps**, pick the
app and create a key (administrators only). The key is shown once, together with the settings to
paste into that app. A key can use these three paths and nothing else, and its owner's AI switch
in AI settings still applies. Revoke a key there to cut an app off.

## Apps

- **Paperless-ngx**: environment variables `PAPERLESS_AI_ENABLED=true`,
  `PAPERLESS_AI_LLM_BACKEND=openai-like`, `PAPERLESS_AI_LLM_ENDPOINT` (the address),
  `PAPERLESS_AI_LLM_API_KEY` (the key), `PAPERLESS_AI_LLM_MODEL=zettnas-chat`,
  `PAPERLESS_AI_LLM_EMBEDDING_BACKEND=openai-like`, `PAPERLESS_AI_LLM_EMBEDDING_MODEL=zettnas-embed`.
- **Open WebUI**: `OPENAI_API_BASE_URL` (the address) and `OPENAI_API_KEY` (the key), or Admin
  settings → Connections.
- **Home Assistant**: its built-in OpenAI integration can't change its address. Use an
  OpenAI-compatible conversation integration (for example from HACS) with the address, the key
  and the model `zettnas-chat`.

## Fair use of the GPU

Requests from apps take their turn like a chat reply: they go before searches being embedded and
before indexing. Each request is logged in the AI request log with the key owner's name, never
with its text.
