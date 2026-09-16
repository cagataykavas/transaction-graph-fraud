from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class Transaction:
    transaction_id: str
    src: str
    dst: str
    amount: float
    timestamp: float
    currency: str = "USD"
    channel: str = "bank_transfer"
    country_src: str = "US"
    country_dst: str = "US"

    def __post_init__(self) -> None:
        if self.amount < 0:
            raise ValueError("amount must be non-negative")
        if not self.src or not self.dst:
            raise ValueError("src and dst are required")
        if self.src == self.dst:
            raise ValueError("self-transfers are excluded from this reference model")

    @property
    def event_time_iso(self) -> str:
        return datetime.fromtimestamp(self.timestamp, tz=timezone.utc).isoformat()

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["event_time"] = self.event_time_iso
        return payload


@dataclass(frozen=True)
class GraphFinding:
    finding_id: str
    finding_type: str
    entities: tuple[str, ...]
    transaction_ids: tuple[str, ...]
    score: float
    severity: str
    explanation: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["entities"] = list(self.entities)
        payload["transaction_ids"] = list(self.transaction_ids)
        return payload


@dataclass(frozen=True)
class EntityRisk:
    entity_id: str
    score: float
    severity: str
    features: dict[str, float]
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reasons"] = list(self.reasons)
        return payload
