from pathlib import Path
from unittest.mock import ANY, patch

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse

from admin_panel.google_oauth import (
    GOOGLE_OAUTH_CODE_VERIFIER_SESSION_KEY,
    GOOGLE_OAUTH_NEXT_SESSION_KEY,
    GOOGLE_OAUTH_STATE_SESSION_KEY,
)


class GoogleOAuthViewsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="u", password="p")

    def _grant(self, codename: str):
        self.user.user_permissions.add(Permission.objects.get(codename=codename))

    def test_start_google_oauth_requires_change_permission(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse("journal_links:start_google_oauth"))

        self.assertEqual(response.status_code, 403)
        self.assertIn("нельзя подключать Google OAuth", response.content.decode("utf-8"))

    @patch(
        "journal_links.views.build_google_authorization_url",
        return_value=("https://accounts.google.com/auth", "s1", "verifier1"),
    )
    def test_start_google_oauth_redirects_to_google_and_stores_state(self, mocked_builder):
        self._grant("change_classsheetlink")
        self.client.force_login(self.user)

        response = self.client.post(reverse("journal_links:start_google_oauth"), {"next": "/links/"})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "https://accounts.google.com/auth")
        self.assertEqual(self.client.session[GOOGLE_OAUTH_STATE_SESSION_KEY], "s1")
        self.assertEqual(self.client.session[GOOGLE_OAUTH_CODE_VERIFIER_SESSION_KEY], "verifier1")
        self.assertEqual(self.client.session[GOOGLE_OAUTH_NEXT_SESSION_KEY], "/links/")
        mocked_builder.assert_called_once_with(ANY)

    @patch("journal_links.views.complete_google_oauth", return_value=Path("creds/google/token.json"))
    def test_google_oauth_callback_saves_token_and_clears_session(self, mocked_complete):
        self._grant("change_classsheetlink")
        self.client.force_login(self.user)
        session = self.client.session
        session[GOOGLE_OAUTH_STATE_SESSION_KEY] = "s1"
        session[GOOGLE_OAUTH_CODE_VERIFIER_SESSION_KEY] = "verifier1"
        session[GOOGLE_OAUTH_NEXT_SESSION_KEY] = "/links/"
        session.save()

        response = self.client.get(reverse("journal_links:google_oauth_callback"), {"state": "s1", "code": "abc"})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/links/")
        self.assertNotIn(GOOGLE_OAUTH_STATE_SESSION_KEY, self.client.session)
        self.assertNotIn(GOOGLE_OAUTH_CODE_VERIFIER_SESSION_KEY, self.client.session)
        self.assertNotIn(GOOGLE_OAUTH_NEXT_SESSION_KEY, self.client.session)
        mocked_complete.assert_called_once_with(ANY, state="s1", code_verifier="verifier1")

    @patch("journal_links.views.complete_google_oauth")
    def test_google_oauth_callback_rejects_invalid_state(self, mocked_complete):
        self._grant("change_classsheetlink")
        self.client.force_login(self.user)
        session = self.client.session
        session[GOOGLE_OAUTH_STATE_SESSION_KEY] = "expected"
        session[GOOGLE_OAUTH_CODE_VERIFIER_SESSION_KEY] = "verifier1"
        session[GOOGLE_OAUTH_NEXT_SESSION_KEY] = "/links/"
        session.save()

        response = self.client.get(reverse("journal_links:google_oauth_callback"), {"state": "wrong", "code": "abc"})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/links/")
        self.assertNotIn(GOOGLE_OAUTH_STATE_SESSION_KEY, self.client.session)
        self.assertNotIn(GOOGLE_OAUTH_CODE_VERIFIER_SESSION_KEY, self.client.session)
        self.assertNotIn(GOOGLE_OAUTH_NEXT_SESSION_KEY, self.client.session)
        mocked_complete.assert_not_called()
