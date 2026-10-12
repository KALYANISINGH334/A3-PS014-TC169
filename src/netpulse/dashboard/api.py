"""Bounded HTTP operations with explicit errors and response validation."""
import os
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError

from backend.models import Measurement, MeasurementCreate, MeasurementList


class APIError(Exception):
    """An actionable error safe to show in the interface."""


class APIClient:
    def __init__(self, base_url=None, transport=None):
        self.base_url = (base_url or os.environ.get("NETPULSE_API_URL", "http://127.0.0.1:8000")).rstrip("/")
        try:
            parsed = urlsplit(self.base_url)
            # Evaluate the port too; malformed ports otherwise fail later in httpx.
            _ = parsed.port
            valid = (parsed.scheme in {"http", "https"} and parsed.hostname
                     and not parsed.username and not parsed.password
                     and not parsed.query and not parsed.fragment)
            httpx.URL(self.base_url)
        except (ValueError, httpx.InvalidURL) as exc:
            raise APIError("NETPULSE_API_URL is not a valid HTTP(S) URL.") from exc
        if not valid:
            raise APIError("NETPULSE_API_URL must be an HTTP(S) URL without credentials, query, or fragment.")
        self.transport = transport

    def request(self, method, path, **kwargs):
        try:
            token = os.environ.get("NETPULSE_UPLOAD_TOKEN")
            if token:
                kwargs["headers"] = {**kwargs.get("headers", {}), "Authorization": "Bearer " + token}
            with httpx.Client(timeout=httpx.Timeout(5.0, connect=2.0), transport=self.transport) as client:
                response = client.request(method, self.base_url + path, **kwargs)
                response.raise_for_status()
                return response.json()
        except httpx.TimeoutException as exc:
            raise APIError("The API timed out. Check the backend and retry.") from exc
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            message = "Payload was rejected; check the API schema." if code == 422 else "Check the backend logs and storage configuration."
            raise APIError(f"API returned HTTP {code}. {message}") from exc
        except httpx.RequestError as exc:
            raise APIError("Cannot reach the API. Start the backend and check NETPULSE_API_URL.") from exc
        except ValueError as exc:
            raise APIError("The API returned invalid JSON.") from exc

    def health(self):
        body = self.request("GET", "/health")
        if body != {"status": "ok"}:
            raise APIError("The health endpoint returned an unexpected response.")
        return body

    def measurements(self):
        try:
            return MeasurementList.model_validate(self.request("GET", "/measurements", params={"limit": 5000, "offset": 0}))
        except ValidationError as exc:
            raise APIError("Measurement response does not match the NetPulse API schema.") from exc

    def create(self, payload: MeasurementCreate):
        try:
            return Measurement.model_validate(self.request("POST", "/measurements", json=payload.model_dump(mode="json")))
        except ValidationError as exc:
            raise APIError("The API returned an invalid saved observation.") from exc
