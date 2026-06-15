import requests

TIMEOUT_SECONDS = 30
MAX_RESPONSE_BYTES = 10 * 1024 * 1024  # 10 MB — guards the worker against an over-large response


def get_capped_bytes(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
) -> bytes:
    """GET a URL, streaming the body and refusing anything over MAX_RESPONSE_BYTES."""
    resp = requests.get(url, headers=headers, params=params, timeout=TIMEOUT_SECONDS, stream=True)
    resp.raise_for_status()
    chunks: list[bytes] = []
    total = 0
    for chunk in resp.iter_content(chunk_size=65536):
        if not chunk:
            continue
        total += len(chunk)
        if total > MAX_RESPONSE_BYTES:
            resp.close()
            raise ValueError(f"Response from {url} exceeds {MAX_RESPONSE_BYTES} bytes")
        chunks.append(chunk)
    return b"".join(chunks)
