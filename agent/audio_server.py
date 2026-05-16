"""
Audio server — runs on DGX, port 8001.
Provides MusicGen generation and demucs stem separation.

Start on DGX:
    python -m agent.audio_server
    # or via run_audio_server.sh
"""
import io
import logging
import os
import subprocess
import tempfile
import traceback
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

import numpy as np
import torch
import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

app = FastAPI(title="Aux Audio Server", version="1.0.0")

_musicgen = None
_processor = None


def _load_musicgen():
    global _musicgen, _processor
    if _musicgen is None:
        from transformers import AutoProcessor, MusicgenForConditionalGeneration
        model_name = os.getenv("MODEL_NAME", "facebook/musicgen-small")
        _processor = AutoProcessor.from_pretrained(model_name)
        _musicgen = MusicgenForConditionalGeneration.from_pretrained(model_name)
        if torch.cuda.is_available():
            _musicgen = _musicgen.cuda()
    return _musicgen, _processor


class GenerateRequest(BaseModel):
    prompt: str
    duration: int = 8
    reference_audio_b64: str | None = None


@app.get("/health")
def health():
    return {"status": "ok", "cuda": torch.cuda.is_available()}


@app.post("/generate")
def generate(req: GenerateRequest):
    try:
        import scipy.io.wavfile as wav

        model, processor = _load_musicgen()
        device = "cuda" if torch.cuda.is_available() else "cpu"

        inputs = processor(
            text=[req.prompt],
            padding=True,
            return_tensors="pt",
        ).to(device)

        max_new_tokens = int(os.getenv("AUDIO_MAX_TOKENS", "1024"))
        with torch.no_grad():
            audio_values = model.generate(**inputs, max_new_tokens=max_new_tokens)

        audio = audio_values[0, 0].cpu().numpy().astype(np.float32)
        if np.abs(audio).max() > 0:
            audio = audio / np.abs(audio).max()
        audio_int16 = (audio * 32767).astype(np.int16)

        sample_rate = model.config.audio_encoder.sampling_rate
        buf = io.BytesIO()
        wav.write(buf, sample_rate, audio_int16)
        buf.seek(0)

        return Response(content=buf.read(), media_type="audio/wav")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/stems")
async def stems(file: UploadFile = File(...)):
    try:
        content = await file.read()
        suffix = Path(file.filename).suffix if file.filename else ".wav"

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_path = tmp_path / f"input{suffix}"
            input_path.write_bytes(content)

            result = subprocess.run(
                ["python", "-m", "demucs", "-o", str(tmp_path), str(input_path)],
                capture_output=True,
                timeout=300,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.decode(errors="replace"))

            stem_files = [f for f in tmp_path.rglob("*.wav") if f != input_path]

            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for sf in stem_files:
                    zf.write(sf, sf.name)
            buf.seek(0)

        return Response(
            content=buf.read(),
            media_type="application/zip",
            headers={"Content-Disposition": "attachment; filename=stems.zip"},
        )
    except Exception as e:
        logger.error("Stems error: %s", traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    port = int(os.getenv("AUDIO_SERVER_PORT", "8001"))
    uvicorn.run(app, host="0.0.0.0", port=port)
