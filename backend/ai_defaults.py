"""The chat model Kiboto uses when none is chosen (decision D4, 10 Nov 2026).

Qwen3-4B (Apache-2.0) in Ollama's q4_K_M build, the one the five-language eval measured (answers
94.9% right, 85.7% backed by the sources, 70% of unanswerable questions declined; Phi-4-mini 87.8%,
77.0%, 30%). It replaces Qwen2.5-3B, whose licence is research-only. Ollama's plain qwen3:4b is the
always-thinking 2507 build, so the tag is pinned. Installs that chose a model keep it.
"""

DEFAULT_CHAT_MODEL = "qwen3:4b-q4_K_M"
