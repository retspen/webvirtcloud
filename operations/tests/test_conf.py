from django.test import TestCase

from appsettings.models import AppSettings
from operations import utils


class ConfTestCase(TestCase):
    def test_defaults_and_bounds(self):
        self.assertEqual((utils.concurrency(), utils.retention_days()), (4, 30))
        AppSettings.objects.filter(key="WORKER_CONCURRENCY").update(value="99")
        self.assertEqual(utils.concurrency(), 4)
        AppSettings.objects.filter(key="WORKER_CONCURRENCY").update(value="8")
        self.assertEqual(utils.concurrency(), 8)
