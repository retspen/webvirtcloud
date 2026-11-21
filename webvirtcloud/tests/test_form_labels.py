"""The fields a page shows with their form's label (bootstrap_field, the
error lists of the VM create form and of the interface, network and pool
dialogs) have a translated label: without one Django makes
an English one from the field's name."""

from accounts.forms import UserInstanceForm
from admin.forms import UserCreateForm
from computes.forms import SocketComputeForm, SshComputeForm, TcpComputeForm, TlsComputeForm
from django import forms
from django.test import SimpleTestCase
from django.utils import translation
from instances.forms import NewVMForm
from interfaces.forms import AddInterface
from networks.forms import AddNetPool
from storages.forms import AddStgPool, CreateVolumeForm


class FormLabelTests(SimpleTestCase):
    def test_shown_fields_have_a_translated_label(self):
        for form in (NewVMForm, TcpComputeForm, TlsComputeForm, SshComputeForm, SocketComputeForm, UserCreateForm,
                     CreateVolumeForm, UserInstanceForm, AddInterface, AddNetPool, AddStgPool):
            for name, field in form.base_fields.items():
                if isinstance(field.widget, forms.HiddenInput):
                    continue
                with self.subTest(form=form.__name__, field=name):
                    self.assertIsNotNone(field.label)

    def test_a_label_is_in_turkish(self):
        with translation.override("tr"):
            self.assertEqual(str(TcpComputeForm.base_fields["hostname"].label), "FQDN/IP")
            self.assertEqual(str(CreateVolumeForm.base_fields["name"].label), "Ad")
            self.assertEqual(str(NewVMForm.base_fields["hdd_size"].label), "Boyut (GiB)")
