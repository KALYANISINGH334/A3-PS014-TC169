"""Explicit, bounded collection settings; adapted from the existing main-branch agent."""
import json
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from backend.models import AccessMedium


class Target(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,40}$")
    host: str = Field(pattern=r"^[a-zA-Z0-9.-]{1,253}$")
    port: int = Field(default=443, ge=1, le=65535)
    approved: bool = False
    download_url: str | None = None

    @model_validator(mode="after")
    def validate_download(self):
        if self.download_url:
            url = urlsplit(self.download_url)
            if (url.scheme not in {"http", "https"} or url.hostname != self.host
                    or (url.port or (443 if url.scheme == "https" else 80)) != self.port
                    or url.username or url.password or url.query or url.fragment):
                raise ValueError("Download URL must match target host/port and have no credentials, query or fragment")
        return self


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    enabled: bool = True
    pilot_days: int | None = Field(default=7, ge=1, le=365)
    interval_seconds: int = Field(default=300, ge=60, le=86400)
    samples: int = Field(default=3, ge=1, le=5)
    timeout_seconds: float = Field(default=2, ge=0.1, le=5)
    dns_hostname: str = Field(default="example.com", pattern=r"^[a-zA-Z0-9.-]{1,253}$")
    throughput_enabled: bool = False
    throughput_interval_seconds: int = Field(default=3600, ge=1800, le=86400)
    max_download_bytes: int = Field(default=262144, ge=1024, le=1048576)
    access_medium: AccessMedium = AccessMedium.wifi
    verification_source: str = Field(default="unverified", pattern="^(unverified|participant_attestation|operator_record)$")
    confirmed_interface: str | None = Field(default=None, max_length=200)
    participant_id: UUID | None = None
    isp: str | None = Field(default=None, max_length=80)
    location_category: str = Field(default="unknown", pattern="^(urban|suburban|rural|unknown)$")
    targets: list[Target] = Field(default_factory=lambda: [Target(id="cloudflare-public-dns", host="1.1.1.1", approved=True)], min_length=1, max_length=3)

    @model_validator(mode="after")
    def consistent_settings(self):
        if len({target.id for target in self.targets}) != len(self.targets):
            raise ValueError("Target IDs must be unique")
        if self.verification_source != "unverified" and (not self.confirmed_interface or self.access_medium == AccessMedium.unknown):
            raise ValueError("Verified labels require confirmed_interface and a known access_medium")
        if self.throughput_enabled and not any(target.approved and target.download_url for target in self.targets):
            raise ValueError("Throughput requires an explicitly approved download URL")
        return self


def load_settings(path: str) -> Settings:
    file = Path(path)
    if not file.exists():
        raise ValueError("Configuration is missing. Copy targets.example.json to targets.json first.")
    return Settings.model_validate(json.loads(file.read_text(encoding="utf-8")))
