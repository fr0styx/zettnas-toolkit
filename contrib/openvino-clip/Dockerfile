# SigLIP 2 image and text vectors on OpenVINO (see server.py). The model server image brings
# Intel's GPU runtime; the Python side only needs OpenVINO, a tokenizer and Pillow.
FROM openvino/model_server:latest-gpu@sha256:a928903fe429f1e3e27107cc45932d30d95febfd2d1159dc50869c3eac76fc58
USER root
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv \
 && rm -rf /var/lib/apt/lists/* \
 && python3 -m venv /venv \
 && /venv/bin/pip install --no-cache-dir "openvino==2026.4.*" "numpy<3" "transformers<6" "tokenizers<1" "pillow<13" sentencepiece
ENV PATH=/venv/bin:$PATH PYTHONUNBUFFERED=1
COPY server.py /app/server.py
EXPOSE 11436
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:11436/health', timeout=4)"
ENTRYPOINT ["python3", "/app/server.py"]
