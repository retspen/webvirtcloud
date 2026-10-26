"""OTP login (SingleDeviceOTPForm): a user with a confirmed TOTP device must
enter a valid code; a user without one logs in with the password alone. The
device is chosen by the server (a posted device id is ignored), so the single
token field of the login page works and no one else's device can be used."""

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts.otp import SingleDeviceOTPForm


def token_for(device, offset=0):
    return format(
        totp(device.bin_key, step=device.step, t0=device.t0, digits=device.digits, drift=offset),
        "0{}d".format(device.digits),
    )


def wrong_token(device):
    """A code that is invalid now: it differs from the tokens of the current
    step and its neighbours (which TOTP accepts within its tolerance), so the
    test never flakes on a code that happens to match."""
    valid = {token_for(device, d) for d in (-1, 0, 1)}
    return next("%06d" % i for i in range(1000000) if "%06d" % i not in valid)


class SingleDeviceOTPFormTestCase(TestCase):
    def setUp(self):
        self.User = get_user_model()
        self.user = self.User.objects.create_user("alice", password="pw-correct-horse")

    def _form(self, **extra):
        data = {"username": "alice", "password": "pw-correct-horse", **extra}
        return SingleDeviceOTPForm(RequestFactory().post("/accounts/login/"), data=data)

    def _device(self, user=None, confirmed=True):
        return TOTPDevice.objects.create(user=user or self.user, confirmed=confirmed)

    def test_user_without_device_logs_in_with_password_only(self):
        self.assertTrue(self._form(otp_token="").is_valid())

    def test_user_with_device_needs_a_token(self):
        self._device()
        form = self._form(otp_token="")
        self.assertFalse(form.is_valid())

    def test_user_with_device_valid_token(self):
        device = self._device()
        self.assertTrue(self._form(otp_token=token_for(device)).is_valid())

    def test_user_with_device_invalid_token(self):
        device = self._device()
        self.assertFalse(self._form(otp_token=wrong_token(device)).is_valid())

    def test_single_token_field_without_device_id(self):
        # the login page posts only otp_token; the form must still find the device
        device = self._device()
        form = self._form(otp_token=token_for(device))
        self.assertTrue(form.is_valid(), form.errors)

    def test_an_unconfirmed_device_does_not_require_otp(self):
        self._device(confirmed=False)
        self.assertTrue(self._form(otp_token="").is_valid())

    def test_another_users_device_is_not_used(self):
        other = self.User.objects.create_user("mallory", password="x")
        other_device = self._device(user=other)
        # alice has no device of her own: a token from mallory's device is ignored
        self.assertTrue(self._form(otp_token=token_for(other_device)).is_valid())

    def test_a_posted_device_id_is_ignored(self):
        other = self.User.objects.create_user("mallory", password="x")
        alice_device = self._device()
        other_device = self._device(user=other)
        form = self._form(otp_token=token_for(alice_device), otp_device=other_device.persistent_id)
        self.assertTrue(form.is_valid(), form.errors)

    def test_token_cannot_be_replayed(self):
        device = self._device()
        code = token_for(device)
        self.assertTrue(self._form(otp_token=code).is_valid())
        self.assertFalse(self._form(otp_token=code).is_valid())


class OTPLoginHTTPTestCase(TestCase):
    """The actual login page (OTP_ENABLED): the single token field logs an
    enrolled user in, and a user without a device needs only the password.
    Reloads the URLconf because accounts/urls.py picks the login form from
    OTP_ENABLED at import time."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import importlib
        from django.conf import settings
        from django.urls import clear_url_caches
        import accounts.urls
        import webvirtcloud.urls

        cls._otp_was_enabled = settings.OTP_ENABLED
        settings.OTP_ENABLED = True
        importlib.reload(accounts.urls)
        importlib.reload(webvirtcloud.urls)
        clear_url_caches()

    @classmethod
    def tearDownClass(cls):
        import importlib
        from django.conf import settings
        from django.urls import clear_url_caches
        import accounts.urls
        import webvirtcloud.urls

        settings.OTP_ENABLED = cls._otp_was_enabled
        importlib.reload(accounts.urls)
        importlib.reload(webvirtcloud.urls)
        clear_url_caches()
        super().tearDownClass()

    def setUp(self):
        self.user = get_user_model().objects.create_user("bob", password="pw-correct-horse")

    def _post(self, **extra):
        from django.urls import reverse
        return self.client.post(reverse("accounts:login"), {
            "username": "bob", "password": "pw-correct-horse", **extra,
        })

    def test_user_without_device_logs_in(self):
        response = self._post(otp_token="")
        self.assertEqual(response.status_code, 302)

    def test_enrolled_user_logs_in_with_only_the_token(self):
        device = TOTPDevice.objects.create(user=self.user, confirmed=True)
        response = self._post(otp_token=token_for(device))
        self.assertEqual(response.status_code, 302)

    def test_enrolled_user_wrong_token_stays(self):
        device = TOTPDevice.objects.create(user=self.user, confirmed=True)
        response = self._post(otp_token=wrong_token(device))
        self.assertEqual(response.status_code, 200)

    def messages(self):
        from logs.models import Logs
        return list(Logs.objects.order_by("id").values_list("message", flat=True))

    def test_a_wrong_otp_code_is_a_failed_login(self):
        from axes.models import AccessAttempt
        device = TOTPDevice.objects.create(user=self.user, confirmed=True)
        self._post(otp_token=wrong_token(device))
        self.assertEqual(self.messages(), ["Login failed"])
        self.assertEqual(AccessAttempt.objects.get(username="bob").failures_since_start, 1)

    def test_wrong_otp_codes_reach_the_lockout(self):
        from appsettings.models import AppSettings
        AppSettings.objects.filter(key="LOGIN_FAILURE_LIMIT").update(value="3")
        device = TOTPDevice.objects.create(user=self.user, confirmed=True)
        self._post(otp_token=wrong_token(device))
        self._post(otp_token=wrong_token(device))
        self.assertEqual(self._post(otp_token=wrong_token(device)).status_code, 429)
        self.assertEqual(self.messages(), ["Login failed", "Login failed", "Locked out", "Login failed"])

    def test_a_right_code_logs_in(self):
        device = TOTPDevice.objects.create(user=self.user, confirmed=True)
        self._post(otp_token=token_for(device))
        self.assertEqual(self.messages(), ["Login"])

    def test_an_oversized_username_is_refused_by_the_form(self):
        response = self._post(username="x" * 300, otp_token="")
        self.assertEqual(response.status_code, 200)
        self.assertIn("username", response.context["form"].errors)
        self.assertEqual(self.messages(), [])

    def test_a_signed_in_user_is_sent_on_from_the_login_page(self):
        from django.urls import reverse
        self.client.force_login(self.user)
        response = self.client.get(f"{reverse('accounts:login')}?next={reverse('computes')}")
        self.assertRedirects(response, reverse("computes"), fetch_redirect_response=False)


class OtpLoginPageTestCase(TestCase):
    def test_a_field_error_is_shown_in_the_error_box(self):
        from django.template.loader import render_to_string

        request = RequestFactory().post("/accounts/login/")
        form = SingleDeviceOTPForm(request, data={"username": "u" * 200, "password": "pw"})
        self.assertFalse(form.is_valid())
        page = render_to_string("accounts/otp_login.html", {"form": form}, request=request)
        self.assertIn(str(form.errors["username"][0]), page)
