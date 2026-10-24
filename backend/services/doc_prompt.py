"""A document question of a chosen size, for measuring how long a model takes to start answering.

Ask Zetty answers from up to ~6,000 tokens of a person's files, so that is the wait that
matters, not the first token of a one-line prompt. Used by the model benchmark
(backend/services/model_benchmark.py) and scripts/llm_bench.py. No imports from the app,
so the script can use it on its own.
"""

from __future__ import annotations

import secrets

DOC_PROMPT_TOKENS = 6000
QUESTION = (
    "Using only the documents above, list the three maintenance steps that come up most often "
    "and say which document mentions each."
)
_SECTIONS = [
    (
        "Boiler maintenance notes",
        "Check the pressure gauge every month; it should read between 1.0 and 1.5 bar when cold. "
        "Bleed the radiators in autumn, starting with the one closest to the boiler. Book a service every twelve months "
        "and keep the receipt with the warranty card.",
    ),
    (
        "Household budget review",
        "Groceries rose by eight percent over the year while energy fell after the insulation work. "
        "The emergency fund now covers four months of fixed costs. Review the insurance renewals in March and compare at "
        "least three quotes before renewing.",
    ),
    (
        "NAS backup plan",
        "Keep three copies of important data on two kinds of media, one of them away from home. "
        "Test a restore every quarter by recovering a random folder to a scratch location and comparing checksums. "
        "Replace any disk that reports reallocated or pending sectors.",
    ),
    (
        "Car service log",
        "Change the oil and filter every 15,000 kilometres or once a year. Rotate the tyres at each "
        "service and check the brake pads for wear. Replace the cabin filter every two years.",
    ),
    (
        "Garden calendar",
        "Prune the apple trees in late winter before the buds open. Mulch the beds in spring to keep "
        "moisture in, and clean the gutters after the leaves fall so the rain barrel stays clear.",
    ),
]
# English text with these excerpts comes to about 4.45 characters per token (Llama, Qwen tokenizers)
CHARS_PER_TOKEN = 4.45


def build_document_prompt(target_tokens: int = DOC_PROMPT_TOKENS) -> str:
    """Numbered document excerpts adding up to about target_tokens, then the question. The first
    line is random, so a runtime can't answer it from a cached prompt."""
    parts = [f"Session {secrets.token_hex(4)}. You answer questions about the user's documents.\n"]
    budget, n, size = int(target_tokens * CHARS_PER_TOKEN), 0, len(parts[0])
    while size < budget:
        title, body = _SECTIONS[n % len(_SECTIONS)]
        part = f"\n[Document {n + 1}: {title}, page {n // len(_SECTIONS) + 1}]\n{body}\n"
        parts.append(part)
        size += len(part)
        n += 1
    parts.append(f"\nQuestion: {QUESTION}\nAnswer:")
    return "".join(parts)
