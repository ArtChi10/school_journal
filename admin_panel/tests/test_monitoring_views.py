from django.test import TestCase, override_settings


class MonitoringViewsTests(TestCase):
    def test_healthz_returns_ok(self):
        response = self.client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {"status": "ok"})

    @override_settings(DJANGO_SECRET_KEY="from-settings")
    def test_readyz_returns_ok_when_checks_pass(self):
        response = self.client.get("/readyz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertEqual(response.json()["checks"]["db"], "ok")
        self.assertEqual(response.json()["checks"]["env"], "ok")