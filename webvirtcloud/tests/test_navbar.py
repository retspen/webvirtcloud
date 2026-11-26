"""The menu on every page: the page's own section marked, the count of unfinished jobs, the languages."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from lxml import html

from operations.models import Operation


class NavbarTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.owner = users.create_user("navbar_owner", password="pw")
        self.other = users.create_user("navbar_other", password="pw")
        self.client.force_login(self.owner)

    def menu(self, url="/jobs/"):
        return html.fromstring(self.client.get(url).content).get_element_by_id("navbar")

    def job(self, user, state, key):
        Operation.objects.create(kind="test.noop", user=user, username=user.username, state=state,
                                 submission_key=key, resource="r", resource_label="c/vm")

    def test_the_pages_section_is_marked_for_eyes_and_screen_readers(self):
        current = self.menu().xpath('.//a[@aria-current="page"]')
        self.assertEqual([a.get("href") for a in current], ["/jobs/"])
        self.assertIn("active", current[0].get("class").split())

    def test_jobs_shows_how_many_of_ones_own_jobs_are_not_finished(self):
        self.job(self.owner, Operation.QUEUED, "a")
        self.job(self.owner, Operation.RUNNING, "b")
        self.job(self.owner, Operation.SUCCEEDED, "c")
        self.job(self.other, Operation.RUNNING, "d")  # another user's job is not counted for this one
        badge = self.menu().xpath('.//a[@href="/jobs/"]//span[contains(@class, "badge")]')[0]
        self.assertEqual(badge.xpath('./span[@aria-hidden="true"]')[0].text, "2")
        self.assertEqual(badge.xpath('./span[@class="visually-hidden"]')[0].text, "2 jobs not finished")

    def test_no_badge_without_unfinished_jobs(self):
        self.job(self.owner, Operation.FAILED, "a")
        self.assertEqual(self.menu().xpath('.//span[contains(@class, "badge")]'), [])

    def test_a_language_button_sets_the_language_and_comes_back_to_the_page(self):
        buttons = self.menu().xpath('.//form[@action="/i18n/setlang/"]//button[@name="language"]')
        self.assertEqual([b.get("value") for b in buttons], ["en", "tr", "zh-hans", "uk"])
        self.assertEqual([b.get("value") for b in buttons if b.get("aria-current")], ["en"])
        answer = self.client.post("/i18n/setlang/", {"language": "tr"}, HTTP_REFERER="http://testserver/jobs/")
        self.assertEqual(answer["Location"], "http://testserver/jobs/")
        self.assertEqual(self.client.cookies["django_language"].value, "tr")
