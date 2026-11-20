"""Voice: transcription through a fake Whisper client, cost and usage recorded."""

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import httpx2
import pytest

from app.config import Settings
from app.llm.stt import SpeechToText, get_stt
from app.llm.usage import InMemoryUsageStore
from app.main import create_app
from tests.llm.fakes import make_config


class FakeWhisper:
    def __init__(self, text: str = "Yarın 14'te toplantı var.", duration: float = 3.2) -> None:
        self.calls: list[dict[str, Any]] = []
        self.audio = SimpleNamespace(transcriptions=self)
        self._result = SimpleNamespace(text=text, duration=duration)

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self._result


def stt(client: Any = None) -> tuple[SpeechToText, InMemoryUsageStore]:
    store = InMemoryUsageStore()
    return SpeechToText(make_config(), Settings(_env_file=None), store, client=client), store


async def test_transcribe_records_cost_with_the_minimum_billed() -> None:
    whisper = FakeWhisper()
    speech, store = stt(whisper)

    transcript = await speech.transcribe(b"RIFF....", "voice.webm")

    assert transcript.text == "Yarın 14'te toplantı var."
    assert whisper.calls[0]["model"] == "whisper-large-v3"
    assert whisper.calls[0]["language"] == "tr"
    assert whisper.calls[0]["file"] == ("voice.webm", b"RIFF....")
    assert transcript.cost_usd == Decimal("0.000308")  # 10 s billed at $0.111 / h
    (record,) = store.records
    assert (record.provider, record.tier, record.purpose) == ("groq", "stt", "voice")


async def test_not_configured_without_a_key() -> None:
    speech, _ = stt()
    assert not speech.configured


@pytest.mark.parametrize(
    ("whisper", "audio", "status", "code"),
    [
        (FakeWhisper(), b"audio", 200, None),
        (FakeWhisper(text="  "), b"audio", 422, "no_speech"),
        (FakeWhisper(), b"", 422, "no_speech"),
        (None, b"audio", 503, "stt_unavailable"),
    ],
)
async def test_voice_endpoint(whisper: Any, audio: bytes, status: int, code: str | None) -> None:
    app = create_app()
    app.dependency_overrides[get_stt] = lambda: stt(whisper)[0]
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as http:
        response = await http.post(
            "/api/voice", files={"audio": ("voice.webm", audio, "audio/webm")}
        )

    assert response.status_code == status, response.text
    if code:
        assert response.json()["detail"]["code"] == code
    else:
        assert response.json()["text"] == "Yarın 14'te toplantı var."
