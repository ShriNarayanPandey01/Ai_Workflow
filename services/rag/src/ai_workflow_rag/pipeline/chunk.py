from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TextChunk:
    index: int
    text: str
    token_count: int
    metadata: dict[str, object]


def chunking_config_hash(*, chunk_size: int, overlap: int) -> str:
    payload = f"v1|{chunk_size}|{overlap}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def chunk_text(
    text: str,
    *,
    chunk_size: int = 1200,
    overlap: int = 200,
) -> list[TextChunk]:
    cleaned = text.strip()
    if not cleaned:
        return []

    if overlap >= chunk_size:
        msg = "chunk overlap must be smaller than chunk size"
        raise ValueError(msg)

    chunks: list[TextChunk] = []
    start = 0
    index = 0
    length = len(cleaned)
    while start < length:
        end = min(start + chunk_size, length)
        piece = cleaned[start:end].strip()
        if piece:
            chunks.append(
                TextChunk(
                    index=index,
                    text=piece,
                    token_count=max(1, len(piece.split())),
                    metadata={"start": start, "end": end},
                )
            )
            index += 1
        if end >= length:
            break
        start = max(0, end - overlap)
    return chunks
