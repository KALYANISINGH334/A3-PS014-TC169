"""Shared API contract. Missing metrics stay null; zeros are real observations."""
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AccessMedium(str, Enum):
    wifi = "Wi-Fi"
    ethernet = "Ethernet"
    cellular = "Cellular"
    unknown = "Unknown"


class MeasurementCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)

    timestamp: datetime
    access_medium: AccessMedium = AccessMedium.unknown
    medium_verified: bool = False
    verification_source: str = Field(default="unverified", pattern="^(unverified|participant_attestation|operator_record)$")
    isp: str | None = Field(default=None, max_length=80)
    location_category: str | None = Field(default=None, pattern="^(urban|suburban|rural|unknown)$")
    status: str = Field(default="success", pattern="^(success|partial|failed)$")
    latency_ms: float | None = Field(default=None, ge=0, le=60000)
    packet_loss_pct: float | None = Field(default=None, ge=0, le=100)
    dns_ms: float | None = Field(default=None, ge=0, le=60000)
    throughput_mbps: float | None = Field(default=None, ge=0, le=1000000)

    # Optional additions keep previously imported observations compatible.
    observation_id: UUID | None = None
    participant_id: UUID | None = None
    device_id: UUID | None = None
    interface_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{24}$")
    network_changed: bool | None = None
    target_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,40}$")
    latency_method: str | None = Field(default=None, pattern="^(icmp_echo|external)$")
    dns_method: str | None = Field(default=None, pattern="^system_resolver$")
    probe_count: int | None = Field(default=None, ge=0, le=5)
    probe_replies: int | None = Field(default=None, ge=0, le=5)
    throughput_bytes: int | None = Field(default=None, ge=0, le=1048576)
    collection_interval_seconds: int | None = Field(default=None, ge=60, le=86400)
    collection_errors: list[str] = Field(default_factory=list, max_length=16)

    @field_validator("collection_errors")
    @classmethod
    def safe_error_codes(cls, values):
        import re
        if any(not re.fullmatch(r"[a-z0-9_]{1,80}", value) for value in values):
            raise ValueError("Use short diagnostic codes, not personal data or raw errors")
        return values

    @field_validator("timestamp")
    @classmethod
    def aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include a timezone, for example +00:00")
        value = value.astimezone(timezone.utc)
        if value > datetime.now(timezone.utc):
            raise ValueError("timestamp cannot be in the future")
        return value

    @model_validator(mode="after")
    def consistent_observation(self):
        if self.medium_verified:
            if self.access_medium == AccessMedium.unknown or self.verification_source == "unverified":
                raise ValueError("verified medium requires a known label and verification source")
        elif self.verification_source != "unverified":
            raise ValueError("unverified labels must use the unverified source")
        if self.probe_replies is not None and (self.probe_count is None or self.probe_replies > self.probe_count):
            raise ValueError("probe replies cannot exceed the probe count")
        metrics = [self.latency_ms, self.packet_loss_pct, self.dns_ms, self.throughput_mbps]
        if self.status in {"success", "partial"} and all(value is None for value in metrics):
            raise ValueError("success or partial records require at least one measured metric")
        if self.status == "failed" and any(value is not None for value in metrics):
            raise ValueError("use partial for attempts that returned some metrics")
        return self


class Measurement(MeasurementCreate):
    id: int


class MeasurementList(BaseModel):
    items: list[Measurement]
    total: int
    limit: int
    offset: int
