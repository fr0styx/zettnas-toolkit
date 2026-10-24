"""How fast a chat model starts answering a document question, per runtime (AI-7).

Ask Zetty answers from up to ~6,000 tokens of your files, so what people wait for is the
time to the first token of a long prompt, then the writing speed. This measures both for
the same model on:

  ollama   an Ollama server (GPU through Vulkan, or the CPU with --cpu)
  genai    OpenVINO GenAI in this Python (pip install openvino-genai), on GPU, CPU or NPU,
           from an OpenVINO model folder or the GGUF file Ollama uses

    python scripts/llm_bench.py ollama --host http://localhost:11434 --model llama3.2:3b
    python scripts/llm_bench.py ollama --host http://localhost:11434 --model llama3.2:3b --cpu
    python scripts/llm_bench.py genai --model /models/blobs/sha256-... --device GPU

Each run uses a new prompt (a random first line), so no runtime can answer from a cached
prompt. Results are printed as one JSON object per line.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.services.doc_prompt import DOC_PROMPT_TOKENS, build_document_prompt  # noqa: E402


def _post_stream(url: str, body: dict, timeout: float = 900.0):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for line in resp:
            if line.strip():
                yield json.loads(line)


def run_ollama(host: str, model: str, prompt: str, cpu: bool, num_predict: int, num_ctx: int) -> dict:
    options = {"num_predict": num_predict, "temperature": 0, "num_ctx": num_ctx}
    if cpu:
        options["num_gpu"] = 0
    # load the model first, so the timing below is the prompt, not the load
    list(
        _post_stream(
            f"{host}/api/generate",
            {
                "model": model,
                "prompt": "Hi",
                "stream": True,
                "keep_alive": "5m",
                "options": {**options, "num_predict": 1},
            },
        )
    )
    start, first, last = time.perf_counter(), None, {}
    for chunk in _post_stream(
        f"{host}/api/generate",
        {"model": model, "prompt": prompt, "stream": True, "keep_alive": "5m", "options": options},
    ):
        if first is None and (chunk.get("response") or chunk.get("thinking")):  # thinking models stream that first
            first = time.perf_counter()
        last = chunk
    ev_n, ev_ns = int(last.get("eval_count") or 0), int(last.get("eval_duration") or 0)
    return {
        "runtime": "ollama-cpu" if cpu else "ollama",
        "model": model,
        "prompt_tokens": int(last.get("prompt_eval_count") or 0),
        "first_token_s": round((first or time.perf_counter()) - start, 2),
        "prompt_tokens_per_s": round(
            int(last.get("prompt_eval_count") or 0) / (int(last.get("prompt_eval_duration") or 1) / 1e9), 1
        ),
        "tokens_per_s": round(ev_n / (ev_ns / 1e9), 1) if ev_ns else 0.0,
        "generated": ev_n,
    }


def run_genai(model: str, device: str, prompt: str, num_predict: int) -> dict:
    import openvino_genai as ov_genai

    t0 = time.perf_counter()
    pipe = ov_genai.LLMPipeline(model, device)
    load_s = time.perf_counter() - t0
    tok = pipe.get_tokenizer()
    n_prompt = int(tok.encode(prompt).input_ids.get_shape()[-1])
    pipe.generate("Hi", max_new_tokens=1)  # first compile of the short path
    times: list[float] = []

    def streamer(_text: str) -> bool:
        times.append(time.perf_counter())
        return False

    start = time.perf_counter()
    pipe.generate(prompt, max_new_tokens=num_predict, do_sample=False, streamer=streamer)
    end = time.perf_counter()
    first = times[0] if times else end
    gen = len(times)
    return {
        "runtime": f"genai-{device.lower()}",
        "model": model.rsplit("/", 1)[-1][:40],
        "prompt_tokens": n_prompt,
        "first_token_s": round(first - start, 2),
        "prompt_tokens_per_s": round(n_prompt / max(first - start, 1e-6), 1),
        "tokens_per_s": round((gen - 1) / max(end - first, 1e-6), 1) if gen > 1 else 0.0,
        "generated": gen,
        "load_s": round(load_s, 1),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("runtime", choices=["ollama", "genai"])
    ap.add_argument("--model", required=True)
    ap.add_argument("--host", default="http://localhost:11434")
    ap.add_argument("--cpu", action="store_true", help="ollama: run on the CPU (num_gpu 0)")
    ap.add_argument("--device", default="GPU", help="genai: GPU, CPU or NPU")
    ap.add_argument("--tokens", type=int, default=DOC_PROMPT_TOKENS, help="prompt size")
    ap.add_argument("--predict", type=int, default=128, help="tokens to write")
    ap.add_argument("--ctx", type=int, default=8192, help="ollama context window")
    ap.add_argument("--runs", type=int, default=3)
    args = ap.parse_args(argv)
    results = []
    for _ in range(args.runs):
        prompt = build_document_prompt(args.tokens)
        if args.runtime == "ollama":
            r = run_ollama(args.host.rstrip("/"), args.model, prompt, args.cpu, args.predict, args.ctx)
        else:
            r = run_genai(args.model, args.device, prompt, args.predict)
        results.append(r)
        print(json.dumps(r), flush=True)
    if len(results) > 1:
        print(
            json.dumps(
                {
                    "runtime": results[0]["runtime"],
                    "median_first_token_s": statistics.median(r["first_token_s"] for r in results),
                    "median_tokens_per_s": statistics.median(r["tokens_per_s"] for r in results),
                }
            ),
            flush=True,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
