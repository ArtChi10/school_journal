from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from jobs.models import JobRun

GROUP_LABELS = {
    "descriptor": "дескриптор",
    "criteria": "критерии",
    "grades": "оценки",
}


def _safe_text(value: object) -> str:
    return str(value or "").strip()


def _iter_issues(job_run: JobRun) -> list[dict]:
    payload = (job_run.result_json or {}).get("issues", [])
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def build_missing_data_summary(job_run: JobRun) -> dict:
    issues = _iter_issues(job_run)
    normalized: list[dict] = []
    subjects = set()
    teachers = set()
    counts = {"descriptor": 0, "criteria": 0, "grades": 0}

    for issue in issues:
        teacher_name = _safe_text(issue.get("teacher_name")) or "UNKNOWN"
        class_code = _safe_text(issue.get("class_code")) or "UNKNOWN"
        subject_name = _safe_text(issue.get("subject_name")) or "UNKNOWN"
        issue_group = _safe_text(issue.get("issue_group"))
        code = _safe_text(issue.get("code"))
        if not issue_group:
            if code == "DESCRIPTOR_EMPTY":
                issue_group = "descriptor"
            elif code == "CRITERIA_HEADERS_EMPTY":
                issue_group = "criteria"
            elif code == "GRADE_EMPTY":
                issue_group = "grades"
        if issue_group not in counts:
            continue

        missing_count = issue.get("missing_count") or 1
        try:
            missing_count = max(1, int(missing_count))
        except (TypeError, ValueError):
            missing_count = 1

        item = {
            "teacher_name": teacher_name,
            "class_code": class_code,
            "subject_name": subject_name,
            "issue_group": issue_group,
            "missing_count": missing_count,
        }
        normalized.append(item)
        teachers.add(teacher_name)
        subjects.add((class_code, subject_name))
        counts[issue_group] += missing_count

    by_teacher_subject: dict[tuple[str, str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for item in normalized:
        key = (item["teacher_name"], item["class_code"], item["subject_name"])
        by_teacher_subject[key][item["issue_group"]] += item["missing_count"]

    teacher_details: dict[str, list[dict]] = defaultdict(list)
    for (teacher, class_code, subject), grouped in sorted(by_teacher_subject.items()):
        teacher_details[teacher].append(
            {
                "class_code": class_code,
                "subject_name": subject,
                "groups": dict(grouped),
            }
        )

    summary = {
        "teachers_total": len(teachers),
        "subjects_total": len(subjects),
        "descriptor_missing_total": counts["descriptor"],
        "criteria_missing_total": counts["criteria"],
        "grades_missing_total": counts["grades"],
        "teachers": [
            {
                "teacher_name": teacher,
                "items": teacher_details[teacher],
            }
            for teacher in sorted(teacher_details)
        ],
    }

    summary["text"] = _build_summary_text(job_run, summary)
    return summary


def _build_summary_text(job_run: JobRun, summary: dict) -> str:
    if summary["teachers_total"] == 0:
        return f"Проверка незаполненности (job={job_run.id})\nВсё заполнено ✅"

    lines = [
        f"Проверка незаполненности (job={job_run.id})",
        (
            "Итого: учителей с проблемами — "
            f"{summary['teachers_total']}, предметов — {summary['subjects_total']}"
        ),
        (
            "Пустые поля: "
            f"дескриптор={summary['descriptor_missing_total']}, "
            f"критерии={summary['criteria_missing_total']}, "
            f"оценки={summary['grades_missing_total']}"
        ),
        "",
    ]

    index = 1
    for teacher in summary["teachers"]:
        lines.append(f"{index}) {teacher['teacher_name']}")
        for item in teacher["items"]:
            groups = []
            for key in ("descriptor", "criteria", "grades"):
                count = item["groups"].get(key, 0)
                if count > 0:
                    label = GROUP_LABELS[key]
                    groups.append(f"{label} ({count})")
            lines.append(
                f"   • {item['class_code']} / {item['subject_name']}: не заполнены " + ", ".join(groups)
            )
        index += 1

    return "\n".join(lines)


def split_summary_for_telegram(text: str, chunk_size: int = 3500) -> list[str]:
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in text.splitlines():
        projected = current_len + len(line) + 1
        if current and projected > chunk_size:
            chunks.append("\n".join(current))
            current = [line]
            current_len = len(line) + 1
        else:
            current.append(line)
            current_len = projected

    if current:
        chunks.append("\n".join(current))
    return chunks