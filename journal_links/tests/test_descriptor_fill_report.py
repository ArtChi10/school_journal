from datetime import timedelta

from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from jobs.models import JobRun
from validation.descriptor_criteria_fill import JOB_TYPE


class DescriptorFillReportViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="reporter", password="p", is_staff=True)
        content_type = ContentType.objects.get_for_model(JobRun)
        self.user.user_permissions.add(Permission.objects.get(codename="view_jobrun", content_type=content_type))
        self.client.force_login(self.user)
        self.url = reverse("journal_links:descriptor_criteria_fill_report")
        self.csv_url = reverse("journal_links:descriptor_criteria_fill_report_csv")
        self.sheet_url = "https://docs.google.com/spreadsheets/d/report-source/edit#gid=10"

    def _create_run(self, *, started_at=None, status=JobRun.Status.SUCCESS, trigger="scheduled", rows=None):
        rows = rows if rows is not None else self._problem_rows()
        return JobRun.objects.create(
            job_type=JOB_TYPE,
            status=status,
            started_at=started_at or timezone.now(),
            finished_at=(started_at or timezone.now()) + timedelta(minutes=2),
            params_json={"trigger": trigger},
            result_json={
                "summary": {
                    "classes_checked": 3,
                    "subjects_checked": len(rows),
                    "fully_filled": 1,
                    "with_problems": 3,
                },
                "rows": rows,
                "tables": [],
            },
        )

    def _problem_rows(self):
        return [
            {
                "teacher_name": "Teacher A",
                "class_code": "7A",
                "subject_name": "Math",
                "module_number": 1,
                "descriptor_status": "missing",
                "criteria_status": "filled",
                "criteria_missing": 0,
                "criteria_total": 2,
                "grades_status": "ok",
                "grades_missing": 0,
                "grades_ratio": "4/4",
                "overall_status": "problem",
                "sheet_url": self.sheet_url,
            },
            {
                "teacher_name": "Teacher B",
                "class_code": "7B",
                "subject_name": "Science",
                "module_number": 2,
                "descriptor_status": "filled",
                "criteria_status": "missing",
                "criteria_missing": 1,
                "criteria_total": 3,
                "grades_status": "ok",
                "grades_missing": 0,
                "grades_ratio": "6/6",
                "overall_status": "problem",
                "sheet_url": self.sheet_url,
            },
            {
                "teacher_name": "Teacher A",
                "class_code": "7A",
                "subject_name": "English",
                "module_number": 3,
                "descriptor_status": "filled",
                "criteria_status": "filled",
                "criteria_missing": 0,
                "criteria_total": 2,
                "grades_status": "missing",
                "grades_missing": 2,
                "grades_ratio": "2/4",
                "overall_status": "problem",
                "sheet_url": self.sheet_url,
            },
            {
                "teacher_name": "Teacher C",
                "class_code": "7C",
                "subject_name": "Art",
                "module_number": 4,
                "descriptor_status": "filled",
                "criteria_status": "filled",
                "criteria_missing": 0,
                "criteria_total": 0,
                "grades_status": "not_applicable",
                "grades_missing": 0,
                "grades_ratio": "—",
                "overall_status": "ok",
                "sheet_url": self.sheet_url,
            },
        ]

    def test_report_opens_for_staff_with_jobrun_permission(self):
        self._create_run()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Отчет по заполненности")

    def test_report_forbidden_without_permission(self):
        user = User.objects.create_user(username="limited", password="p", is_staff=True)
        self.client.force_login(user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_empty_state_when_no_jobruns_exist(self):
        response = self.client.get(self.url)

        self.assertContains(response, "Проверки еще не запускались")

    def test_latest_jobrun_is_default(self):
        self._create_run(
            started_at=timezone.now() - timedelta(hours=2),
            rows=[{**self._problem_rows()[0], "teacher_name": "Old Teacher", "subject_name": "Old Math"}],
        )
        self._create_run(
            started_at=timezone.now(),
            rows=[{**self._problem_rows()[0], "teacher_name": "Latest Teacher", "subject_name": "Latest Math"}],
        )

        response = self.client.get(self.url)

        self.assertContains(response, "Latest Teacher")
        self.assertNotContains(response, "Old Math")

    def test_specific_jobrun_can_be_selected(self):
        older = self._create_run(
            started_at=timezone.now() - timedelta(hours=2),
            rows=[{**self._problem_rows()[0], "teacher_name": "Selected Teacher", "subject_name": "Selected Math"}],
        )
        self._create_run(
            started_at=timezone.now(),
            rows=[{**self._problem_rows()[0], "teacher_name": "Latest Teacher", "subject_name": "Latest Math"}],
        )

        response = self.client.get(self.url, {"run_id": str(older.id)})

        self.assertContains(response, "Selected Teacher")
        self.assertNotContains(response, "Latest Math")

    def test_problem_rows_go_to_expected_sections(self):
        self._create_run()

        response = self.client.get(self.url)

        self.assertContains(response, "Не заполнены дескрипторы")
        self.assertContains(response, "Math")
        self.assertContains(response, "Не заполнены критерии")
        self.assertContains(response, "Science")
        self.assertContains(response, "Не проставлены оценки")
        self.assertContains(response, "English")

    def test_not_applicable_grades_are_not_problem(self):
        self._create_run()

        response = self.client.get(self.url)

        self.assertNotContains(response, "Art")

    def test_filters_apply_without_running_new_check(self):
        job_run = self._create_run()

        response = self.client.get(
            self.url,
            {
                "run_id": str(job_run.id),
                "class_code": "7A",
                "teacher": "Teacher A",
                "problem_type": "grades",
            },
        )

        self.assertContains(response, "English")
        self.assertNotContains(response, "Math")
        self.assertEqual(JobRun.objects.filter(job_type=JOB_TYPE).count(), 1)

    def test_teacher_grouping_counts_and_sorts_by_total_problems(self):
        self._create_run()

        response = self.client.get(self.url)
        content = response.content.decode()
        teacher_section = content.split("По учителям", 1)[1].split("Не заполнены дескрипторы", 1)[0]

        self.assertLess(teacher_section.index("Teacher A"), teacher_section.index("Teacher B"))
        self.assertRegex(
            teacher_section,
            r"<td>Teacher A</td>\s*<td>1</td>\s*<td>0</td>\s*<td>1</td>\s*<td class=\"fw-semibold\">2</td>",
        )
        self.assertRegex(
            teacher_section,
            r"<td>Teacher B</td>\s*<td>0</td>\s*<td>1</td>\s*<td>0</td>\s*<td class=\"fw-semibold\">1</td>",
        )

    def test_sheet_links_are_open_text_not_visible_raw_url(self):
        self._create_run()

        response = self.client.get(self.url)

        self.assertContains(response, ">Открыть</a>")
        self.assertNotContains(response, f">{self.sheet_url}</a>")

    def test_partial_run_shows_warning_and_available_rows(self):
        self._create_run(status=JobRun.Status.PARTIAL)

        response = self.client.get(self.url)

        self.assertContains(response, "доступные данные из JobRun")
        self.assertContains(response, "Math")

    def test_csv_export_uses_current_filters(self):
        job_run = self._create_run()

        response = self.client.get(
            self.csv_url,
            {"run_id": str(job_run.id), "problem_type": "grades"},
        )
        content = response.content.decode("utf-8-sig")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Тип проблемы,Учитель,Класс,Предмет,Модуль", content)
        self.assertIn("Оценки,Teacher A,7A,English,3", content)
        self.assertNotIn("Дескриптор,Teacher A,7A,Math", content)
