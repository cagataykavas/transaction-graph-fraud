"""Capacity-aware evaluation for investigator-facing entity rankings."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from numbers import Real
from typing import Any


class RankingAuditError(ValueError):
    """Malformed ranking evidence that cannot be evaluated safely."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RankingObservation:
    entity_id: str
    score: float
    label: int


@dataclass(frozen=True)
class RankingAuditPolicy:
    review_capacity: int
    min_labeled_entities: int = 25
    min_positive_entities: int = 5
    min_precision_lower_bound: float = 0.10
    min_recall_lower_bound: float = 0.20
    min_lift_lower_bound: float = 1.50
    reject_ambiguous_cutoff: bool = False


@dataclass(frozen=True)
class RankingAuditReport:
    accepted: bool
    reason_codes: tuple[str, ...]
    labeled_entities: int
    positive_entities: int
    base_rate: float
    review_capacity: int
    cutoff_score: float
    guaranteed_review_ids: tuple[str, ...]
    boundary_tie_ids: tuple[str, ...]
    boundary_slots: int
    cutoff_ambiguous: bool
    true_positives_lower: int
    true_positives_upper: int
    precision_lower: float
    precision_upper: float
    recall_lower: float
    recall_upper: float
    lift_lower: float
    lift_upper: float

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for field in (
            "reason_codes",
            "guaranteed_review_ids",
            "boundary_tie_ids",
        ):
            payload[field] = list(payload[field])
        return payload


def audit_investigation_ranking(
    observations: Sequence[RankingObservation],
    *,
    policy: RankingAuditPolicy,
) -> RankingAuditReport:
    """Evaluate fraud capture at a fixed analyst capacity.

    If equal scores cross the capacity cutoff, the report returns the best and
    worst performance possible within that tie block. Admission always uses the
    conservative lower bound rather than an arbitrary entity-ID tie break.
    """

    _validate_policy(policy)
    records = _validate_observations(observations)
    if policy.review_capacity > len(records):
        raise RankingAuditError(
            "CAPACITY_EXCEEDS_SAMPLE",
            "review_capacity cannot exceed the labeled entity count",
        )

    ranked = sorted(records, key=lambda item: (-item.score, item.entity_id))
    cutoff = ranked[policy.review_capacity - 1].score
    guaranteed = tuple(item for item in ranked if item.score > cutoff)
    boundary = tuple(item for item in ranked if item.score == cutoff)
    boundary_slots = policy.review_capacity - len(guaranteed)
    cutoff_ambiguous = len(boundary) > boundary_slots

    guaranteed_positives = sum(item.label for item in guaranteed)
    boundary_positives = sum(item.label for item in boundary)
    boundary_negatives = len(boundary) - boundary_positives
    minimum_boundary_positives = max(0, boundary_slots - boundary_negatives)
    maximum_boundary_positives = min(boundary_slots, boundary_positives)
    true_positives_lower = guaranteed_positives + minimum_boundary_positives
    true_positives_upper = guaranteed_positives + maximum_boundary_positives

    positive_entities = sum(item.label for item in ranked)
    base_rate = positive_entities / len(ranked)
    precision_lower = true_positives_lower / policy.review_capacity
    precision_upper = true_positives_upper / policy.review_capacity
    recall_lower = (
        true_positives_lower / positive_entities if positive_entities else 0.0
    )
    recall_upper = (
        true_positives_upper / positive_entities if positive_entities else 0.0
    )
    lift_lower = precision_lower / base_rate if base_rate else 0.0
    lift_upper = precision_upper / base_rate if base_rate else 0.0

    reasons: list[str] = []
    if len(ranked) < policy.min_labeled_entities:
        reasons.append("INSUFFICIENT_LABELED_ENTITIES")
    if positive_entities < policy.min_positive_entities:
        reasons.append("INSUFFICIENT_POSITIVE_ENTITIES")
    if cutoff_ambiguous and policy.reject_ambiguous_cutoff:
        reasons.append("AMBIGUOUS_CAPACITY_CUTOFF")
    if precision_lower < policy.min_precision_lower_bound:
        reasons.append("PRECISION_LOWER_BOUND_BELOW_MINIMUM")
    if recall_lower < policy.min_recall_lower_bound:
        reasons.append("RECALL_LOWER_BOUND_BELOW_MINIMUM")
    if lift_lower < policy.min_lift_lower_bound:
        reasons.append("LIFT_LOWER_BOUND_BELOW_MINIMUM")

    return RankingAuditReport(
        accepted=not reasons,
        reason_codes=tuple(reasons),
        labeled_entities=len(ranked),
        positive_entities=positive_entities,
        base_rate=base_rate,
        review_capacity=policy.review_capacity,
        cutoff_score=cutoff,
        guaranteed_review_ids=tuple(item.entity_id for item in guaranteed),
        boundary_tie_ids=tuple(item.entity_id for item in boundary),
        boundary_slots=boundary_slots,
        cutoff_ambiguous=cutoff_ambiguous,
        true_positives_lower=true_positives_lower,
        true_positives_upper=true_positives_upper,
        precision_lower=precision_lower,
        precision_upper=precision_upper,
        recall_lower=recall_lower,
        recall_upper=recall_upper,
        lift_lower=lift_lower,
        lift_upper=lift_upper,
    )


def _validate_policy(policy: RankingAuditPolicy) -> None:
    if (
        not isinstance(policy.review_capacity, int)
        or isinstance(policy.review_capacity, bool)
        or policy.review_capacity < 1
    ):
        raise RankingAuditError(
            "INVALID_POLICY", "review_capacity must be a positive integer"
        )
    for field in ("min_labeled_entities", "min_positive_entities"):
        value = getattr(policy, field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise RankingAuditError(
                "INVALID_POLICY", f"{field} must be a positive integer"
            )
    for field in ("min_precision_lower_bound", "min_recall_lower_bound"):
        value = getattr(policy, field)
        if not _is_finite_real(value) or not 0.0 <= float(value) <= 1.0:
            raise RankingAuditError(
                "INVALID_POLICY", f"{field} must be between zero and one"
            )
    if (
        not _is_finite_real(policy.min_lift_lower_bound)
        or policy.min_lift_lower_bound < 0
    ):
        raise RankingAuditError(
            "INVALID_POLICY", "min_lift_lower_bound must be finite and non-negative"
        )
    if not isinstance(policy.reject_ambiguous_cutoff, bool):
        raise RankingAuditError(
            "INVALID_POLICY", "reject_ambiguous_cutoff must be boolean"
        )


def _validate_observations(
    observations: Sequence[RankingObservation],
) -> tuple[RankingObservation, ...]:
    if (
        isinstance(observations, (str, bytes))
        or not isinstance(observations, Sequence)
        or not observations
    ):
        raise RankingAuditError(
            "INVALID_OBSERVATIONS", "observations must be a non-empty sequence"
        )

    records: list[RankingObservation] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(observations):
        if not isinstance(item, RankingObservation):
            raise RankingAuditError(
                "INVALID_OBSERVATION", f"observation {index} has an invalid type"
            )
        if not isinstance(item.entity_id, str) or not item.entity_id.strip():
            raise RankingAuditError(
                "INVALID_ENTITY_ID", f"observation {index} has an invalid entity_id"
            )
        if item.entity_id in seen_ids:
            raise RankingAuditError(
                "DUPLICATE_ENTITY_ID", f"duplicate entity_id: {item.entity_id}"
            )
        if not _is_finite_real(item.score):
            raise RankingAuditError(
                "INVALID_SCORE", f"entity {item.entity_id} has a non-finite score"
            )
        if (
            not isinstance(item.label, int)
            or isinstance(item.label, bool)
            or item.label not in (0, 1)
        ):
            raise RankingAuditError(
                "INVALID_LABEL", f"entity {item.entity_id} label must be zero or one"
            )
        seen_ids.add(item.entity_id)
        records.append(
            RankingObservation(
                entity_id=item.entity_id,
                score=float(item.score),
                label=item.label,
            )
        )
    return tuple(records)


def _is_finite_real(value: Any) -> bool:
    return (
        isinstance(value, Real)
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )
