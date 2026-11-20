"""Voice messages: audio -> text (Groq Whisper). The web app then sends the text through
the normal chat stream, so a voice message is answered like a typed one."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.llm.stt import SpeechToText, SttUnavailableError, get_stt

router = APIRouter(tags=["voice"])

MAX_AUDIO_BYTES = 15 * 1024 * 1024  # ~2 minutes of compressed audio is far below this


@router.post("/voice")
async def transcribe(
    audio: Annotated[UploadFile, File(description="recording: webm/ogg/mp4/m4a/wav")],
    stt: SpeechToText = Depends(get_stt),
) -> dict[str, Any]:
    data = await audio.read(MAX_AUDIO_BYTES + 1)
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(413, detail={"code": "too_long"})
    if not data:
        raise HTTPException(422, detail={"code": "no_speech"})
    if not stt.configured:
        raise HTTPException(503, detail={"code": "stt_unavailable"})
    try:
        transcript = await stt.transcribe(data, audio.filename or "voice.webm")
    except SttUnavailableError as exc:
        raise HTTPException(503, detail={"code": "stt_unavailable", "message": str(exc)}) from exc
    if not transcript.text:
        raise HTTPException(422, detail={"code": "no_speech"})
    return {"text": transcript.text, "seconds": transcript.seconds}
