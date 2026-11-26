from unittest import mock

import libvirt
from django.test import TestCase

from appsettings.models import AppSettings
from computes.models import Compute
from instances import jobs
from instances.models import Instance
from operations.models import Alert
from operations.utils import words

PAUSED_IOERROR = (libvirt.VIR_DOMAIN_PAUSED, libvirt.VIR_DOMAIN_PAUSED_IOERROR)
RUNNING = (libvirt.VIR_DOMAIN_RUNNING, libvirt.VIR_DOMAIN_RUNNING_BOOTED)
PAUSED_BY_USER = (libvirt.VIR_DOMAIN_PAUSED, libvirt.VIR_DOMAIN_PAUSED_USER)


class FaultAlertTests(TestCase):
    def setUp(self):
        AppSettings.objects.update_or_create(key="ALERT_WEBHOOK", defaults={"name": "Alert webhook",
                                                                             "value": "http://192.0.2.9/hook"})
        self.compute = Compute.objects.create(name="h1", hostname="192.0.2.71", login="u", password="p", type=1)
        self.vm = Instance.objects.create(compute=self.compute, name="vm1", uuid="71717171-0000-4000-8000-000000000001")

    def watch(self, state):
        """One pass with the host's VM in state (state, reason), or the host not answering (None)."""
        answer = None if state is None else {self.vm.uuid: ["vm1", *state]}
        with mock.patch.object(jobs.utils, "host_domain_states", return_value={self.compute.pk: answer}):
            jobs.watch_faults()
        self.vm.refresh_from_db()

    def test_a_fault_is_alerted_once_and_again_after_the_vm_recovers(self):
        self.watch(PAUSED_IOERROR)
        self.assertEqual([(words(a.subject), words(a.text)) for a in Alert.objects.all()],
                         [("VM fault: vm1", "vm1 on h1: Paused by a disk error")])
        self.watch(PAUSED_IOERROR)
        self.watch(None)  # a host that does not answer changes nothing
        self.assertEqual(Alert.objects.count(), 1)
        self.watch(RUNNING)
        self.assertEqual(self.vm.fault, "")
        self.watch(PAUSED_IOERROR)
        self.assertEqual(Alert.objects.count(), 2)

    def test_no_alert_for_an_ordinary_state_nor_without_a_channel(self):
        self.watch(PAUSED_BY_USER)
        self.assertFalse(Alert.objects.exists())
        AppSettings.objects.filter(key="ALERT_WEBHOOK").update(value="")
        with mock.patch.object(jobs.utils, "host_domain_states") as read:
            jobs.watch_faults()
        read.assert_not_called()  # no host is read for nobody

    def test_a_fault_is_told_again_after_the_channels_were_off(self):
        self.watch(PAUSED_IOERROR)
        AppSettings.objects.filter(key="ALERT_WEBHOOK").update(value="")
        self.watch(PAUSED_IOERROR)
        self.assertEqual(self.vm.fault, "")  # nobody heard of what happens meanwhile
        AppSettings.objects.filter(key="ALERT_WEBHOOK").update(value="http://192.0.2.9/hook")
        self.watch(PAUSED_IOERROR)
        self.assertEqual(Alert.objects.count(), 2)
