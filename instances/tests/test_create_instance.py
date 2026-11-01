"""Regression tests for the instance creation request."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from instances.api.serializers import CreateInstanceSerializer
from instances.models import Instance
from instances.utils import nic_macs
from operations.jobs import Context, Outcome, finish, get_kind
from operations.models import Operation, acquire


wvm_create = MagicMock()  # the page and the job reach the same host


def run(op):
    """The queued job, run and finished as the worker does."""
    acquire("wvc-test:1:a", "wvc-test")
    Operation.objects.filter(pk=op.pk).update(state=Operation.RUNNING, worker="wvc-test:1:a")
    op.refresh_from_db()
    result = get_kind(op.kind).run(op, Context(op, SimpleNamespace(identity="wvc-test:1:a")))
    finish(op, Outcome(Operation.SUCCEEDED, result=result))


@patch("instances.jobs.wvmCreate", new=wvm_create)
class CreateInstanceViewTests(TestCase):
    @patch("instances.views.wvmCreate", new=wvm_create)
    @patch("instances.views.NewVMForm")
    def test_successful_create_redirects_to_the_compute_instances_with_a_queued_job(self, form_class):
        response, conn = self.create(form_class)

        self.assertRedirects(
            response, reverse("instances", args=[Compute.objects.get().id]),
            fetch_redirect_response=False,
        )
        op = Operation.objects.get()
        self.assertEqual((op.kind, op.state), ("instance.create", Operation.QUEUED))
        conn.create_instance.assert_not_called()
        run(op)
        conn.create_instance.assert_called_once()
        self.assertEqual(conn.create_instance.call_args.kwargs["volumes"][0]["bus"], "virtio")
        self.assertTrue(Instance.objects.filter(name="new-vm").exists())

    @patch("instances.views.wvmCreate", new=wvm_create)
    @patch("instances.views.NewVMForm")
    def test_secure_boot_and_a_tpm_reach_the_definition(self, form_class):
        _, conn = self.create(form_class, firmware="UEFI Secure Boot", tpm=True)
        run(Operation.objects.get())
        kwargs = conn.create_instance.call_args.kwargs
        self.assertEqual((kwargs["firmware"], kwargs["machine"], kwargs["tpm_model"]),
                         ("UEFI Secure Boot", "q35", "tpm-crb"))

    @patch("instances.views.wvmCreate", new=wvm_create)
    @patch("instances.views.NewVMForm")
    def test_a_firmware_or_a_tpm_the_host_does_not_offer_is_refused(self, form_class):
        for data, host in (({"firmware": "UEFI Secure Boot"}, {"get_firmwares": ["BIOS", "UEFI"]}),
                           ({"tpm": True}, {"get_tpm_model": None})):
            with self.subTest(data):
                Instance.objects.all().delete()
                response, conn = self.create(form_class, host=host, **data)
                self.assertEqual(response.status_code, 200)
                self.assertFalse(Operation.objects.exists())
                conn.create_instance.assert_not_called()

    @patch("instances.views.wvmCreate", new=wvm_create)
    @patch("instances.views.NewVMForm")
    def test_invalid_devices_are_refused_before_anything_is_created(self, form_class):
        for data in (
            {"add_cdrom": "virtio"},  # no ejectable media
            {"add_cdrom": "fdc"},
            {"add_cdrom": "usb"},  # libvirt refuses an empty usb disk
            {"mac": "52:54:00:00:00:01,52:54:00:00:00:02"},  # one network
            {"mac": "52:54:00:00:00:01'/><evil/>"},
        ):
            with self.subTest(data):
                Instance.objects.all().delete()
                response, conn = self.create(form_class, **data)
                self.assertEqual(response.status_code, 200)
                self.assertFalse(Operation.objects.exists())
                conn.create_volume.assert_not_called()
                conn.create_instance.assert_not_called()

    def create(self, form_class, host=None, **data):
        """POST the create form with data over the form's defaults; host: what
        the mocked host answers, over its defaults."""
        user = get_user_model().objects.filter(username="create-test-admin").first() or (
            get_user_model().objects.create_superuser(
                username="create-test-admin", password="password", email="create@example.com"
            )
        )
        self.client.force_login(user)
        compute, _ = Compute.objects.get_or_create(
            name="create-test-compute", hostname="localhost", type=4,
            login="", password="",
        )
        wvm_create.reset_mock()
        conn = wvm_create.return_value
        conn.get_instances.return_value = []
        conn.get_video_models.return_value = ["vga"]
        conn.get_cache_modes.return_value = {"default": "Default"}
        conn.get_disk_device_types.return_value = ["disk"]
        conn.get_disk_bus_types.return_value = ["fdc", "virtio", "sata"]
        conn.get_networks.return_value = ["default"]
        conn.get_nwfilters.return_value = []
        conn.get_network_models.return_value = ["virtio"]
        conn.get_storages.return_value = ["default"]
        conn.get_dom_capabilities.return_value = {"loader_enums": [], "loaders": [], "cpu_modes": ["host-model"]}
        conn.get_capabilities.return_value = {}
        conn.get_firmwares.return_value = ["BIOS", "UEFI", "UEFI Secure Boot"]
        conn.get_tpm_model.return_value = "tpm-crb"
        for method, value in (host or {}).items():
            getattr(conn, method).return_value = value
        conn.get_volume_path.return_value = "/var/lib/libvirt/images/base.qcow2"
        conn.get_volume_format_type.return_value = "qcow2"

        form = form_class.return_value
        form.is_valid.return_value = True
        form.cleaned_data = {
            "name": "new-vm", "meta_prealloc": False, "hdd_size": 0,
            "template": "", "images": "base.qcow2", "cache_mode": "default",
            "firmware": "BIOS", "net_model": "virtio", "memory": 1024,
            "vcpu": 1, "vcpu_mode": "host-model", "networks": "default",
            "virtio": True, "listener_addr": "0.0.0.0", "nwfilter": "",
            "graphics": "vnc", "video": "vga",
            "mac": "52:54:00:00:00:01", "qemu_ga": False,
            "add_cdrom": "sata", "add_input": "default", "tpm": False,
            **data,
        }

        response = self.client.post(
            reverse("instances:create_instance", args=[compute.id, "x86_64", "q35"]),
            {"create": "1", "device0": "disk", "bus0": "virtio", "submission_key": "key-create01"},
        )
        return response, conn

    @patch("instances.views.wvmCreate")
    def test_firmware_list_uses_the_chosen_machine_type(self, connection_class):
        user = get_user_model().objects.create_superuser(
            username="create-fw-admin", password="password", email="fw@example.com"
        )
        self.client.force_login(user)
        compute = Compute.objects.create(
            name="create-fw-compute", hostname="localhost", type=4, login="", password="",
        )
        conn = connection_class.return_value
        conn.get_instances.return_value = []
        conn.get_storages.return_value = []
        conn.get_networks.return_value = []
        conn.get_nwfilters.return_value = []
        conn.get_cache_modes.return_value = {}
        # A host without loader support has no "loaders"/"loader_enums" keys
        conn.get_dom_capabilities.return_value = {"loader_support": "no", "cpu_modes": ["host-model"]}
        conn.get_capabilities.return_value = {}
        conn.get_firmwares.return_value = ["BIOS"]
        conn.get_tpm_model.return_value = None

        response = self.client.get(reverse("instances:create_instance", args=[compute.id, "x86_64", "q35"]))

        self.assertEqual(response.status_code, 200)
        conn.get_firmwares.assert_called_once_with("x86_64", "q35")


class NicMacsTestCase(TestCase):
    def test_macs_follow_the_networks(self):
        self.assertEqual(nic_macs("52:54:00:00:00:01", "a,b"), ["52:54:00:00:00:01"])
        self.assertEqual(nic_macs("", "a,b"), [])

    def test_invalid_or_extra_macs_are_refused(self):
        for mac, networks in (("52:54:00:00:00:01,52:54:00:00:00:02", "a"), ("not-a-mac", "a")):
            with self.subTest(mac=mac), self.assertRaises(ValueError):
                nic_macs(mac, networks)

    def test_api_serializer_takes_a_mac_per_network(self):
        def serializer(networks):
            return CreateInstanceSerializer(data={
                "name": "api-vm", "vcpu": 1, "vcpu_mode": "host-model", "memory": 512,
                "networks": networks, "mac": "52:54:00:00:00:01,52:54:00:00:00:02", "nwfilter": "",
                "storage": "default", "hdd_size": 1, "cache_mode": "none", "meta_prealloc": False,
                "virtio": True, "qemu_ga": True, "video": "vga", "listener_addr": "0.0.0.0",
                "submission_key": "test-key",
            })
        two_nics = serializer("default,second")
        self.assertTrue(two_nics.is_valid(), two_nics.errors)
        extra = serializer("default")
        self.assertFalse(extra.is_valid())
        self.assertEqual(extra.errors["mac"], ["More MAC addresses than networks"])
