"""Content sniffing for accepted lecture audio and board photos."""

from __future__ import annotations

# Magic signatures, not client Content-Type.
_WEBM = bytes([0x1A, 0x45, 0xDF, 0xA3])


class SniffError(Exception):
    def __init__(self, message: str = "File type is not supported."):
        self.message = message
        super().__init__(message)


def _has_mp3_frame(data: bytes) -> bool:
    # Look for an MPEG audio frame sync in the first few kilobytes.
    window = data[:8192]
    for i in range(0, max(0, len(window) - 1)):
        if window[i] == 0xFF and (window[i + 1] & 0xE0) == 0xE0:
            return True
    return False


def sniff_audio(data: bytes) -> str:
    """Return a contract MIME type, or raise SniffError."""
    if len(data) < 12:
        raise SniffError("File is too small to be a valid audio recording.")
    if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
        return "audio/wav"
    if data.startswith(b"OggS"):
        return "audio/ogg"
    if data.startswith(_WEBM):
        return "audio/webm"
    if data[4:8] == b"ftyp":
        return "audio/mp4"
    if data.startswith(b"ID3") or _has_mp3_frame(data):
        return "audio/mpeg"
    raise SniffError("This audio type is not supported. Use mp4, m4a, mp3, wav, webm, or ogg.")


def sniff_image(data: bytes) -> str:
    if len(data) < 12:
        raise SniffError("File is too small to be a valid image.")
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    raise SniffError("This image type is not supported. Use jpeg, png, or webp.")


def extension_for_mime(mime: str) -> str:
    return {
        "audio/wav": ".wav",
        "audio/mpeg": ".mp3",
        "audio/mp4": ".m4a",
        "audio/webm": ".webm",
        "audio/ogg": ".ogg",
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }.get(mime, "")
