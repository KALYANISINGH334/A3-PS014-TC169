"""Upload the shared payload to the existing measurement API."""
import os
from urllib.parse import urlsplit

import httpx

from dashboard.api import APIClient, APIError


class UploadError(Exception):
    def __init__(self, message, retryable=True):
        super().__init__(message)
        self.retryable = retryable


def upload_observation(payload, base_url=None, transport=None):
    try:
        client = APIClient(base_url, transport)
    except APIError as exc:
        raise UploadError(str(exc)) from exc
    parsed = urlsplit(client.base_url)
    if transport is None and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        if parsed.scheme != "https" or not os.environ.get("NETPULSE_UPLOAD_TOKEN"):
            raise UploadError("A central backend requires HTTPS and NETPULSE_UPLOAD_TOKEN.")
    try:
        saved = client.create(payload)
        if saved.observation_id != payload.observation_id:
            raise UploadError("API acknowledgment did not match the queued observation.")
        return saved
    except APIError as exc:
        code = exc.__cause__.response.status_code if isinstance(exc.__cause__, httpx.HTTPStatusError) else None
        retryable = code not in {400, 404, 409, 413, 422}
        raise UploadError(str(exc), retryable) from exc
