"""Live: Groq Whisper on a Turkish recording (examples/audio, Windows TTS, made-up text).

docker compose exec api pytest -m live -k voice -s
"""

from pathlib import Path

import pytest

from app.config import get_settings
from app.core.time_resolver import normalize
from app.llm.config import load_providers_config
from app.llm.stt import SpeechToText
from app.llm.usage import InMemoryUsageStore

pytestmark = pytest.mark.live

SAMPLE = Path(__file__).resolve().parents[3] / "examples" / "audio" / "yarin_toplanti.wav"


async def test_turkish_voice_message() -> None:
    if not SAMPLE.is_file():
        pytest.skip("examples/ not mounted")
    store = InMemoryUsageStore()
    stt = SpeechToText(load_providers_config(), get_settings(), store)
    if not stt.configured:
        pytest.skip("no key for speech to text")

    try:
        transcript = await stt.transcribe(SAMPLE.read_bytes(), SAMPLE.name)
    finally:
        await stt.aclose()

    print(f"\n{transcript.text!r} ({transcript.seconds:.1f} s, ${transcript.cost_usd})")
    text = normalize(transcript.text)
    assert "yarin" in text
    assert "toplanti" in text
    assert store.records[0].tier == "stt"
