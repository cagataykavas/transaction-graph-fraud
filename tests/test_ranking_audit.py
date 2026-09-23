from __future__ import annotations

import math

import pytest

from graphfraud.ranking_audit import (
    RankingAuditError,
    RankingAuditPolicy,
    RankingObservation,
    audit_investigation_ranking,
)


def _policy(**overrides: object) -> RankingAuditPolicy:
    values: dict[str, object] = {
        "review_capacity": 3,
        "min_labeled_entities": 6,
        "min_positive_entities": 2,
        "min_precision_lower_bound": 0.50,
        "min_recall_lower_bound": 0.50,
        "min_lift_lower_bound": 1.20,
    }
    values.update(overrides)
    return RankingAuditPolicy(**values)


def _records(rows: list[tuple[str, float, int]]) -> list[RankingObservation]:
    return [RankingObservation(*row) for row in rows]


def test_accepts_ranking_that_captures_cases_within_capacity():
    observations = _records(
        [
            ("case-a", 0.99, 1),
            ("case-b", 0.95, 1),
            ("case-c", 0.90, 1),
            ("normal-a", 0.40, 0),
            ("normal-b", 0.20, 0),
            ("normal-c", 0.10, 0),
        ]
    )

    report = audit_investigation_ranking(observations, policy=_policy())

    assert report.accepted
    assert report.precision_lower == 1.0
    assert report.recall_lower == 1.0
    assert report.lift_lower == 2.0
    assert report.guaranteed_review_ids == ("case-a", "case-b")
    assert report.boundary_tie_ids == ("case-c",)


def test_rejects_low_capture_ranking_with_stable_reason_order():
    observations = _records(
        [
            ("normal-a", 0.99, 0),
            ("normal-b", 0.95, 0),
            ("case-a", 0.90, 1),
            ("case-b", 0.40, 1),
            ("normal-c", 0.20, 0),
            ("normal-d", 0.10, 0),
        ]
    )

    report = audit_investigation_ranking(observations, policy=_policy())

    assert not report.accepted
    assert report.reason_codes == (
        "PRECISION_LOWER_BOUND_BELOW_MINIMUM",
        "LIFT_LOWER_BOUND_BELOW_MINIMUM",
    )


def test_boundary_tie_reports_conservative_and_optimistic_bounds():
    observations = _records(
        [
            ("certain-case", 0.90, 1),
            ("tied-case", 0.80, 1),
            ("tied-normal-a", 0.80, 0),
            ("tied-normal-b", 0.80, 0),
            ("normal", 0.10, 0),
            ("case-low", 0.05, 1),
        ]
    )

    report = audit_investigation_ranking(
        observations,
        policy=_policy(review_capacity=2, min_precision_lower_bound=0.50),
    )

    assert report.cutoff_ambiguous
    assert report.boundary_slots == 1
    assert report.boundary_tie_ids == (
        "tied-case",
        "tied-normal-a",
        "tied-normal-b",
    )
    assert (report.true_positives_lower, report.true_positives_upper) == (1, 2)
    assert (report.precision_lower, report.precision_upper) == (0.5, 1.0)
    assert report.recall_lower == pytest.approx(1 / 3)
    assert report.recall_upper == pytest.approx(2 / 3)


def test_strict_policy_rejects_tie_that_crosses_capacity():
    observations = _records(
        [
            ("case-a", 0.90, 1),
            ("case-b", 0.80, 1),
            ("normal-a", 0.80, 0),
            ("normal-b", 0.80, 0),
            ("normal-c", 0.20, 0),
            ("normal-d", 0.10, 0),
        ]
    )

    report = audit_investigation_ranking(
        observations,
        policy=_policy(review_capacity=2, reject_ambiguous_cutoff=True),
    )

    assert "AMBIGUOUS_CAPACITY_CUTOFF" in report.reason_codes


def test_tie_fully_inside_capacity_is_not_ambiguous():
    observations = _records(
        [
            ("case-b", 0.90, 1),
            ("case-a", 0.90, 1),
            ("normal-a", 0.80, 0),
            ("normal-b", 0.70, 0),
            ("case-c", 0.20, 1),
            ("normal-c", 0.10, 0),
        ]
    )

    report = audit_investigation_ranking(
        observations,
        policy=_policy(review_capacity=2, reject_ambiguous_cutoff=True),
    )

    assert not report.cutoff_ambiguous
    assert report.boundary_tie_ids == ("case-a", "case-b")
    assert "AMBIGUOUS_CAPACITY_CUTOFF" not in report.reason_codes


def test_sparse_evidence_is_visible_in_report():
    observations = _records([("a", 0.9, 1), ("b", 0.8, 0), ("c", 0.7, 0)])

    report = audit_investigation_ranking(
        observations,
        policy=_policy(
            review_capacity=1,
            min_labeled_entities=5,
            min_positive_entities=2,
        ),
    )

    assert report.reason_codes[:2] == (
        "INSUFFICIENT_LABELED_ENTITIES",
        "INSUFFICIENT_POSITIVE_ENTITIES",
    )


def test_json_report_uses_arrays_and_is_deterministic():
    observations = _records(
        [
            ("z", 0.9, 1),
            ("a", 0.9, 0),
            ("b", 0.8, 1),
            ("c", 0.7, 0),
            ("d", 0.6, 0),
            ("e", 0.5, 0),
        ]
    )

    first = audit_investigation_ranking(observations, policy=_policy(review_capacity=2))
    second = audit_investigation_ranking(
        list(reversed(observations)), policy=_policy(review_capacity=2)
    )

    assert first.as_dict() == second.as_dict()
    assert first.as_dict()["boundary_tie_ids"] == ["a", "z"]
    assert isinstance(first.as_dict()["reason_codes"], list)


@pytest.mark.parametrize(
    ("observations", "code"),
    [
        ([], "INVALID_OBSERVATIONS"),
        (
            _records([("same", 0.9, 1), ("same", 0.8, 0)]),
            "DUPLICATE_ENTITY_ID",
        ),
        (_records([("a", math.nan, 1)]), "INVALID_SCORE"),
        (_records([("a", 0.8, 2)]), "INVALID_LABEL"),
    ],
)
def test_malformed_evidence_fails_closed(
    observations: list[RankingObservation], code: str
):
    with pytest.raises(RankingAuditError) as error:
        audit_investigation_ranking(observations, policy=_policy(review_capacity=1))

    assert error.value.code == code


def test_capacity_larger_than_sample_fails_closed():
    with pytest.raises(RankingAuditError) as error:
        audit_investigation_ranking(
            _records([("a", 0.9, 1)]),
            policy=_policy(review_capacity=2),
        )

    assert error.value.code == "CAPACITY_EXCEEDS_SAMPLE"


def test_invalid_policy_fails_closed():
    with pytest.raises(RankingAuditError) as error:
        audit_investigation_ranking(
            _records([("a", 0.9, 1)]),
            policy=_policy(review_capacity=0),
        )

    assert error.value.code == "INVALID_POLICY"
