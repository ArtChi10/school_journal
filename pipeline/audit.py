from __future__ import annotations

from pipeline.models import CriterionEntry, CriterionReviewEvent


def log_criterion_event(
    criterion: CriterionEntry,
    *,
    event_type: str,
    actor_name: str = "",
    actor_role: str = "",
    reason: str = "",
    payload: dict | None = None,
) -> CriterionReviewEvent:
    return CriterionReviewEvent.objects.create(
        criterion=criterion,
        event_type=event_type,
        actor_name=actor_name,
        actor_role=actor_role,
        reason=reason,
        payload_json=payload or {},
    )