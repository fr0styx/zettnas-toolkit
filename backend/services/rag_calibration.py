"""The similarity cut-off for each embedding model, measured on this install (AI-17).

Search drops a passage that shares no word with the question when its vector similarity is
below the profile's vec_min. Where that line belongs depends on the model: EmbeddingGemma,
nomic-embed-text and bge-m3 spread their cosines differently, and a cut-off that suits one throws
away good matches of another or lets noise through. So instead of one number for every neural
model, each exact model (id and vector size) is measured once, the first time search uses it:

- the questions and passages below are embedded the way search and indexing do it (query and
  document prompts), in five languages and across languages, as the household files ZettNAS
  indexes;
- for each question, the similarity to its own passage and to every other one;
- the model's noise level is what a question reaches with passages about something else (the
  90th percentile of those similarities): below it, a match says nothing;
- vec_min is that noise level, but never above the built-in profile's value. Short, clean pairs
  score higher than real file passages do (a whole page, another language), so a cut-off placed
  between right and wrong pairs here would drop good matches in real files. The measurement
  only ever lowers the cut-off, for models whose similarities sit lower than EmbeddingGemma's,
  never makes search stricter than the tested default.

The result lives in the data folder (ai/vec_thresholds.json), so nothing measured on one machine
ends up in the code. Until a model is measured, and when measuring fails, the built-in profile
stands. Measuring is about 50 embeddings, once per model, in a background thread.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

from backend.config import DATA_DIR, logger

STORE = os.path.join(DATA_DIR, "ai", "vec_thresholds.json")
MIN_VEC_MIN = 0.10
DEFAULT_VEC_MIN = 0.50  # the neural profile's value in rag_engine.SIMILARITY_PROFILES (a test keeps them equal)
RETRY_AFTER_SECS = 3600.0  # a failed measurement is tried again after this long
VERSION = 2  # bump when the pairs or the rule change, so every model is measured again

# (question, its passage); the passages are unrelated to each other's questions
PAIRS: list[tuple[str, str]] = [
    (
        "At what temperature do I bake the banana bread?",
        "Banana bread: mash three ripe bananas, mix with butter, sugar, eggs and flour, bake at 175 °C for about 55 minutes.",
    ),
    (
        "What boiler pressure should I aim for?",
        "Boiler notes: when refilling, bring the pressure up to 1.2 bar. Fault F22 means the pressure fell below 0.8 bar.",
    ),
    (
        "When does the car insurance renew?",
        "Motor policy schedule: cover runs from 1 March to 28 February; renewal notice is sent four weeks before.",
    ),
    (
        "Which vaccines are due for the kids this year?",
        "Vaccination record: MMR second dose due in May, tetanus booster at the next school check-up.",
    ),
    (
        "How do I reset the router to factory settings?",
        "Router manual: hold the reset button on the back for ten seconds until the lights flash, then set it up again.",
    ),
    (
        "What is the Wi-Fi password for guests?",
        "Guest network: name Garden-Guest, password printed on the card in the hall drawer, changes every spring.",
    ),
    (
        "Wann muss die Steuererklärung abgegeben werden?",
        "Steuer: Die Einkommensteuererklärung für das Vorjahr ist bis zum 31. Juli beim Finanzamt einzureichen.",
    ),
    (
        "Wie oft muss der Rauchmelder getestet werden?",
        "Rauchmelder im Flur und im Schlafzimmer einmal im Monat mit der Prüftaste testen, Batterie jährlich wechseln.",
    ),
    (
        "Quand le contrat d'électricité se termine-t-il ?",
        "Contrat d'électricité : durée d'un an à partir du 15 janvier, résiliable avec un préavis d'un mois.",
    ),
    (
        "Combien coûte la cantine par mois ?",
        "Facture de la cantine scolaire : 4,20 € par repas, soit environ 75 € par mois pour quatre jours par semaine.",
    ),
    (
        "¿Cuándo hay que revisar la caldera?",
        "Mantenimiento: la revisión de la caldera de gas es obligatoria cada dos años; la última fue en octubre.",
    ),
    (
        "¿Qué día se recoge la basura de reciclaje?",
        "Calendario de residuos: el contenedor amarillo se recoge los martes; el de papel, cada dos jueves.",
    ),
    ("洗衣机显示错误代码E3是什么意思？", "洗衣机说明书：E3 表示排水不畅，请清理底部的过滤器并检查排水管是否弯折。"),
    ("房租每个月几号交？", "租房合同：每月租金为 4500 元，须在每月 5 日前转账给房东。"),
    # across languages: the question in one, the file in another
    (
        "When is the dentist appointment?",
        "Zahnarzt: Kontrolltermin am Dienstag, 14. Oktober um 9:30 Uhr, Praxis Dr. Weber.",
    ),
    (
        "How much is the monthly gym membership?",
        "Abonnement salle de sport : 29,90 € par mois, engagement de douze mois, résiliation par écrit.",
    ),
    (
        "Where is the spare key for the shed?",
        "Llave de repuesto del cobertizo: colgada en el gancho detrás de la puerta del garaje.",
    ),
    ("What does the warranty on the fridge cover?", "冰箱保修卡：压缩机保修十年，其他部件保修两年，需保留购买发票。"),
    (
        "Wie viel Strom verbraucht die Wärmepumpe im Jahr?",
        "Heat pump report: annual consumption about 3,400 kWh, seasonal performance factor 4.1.",
    ),
    (
        "Qui garde le chat pendant les vacances ?",
        "Pet sitting: the neighbours at number 12 feed the cat twice a day while we are away in August.",
    ),
    (
        "¿Cuál es el número de póliza del seguro de hogar?",
        "Home insurance certificate: policy number HX-4471-209, building and contents cover.",
    ),
    (
        "我们的航班几点起飞？",
        "Flight booking: departure 07:45 from terminal 2, check-in closes 45 minutes before, seats 14A and 14B.",
    ),
    (
        "What is in the emergency kit?",
        "Notfallset im Keller: Taschenlampe, Batterien, Wasser für drei Tage, Erste-Hilfe-Kasten und Kerzen.",
    ),
    ("How long do I steam the dumplings?", "饺子做法：水开后放入蒸笼，大火蒸十二分钟，出锅前不要开盖。"),
]

_LOCK = threading.Lock()
_RUNNING: set[str] = set()
_FAILED: dict[str, float] = {}
_CACHE: dict[str, Any] = {}


def model_key(model: str, dim: int | None) -> str:
    """The exact model: its id (without Ollama's ':latest') and the vector size search uses."""
    return f"{(model or '').strip().lower().removesuffix(':latest')}@{dim or 'native'}"


def _load() -> dict[str, Any]:
    if "store" not in _CACHE:
        try:
            with open(STORE, encoding="utf-8") as f:
                data = json.load(f)
            _CACHE["store"] = data if isinstance(data, dict) and data.get("version") == VERSION else {}
        except (OSError, ValueError):
            _CACHE["store"] = {}
    return _CACHE["store"]


def measured(model: str, dim: int | None) -> dict[str, Any] | None:
    """The stored measurement for this exact model, or None."""
    return (_load().get("models") or {}).get(model_key(model, dim))


def _percentile(values: list[float], p: float) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, max(0, int(round(p * (len(s) - 1)))))]


def threshold(right: list[float], others: list[float], default: float) -> tuple[float, float]:
    """(vec_min, noise) from each question's similarity to its own passage and to the others:
    the noise level, capped at the default, and never above the weakest right matches."""
    noise = _percentile(others, 0.90)
    value = min(default, noise, _percentile(right, 0.10) - 0.05)
    return round(max(MIN_VEC_MIN, value), 3), round(noise, 3)


def measure(model: str, dim: int | None, host: str | None) -> dict[str, Any] | None:
    """Embeds the pairs with this model and works out its cut-off; None when the embedder fails."""
    from backend.services.rag_embeddings import (
        compute_neural_embedding_via_ollama,
        compute_neural_embeddings_batch,
        cosine_similarity_vec,
        format_embeddinggemma_document,
        unpack_embedding,
    )

    blobs = compute_neural_embeddings_batch(
        [format_embeddinggemma_document(None, p) for _, p in PAIRS], model, target_dim=dim, host=host
    )
    if not blobs or len(blobs) != len(PAIRS):
        return None
    docs = [unpack_embedding(b) for b in blobs]
    queries = []
    for q, _ in PAIRS:
        res = compute_neural_embedding_via_ollama(
            q, model=model, host=host, timeout=10.0, target_dim=dim, is_query=True
        )
        if res is None:
            return None
        queries.append(res[1])
    if not all(docs):
        return None
    right, others = [], []
    for i, qv in enumerate(queries):
        sims = [cosine_similarity_vec(qv, d) for d in docs]
        right.append(sims[i])
        others.extend(s for j, s in enumerate(sims) if j != i)
    vec_min, noise = threshold(right, others, DEFAULT_VEC_MIN)
    return {
        "vec_min": vec_min,
        "noise": noise,
        "right_p10": round(_percentile(right, 0.10), 3),
        "pairs": len(PAIRS),
        "ts": int(time.time()),
    }


def _save(key: str, result: dict[str, Any]) -> None:
    from backend.fsutil import atomic_write_json

    with _LOCK:
        store = dict(_load())
        store["version"] = VERSION
        store["models"] = {**(store.get("models") or {}), key: result}
        os.makedirs(os.path.dirname(STORE), exist_ok=True)
        atomic_write_json(STORE, store)
        _CACHE["store"] = store


def ensure_measured(model: str, dim: int | None, host: str | None, background: bool = True) -> None:
    """Measures this exact model once (in a thread unless background=False); does nothing for the
    built-in lexical vectors, a model already measured, one being measured, or one that failed
    within the last hour."""
    if not model or "lexical" in model.lower():
        return
    if background and os.environ.get("TESTING"):
        return  # tests ask for it explicitly (background=False), never as a side effect of a search
    key = model_key(model, dim)
    with _LOCK:
        if key in _RUNNING or measured(model, dim) or time.time() - _FAILED.get(key, 0.0) < RETRY_AFTER_SECS:
            return
        _RUNNING.add(key)

    def run() -> None:
        try:
            result = measure(model, dim, host)
            if result is None:
                _FAILED[key] = time.time()
                logger.info("[AI] Could not measure the similarity cut-off for %s; using the default", key)
            else:
                _save(key, result)
                logger.info("[AI] Similarity cut-off for %s: %s", key, result["vec_min"])
        except Exception:
            _FAILED[key] = time.time()
            logger.warning("[AI] Measuring the similarity cut-off for %s failed", key, exc_info=True)
        finally:
            with _LOCK:
                _RUNNING.discard(key)

    if background:
        threading.Thread(target=run, name="zn-vec-calibrate", daemon=True).start()
    else:
        run()


def reset() -> None:
    """Forgets what is cached in memory (tests, and after the store changed on disk)."""
    with _LOCK:
        _CACHE.clear()
        _FAILED.clear()
        _RUNNING.clear()
