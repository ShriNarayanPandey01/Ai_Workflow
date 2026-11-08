from __future__ import annotations

import asyncio
import io
import re

ALLOWED_MEDIA_TYPES = frozenset(
    {
        "text/plain",
        "text/markdown",
        "application/pdf",
    }
)


class UnsupportedMediaTypeError(ValueError):
    """Raised when the document MIME type is not allowlisted."""


def normalize_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t]+\n", "\n", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


async def extract_text(*, media_type: str, data: bytes) -> str:
    if media_type not in ALLOWED_MEDIA_TYPES:
        msg = f"Unsupported media type: {media_type}"
        raise UnsupportedMediaTypeError(msg)

    if media_type in {"text/plain", "text/markdown"}:
        return normalize_text(data.decode("utf-8", errors="replace"))

    return await asyncio.to_thread(_extract_pdf, data)


def _extract_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    parts: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            parts.append(text)
    return normalize_text("\n\n".join(parts))
