"""
MusicGen server — run this on the DGX Spark in ~/tisha/
  cd ~/tisha
  source venv/bin/activate
  pip install transformers accelerate torch torchaudio flask
  python dgx_musicgen_server.py

Then set DGX_MUSICGEN_URL=http://<dgx-ip>:7860 in your Mac .env
"""

import io
import os
import time
import logging
import tempfile

from flask import Flask, request, jsonify, send_file

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
_model = None
_processor = None


def _load_model():
    global _model, _processor
    if _model is not None:
        return
    logger.info("Loading MusicGen Small (first run — downloading ~2GB)...")
    from transformers import MusicgenForConditionalGeneration, AutoProcessor
    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info(f"Device: {device}")

    _processor = AutoProcessor.from_pretrained("facebook/musicgen-small")
    _model = MusicgenForConditionalGeneration.from_pretrained(
        "facebook/musicgen-small",
        torch_dtype=torch.float16 if device == "cuda" else torch.float32,
    ).to(device)
    logger.info("MusicGen loaded.")


@app.route("/health")
def health():
    return jsonify({"status": "ok", "model": "musicgen-small"})


@app.route("/generate", methods=["POST"])
def generate():
    data = request.json or {}
    prompt = data.get("prompt", "instrumental hip hop beat")
    duration = int(data.get("duration_seconds", 30))

    logger.info(f"Generating: '{prompt}' ({duration}s)")
    t0 = time.time()

    try:
        import torch
        _load_model()

        device = next(_model.parameters()).device
        inputs = _processor(text=[prompt], padding=True, return_tensors="pt").to(device)

        # tokens = ~50 per second for musicgen-small
        max_tokens = min(duration * 50, 1500)
        with torch.no_grad():
            audio_values = _model.generate(**inputs, max_new_tokens=max_tokens)

        import scipy.io.wavfile as wavfile
        import numpy as np
        sample_rate = _model.config.audio_encoder.sampling_rate
        audio_cpu = audio_values[0, 0].cpu().float().numpy()

        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        # Clamp to [-1, 1] and convert to int16 for standard WAV
        audio_int16 = (np.clip(audio_cpu, -1.0, 1.0) * 32767).astype(np.int16)
        wavfile.write(path, sample_rate, audio_int16)

        elapsed = round(time.time() - t0, 1)
        logger.info(f"Done in {elapsed}s → {path}")

        return send_file(path, mimetype="audio/wav", as_attachment=True,
                         download_name="musicgen_fill.wav")
    except Exception as e:
        logger.error(f"Generation failed: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    logger.info(f"MusicGen server on :{port}")
    # Pre-load so first request is fast
    _load_model()
    app.run(host="0.0.0.0", port=port)
