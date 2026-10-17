import io
import os
from contextlib import asynccontextmanager

import soundfile as sf
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest

from services.common import RequestBudgetMiddleware, authorize, instrument

AUDIO_SECONDS = Counter("afri_audio_seconds_total", "Successfully transcribed audio seconds")
MAX_BYTES = 20 * 1024 * 1024
MAX_SECONDS = 120


def create_app(transcriber=None):
    @asynccontextmanager
    async def lifespan(app):
        if transcriber is not None:
            app.state.transcribe = transcriber
        else:
            from faster_whisper import WhisperModel

            model_id = os.environ.get("ASR_MODEL")
            if not model_id:
                raise RuntimeError("Set ASR_MODEL to a reviewed CTranslate2 model directory")
            model = await run_in_threadpool(
                lambda: WhisperModel(
                    model_id,
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=int(os.environ.get("MODEL_THREADS", "2")),
                )
            )

            def decode(audio):
                segments, _ = model.transcribe(
                    io.BytesIO(audio),
                    language="yo",
                    beam_size=1,
                    temperature=0.0,
                    vad_filter=False,
                    condition_on_previous_text=False,
                )
                return " ".join(segment.text.strip() for segment in segments)

            app.state.transcribe = decode
        app.state.ready = True
        yield
        app.state.ready = False

    app = FastAPI(title="African-language speech service", lifespan=lifespan)
    app.state.ready = False
    app.add_middleware(
        RequestBudgetMiddleware, path="/transcribe", max_body_bytes=MAX_BYTES, max_inflight=1
    )
    instrument(app, "speech")

    @app.get("/health")
    def health():
        return {"status": "alive"}

    @app.get("/ready")
    def ready():
        if not app.state.ready:
            raise HTTPException(503, "Model is not ready")
        return {"status": "ready"}

    @app.get("/metrics")
    def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.post("/transcribe", dependencies=[Depends(authorize)])
    async def transcribe_audio(request: Request):
        if not app.state.ready:
            raise HTTPException(503, "Model is not ready")
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_BYTES:
                raise HTTPException(413, "Audio exceeds 20 MiB")
            chunks.append(chunk)
        audio = b"".join(chunks)
        try:
            metadata = sf.info(io.BytesIO(audio))
        except (RuntimeError, sf.LibsndfileError):
            raise HTTPException(415, "Send valid WAV or FLAC audio as the request body") from None
        duration = metadata.duration
        if metadata.format not in {"WAV", "WAVEX", "FLAC"}:
            raise HTTPException(415, "Send WAV or FLAC audio")
        if metadata.channels > 2 or not 8000 <= metadata.samplerate <= 48000:
            raise HTTPException(422, "Use mono/stereo audio between 8 and 48 kHz")
        if duration <= 0 or duration > MAX_SECONDS:
            raise HTTPException(422, "Audio must be between 0 and 120 seconds")
        text = await run_in_threadpool(app.state.transcribe, audio)
        AUDIO_SECONDS.inc(duration)
        return {"text": text, "language": "yo", "audio_seconds": duration}

    return app


app = create_app()
