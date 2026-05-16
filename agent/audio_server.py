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

import torch
import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

app = FastAPI(title="Aux Audio Server", version="1.0.0")

_MUSICGEN_SAMPLE_RATE = 32000

_musicgen = None
_processor = None
_is_melody_model = False


def _load_musicgen():
    global _musicgen, _processor, _is_melody_model
    if _musicgen is None:
        from transformers import AutoProcessor
        model_name = os.getenv("MUSICGEN_MODEL", "facebook/musicgen-small")
        _is_melody_model = "melody" in model_name
        _processor = AutoProcessor.from_pretrained(model_name)
        if _is_melody_model:
            from transformers import MusicgenMelodyForConditionalGeneration
            _musicgen = MusicgenMelodyForConditionalGeneration.from_pretrained(model_name)
        else:
            from transformers import MusicgenForConditionalGeneration
            _musicgen = MusicgenForConditionalGeneration.from_pretrained(model_name)
        if torch.cuda.is_available():
            _musicgen = _musicgen.cuda()
        logger.info("Loaded %s (melody_conditioning=%s)", model_name, _is_melody_model)
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
        max_new_tokens = req.duration * 50  # ~50 tokens/sec

        if req.reference_audio_b64 and _is_melody_model:
            import base64
            import librosa
            raw_bytes = base64.b64decode(req.reference_audio_b64)
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                tmp.write(raw_bytes)
                tmp_path = tmp.name
            try:
                # librosa handles any format (mp3/wav/flac) via soundfile/ffmpeg
                audio_np, _ = librosa.load(tmp_path, sr=_MUSICGEN_SAMPLE_RATE, mono=True)
            finally:
                os.unlink(tmp_path)
            inputs = processor(
                audio=[audio_np],
                sampling_rate=_MUSICGEN_SAMPLE_RATE,
                text=[req.prompt],
                padding=True,
                return_tensors="pt",
            ).to(device)
        else:
            inputs = processor(
                text=[req.prompt],
                padding=True,
                return_tensors="pt",
            ).to(device)

        with torch.no_grad():
            audio_values = model.generate(**inputs, max_new_tokens=max_new_tokens)

        audio_np = audio_values[0, 0].cpu().numpy()
        sample_rate = model.config.audio_encoder.sampling_rate

        buf = io.BytesIO()
        wav.write(buf, sample_rate, (audio_np * 32767).astype("int16"))
        buf.seek(0)

        return Response(content=buf.read(), media_type="audio/wav")
    except Exception as e:
        logger.error("Generate error: %s", traceback.format_exc())
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
