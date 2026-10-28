import io
import struct
import wave

import pytest
import soundfile as sf

from services.audio import UnsupportedAudio, prepare_audio


def pcm():
    stream = io.BytesIO()
    with wave.open(stream, "wb") as output:
        output.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        output.writeframes(b"\x00\x00" * 160)
    return stream.getvalue()


def no_native_parser(*_args, **_kwargs):
    raise AssertionError("Untrusted WAV must not reach native format parsing")


def test_compressed_wav_is_rejected_before_native_header_parsing(monkeypatch):
    monkeypatch.setattr(sf, "info", no_native_parser)
    data = bytearray(pcm())
    struct.pack_into("<H", data, 20, 0x11)  # Benign IMA ADPCM format tag; no exploit payload.
    with pytest.raises(UnsupportedAudio):
        prepare_audio(bytes(data))


def test_pcm_is_rewritten_and_trailing_ambiguous_chunks_do_not_reach_decoder(monkeypatch):
    monkeypatch.setattr(sf, "info", no_native_parser)
    original = pcm()
    duplicate = b"fmt " + struct.pack("<IHHIIHH", 16, 0x11, 1, 16000, 32000, 2, 16)
    body = bytearray(original + duplicate)
    struct.pack_into("<I", body, 4, len(body) - 8)
    normalized, metadata = prepare_audio(bytes(body))
    assert normalized == original
    assert metadata.duration == 0.01
    assert metadata.format == "WAV"
    with pytest.raises(UnsupportedAudio, match="Truncated"):
        prepare_audio(original[:-2])


def test_flac_remains_supported_and_other_containers_are_rejected():
    stream = io.BytesIO()
    sf.write(stream, [0.0] * 160, 16000, format="FLAC")
    body = stream.getvalue()
    normalized, metadata = prepare_audio(body)
    assert normalized == body and metadata.format == "FLAC"
    assert metadata.duration == 0.01
    with pytest.raises(UnsupportedAudio):
        prepare_audio(b"OggS" + b"\x00" * 32)
