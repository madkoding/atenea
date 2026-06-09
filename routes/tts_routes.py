# routes/tts_routes.py
"""
TTS API routes — multi-provider (local Kokoro, API endpoint, browser).
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)


class TTSRequest(BaseModel):
    text: str
    format: str = "audio"  # "audio" or "base64"


def _audio_response(audio_data: bytes) -> Response:
    is_mp3 = audio_data[:3] == b"ID3" or (
        len(audio_data) >= 2 and audio_data[0] == 0xFF and (audio_data[1] & 0xE0) == 0xE0
    )
    mime = "audio/mpeg" if is_mp3 else "audio/wav"
    filename = "speech.mp3" if "mpeg" in mime else "speech.wav"
    return Response(
        content=audio_data,
        media_type=mime,
        headers={"Content-Disposition": f"inline; filename={filename}"},
    )


def _synthesis_failed() -> HTTPException:
    return HTTPException(status_code=500, detail={"message": "Synthesis failed"})


def setup_tts_routes(tts_service):
    """Setup TTS routes with the provided TTS service"""
    router = APIRouter(prefix="/api/tts", tags=["tts"])

    @router.get("/stats")
    async def get_tts_stats():
        """Get TTS service statistics"""
        try:
            return tts_service.get_stats()
        except Exception as e:
            logger.error(f"Failed to get TTS stats: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to get TTS stats")

    @router.post("/synthesize")
    async def synthesize_speech(request: TTSRequest):
        """Synthesize speech from text"""
        try:
            if not tts_service.available:
                raise HTTPException(
                    status_code=503,
                    detail={"message": "TTS service not available"}
                )
            
            if request.format == "base64":
                audio_b64 = tts_service.synthesize_to_base64(request.text)
                if not audio_b64:
                    raise _synthesis_failed()
                return {"audio": audio_b64}
            
            else:  # audio format
                audio_data = tts_service.synthesize(request.text)
                if not audio_data:
                    raise _synthesis_failed()
                return _audio_response(audio_data)
        
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Synthesis error: {e}", exc_info=True)
            raise _synthesis_failed()

    @router.post("/clear-cache")
    async def clear_tts_cache():
        """Clear TTS cache"""
        try:
            tts_service.clear_cache()
            return {"success": True, "message": "Cache cleared"}
        except Exception as e:
            logger.error(f"Failed to clear cache: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to clear TTS cache")

    return router
