"""Admit PCM WAV before any native parsing; keep compressed WAV out of the API."""

import io
import wave
from dataclasses import dataclass

import soundfile as sf


class UnsupportedAudio(ValueError):
    pass


class AudioLimitError(ValueError):
    pass


@dataclass
class AudioMetadata:
    channels: int
    samplerate: int
    duration: float
    format: str


def validate_limits(metadata, max_seconds):
    if not 1 <= metadata.channels <= 2 or not 8000 <= metadata.samplerate <= 48000:
        raise AudioLimitError("Use mono/stereo audio between 8 and 48 kHz")
    if not 0 < metadata.duration <= max_seconds:
        raise AudioLimitError("Audio must be between 0 and 120 seconds")


def prepare_audio(body, max_seconds=120):
    if body[:4] == b"RIFF" and body[8:12] == b"WAVE":
        try:
            # Python's wave parser rejects ADPCM/other compressed WAV formats
            # without calling libsndfile or FFmpeg on the attacker-supplied header.
            with wave.open(io.BytesIO(body), "rb") as source:
                channels, width, rate, frames, compression, _ = source.getparams()
                if compression != "NONE" or width not in (1, 2, 3, 4):
                    raise UnsupportedAudio("Use integer PCM WAV or FLAC")
                metadata = AudioMetadata(channels, rate, frames / rate, "WAV")
                validate_limits(metadata, max_seconds)
                data = source.readframes(frames)
                if len(data) != frames * channels * width:
                    raise UnsupportedAudio("Truncated WAV data")
            # Rewrite a canonical PCM header. Checking only the first fmt chunk
            # would leave ambiguous/duplicate chunks for a different native parser.
            output = io.BytesIO()
            with wave.open(output, "wb") as target:
                target.setnchannels(channels)
                target.setsampwidth(width)
                target.setframerate(rate)
                target.writeframes(data)
            return output.getvalue(), metadata
        except (wave.Error, EOFError, ZeroDivisionError) as error:
            raise UnsupportedAudio("Use valid integer PCM WAV or FLAC") from error
    if body[:4] == b"fLaC":
        try:
            metadata = sf.info(io.BytesIO(body))
        except (RuntimeError, sf.LibsndfileError) as error:
            raise UnsupportedAudio("Use valid integer PCM WAV or FLAC") from error
        if metadata.format != "FLAC":
            raise UnsupportedAudio("Use integer PCM WAV or FLAC")
        validate_limits(metadata, max_seconds)
        return body, metadata
    raise UnsupportedAudio("Use integer PCM WAV or FLAC")
