from __future__ import annotations

from django.utils import timezone

from jobs.models import JobLog, JobRun
from jobs.services import log_step
from pipeline.audit import log_criterion_event
from pipeline.models import CriterionEntry, ValidCriterionTemplate, normalize_criterion_name
from pipeline.services import CriterionNormalizationError, evaluate_criterion_text_with_ai


def _log(job_run: JobRun, level: str, message: str, context: dict | None = None) -> None:
    log_step(job_run=job_run, level=level, message=message, context=context)


def _select_entries_for_teacher(teacher_name: str) -> list[CriterionEntry]:
    return list(
        CriterionEntry.objects.filter(
            teacher_name=teacher_name,
            needs_recheck=True,
            validation_status__in=(
                CriterionEntry.ValidationStatus.INVALID,
                CriterionEntry.ValidationStatus.RECHECK,
            ),
        ).order_by("class_code", "subject_name", "module_number", "criterion_text")
    )


def _apply_whitelist_if_matches(entry: CriterionEntry, active_templates: set[str]) -> bool:
    normalized_name = normalize_criterion_name(entry.criterion_text)
    if normalized_name not in active_templates:
        return False

    now = timezone.now()
    entry.criterion_text_ai = entry.criterion_text
    entry.validation_status = CriterionEntry.ValidationStatus.OVERRIDE
    entry.ai_verdict = "override"
    entry.ai_why = "Validated by whitelist template during teacher recheck."
    entry.ai_fix_suggestion = ""
    entry.ai_variants_json = [entry.criterion_text]
    entry.needs_recheck = False
    entry.last_checked_at = now
    entry.save(
        update_fields=[
            "criterion_text_ai",
            "validation_status",
            "ai_verdict",
            "ai_why",
            "ai_fix_suggestion",
            "ai_variants_json",
            "needs_recheck",
            "last_checked_at",
            "updated_at",
        ]
    )
    log_criterion_event(
        entry,
        event_type="recheck",
        actor_name="AI Recheck",
        actor_role="system",
        reason="Validated by whitelist template during teacher recheck.",
        payload={"result": "override"},
    )
    return True


def run_teacher_recheck_for_job(job_run: JobRun, *, teacher_name: str) -> dict:
    entries = _select_entries_for_teacher(teacher_name)
    if not entries:
        summary = {
            "teacher": teacher_name,
            "checked": 0,
            "became_valid": 0,
            "still_invalid": 0,
            "failed": 0,
        }
        _log(job_run, JobLog.Level.INFO, "Teacher recheck skipped: no matching criteria", summary)
        return summary

    active_templates = set(
        ValidCriterionTemplate.objects.filter(is_active=True).values_list("normalized_name", flat=True)
    )

    became_valid = 0
    still_invalid = 0
    failed = 0

    for entry in entries:
        if _apply_whitelist_if_matches(entry, active_templates):
            became_valid += 1
            continue

        try:
            ai_result = evaluate_criterion_text_with_ai(entry.criterion_text)
            verdict = str(ai_result.get("verdict", "")).strip().lower()
            ai_variants = ai_result.get("variants") or []
            ai_text = str(ai_variants[0]).strip() if ai_variants else ""

            entry.criterion_text_ai = ai_text
            entry.ai_verdict = verdict
            entry.ai_why = str(ai_result.get("why", "")).strip()
            entry.ai_fix_suggestion = str(ai_result.get("fix", "")).strip()
            entry.ai_variants_json = ai_variants
            entry.last_checked_at = timezone.now()

            if verdict == "valid":
                entry.validation_status = CriterionEntry.ValidationStatus.VALID
                entry.needs_recheck = False
                became_valid += 1
            elif verdict == "partial":
                entry.validation_status = CriterionEntry.ValidationStatus.RECHECK
                entry.needs_recheck = True
                still_invalid += 1
            else:
                entry.validation_status = CriterionEntry.ValidationStatus.INVALID
                entry.needs_recheck = True
                still_invalid += 1

            entry.save(
                update_fields=[
                    "criterion_text_ai",
                    "validation_status",
                    "ai_verdict",
                    "ai_why",
                    "ai_fix_suggestion",
                    "ai_variants_json",
                    "needs_recheck",
                    "last_checked_at",
                    "updated_at",
                ]
            )
            log_criterion_event(
                entry,
                event_type="recheck",
                actor_name="AI Recheck",
                actor_role="system",
                reason=entry.ai_why,
                payload={
                    "ai_verdict": entry.ai_verdict,
                    "validation_status": entry.validation_status,
                    "needs_recheck": entry.needs_recheck,
                    "job_run_id": str(job_run.id),
                },
            )
        except CriterionNormalizationError:
            failed += 1
            entry.validation_status = CriterionEntry.ValidationStatus.RECHECK
            entry.ai_verdict = "failed"
            entry.ai_why = "AI response format is invalid or request failed during teacher recheck."
            entry.ai_fix_suggestion = "Проверьте критерий вручную и отправьте подтверждение снова."
            entry.needs_recheck = True
            entry.last_checked_at = timezone.now()
            entry.save(
                update_fields=[
                    "validation_status",
                    "ai_verdict",
                    "ai_why",
                    "ai_fix_suggestion",
                    "needs_recheck",
                    "last_checked_at",
                    "updated_at",
                ]
            )
            log_criterion_event(
                entry,
                event_type="recheck",
                actor_name="AI Recheck",
                actor_role="system",
                reason=entry.ai_why,
                payload={
                    "ai_verdict": entry.ai_verdict,
                    "validation_status": entry.validation_status,
                    "needs_recheck": entry.needs_recheck,
                    "job_run_id": str(job_run.id),
                },
            )

    summary = {
        "teacher": teacher_name,
        "checked": len(entries),
        "became_valid": became_valid,
        "still_invalid": still_invalid,
        "failed": failed,
    }
    _log(job_run, JobLog.Level.INFO, "Teacher recheck finished", summary)
    return summary


def run_teacher_recheck_job(*, source_job_run: JobRun, teacher_name: str, initiated_by=None) -> JobRun:
    recheck_job = JobRun.objects.create(
        job_type="teacher_criteria_recheck",
        status=JobRun.Status.RUNNING,
        started_at=timezone.now(),
        initiated_by=initiated_by,
        params_json={
            "source_job_run_id": str(source_job_run.id),
            "teacher_name": teacher_name,
        },
        result_json={},
    )

    _log(
        recheck_job,
        JobLog.Level.INFO,
        "Teacher recheck started",
        {"source_job_run_id": str(source_job_run.id), "teacher": teacher_name},
    )

    try:
        summary = run_teacher_recheck_for_job(recheck_job, teacher_name=teacher_name)
        recheck_job.result_json = {
            "source_job_run_id": str(source_job_run.id),
            "teacher": teacher_name,
            "summary": summary,
        }
        recheck_job.status = JobRun.Status.PARTIAL if summary.get("failed", 0) > 0 else JobRun.Status.SUCCESS
    except Exception as exc:
        _log(
            recheck_job,
            JobLog.Level.ERROR,
            f"Teacher recheck failed: {exc}",
            {"source_job_run_id": str(source_job_run.id), "teacher": teacher_name},
        )
        recheck_job.status = JobRun.Status.FAILED
        recheck_job.result_json = {
            "source_job_run_id": str(source_job_run.id),
            "teacher": teacher_name,
            "error": str(exc),
        }
    finally:
        recheck_job.finished_at = timezone.now()
        recheck_job.save(update_fields=["status", "result_json", "finished_at"])

    return recheck_job