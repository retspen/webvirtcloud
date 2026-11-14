from django.test import SimpleTestCase

from operations import utils


class RedactTestCase(SimpleTestCase):
    def test_credentials_in_text_are_hidden(self):
        text = ("Cannot connect to qemu+tcp://admin:s3cret@192.0.2.5/system: "
                "<graphics passwd='vncpw'/> password=hunter2 auth_password: abc console_pass=cp1 "
                'password="quoted1" token: \'quoted2\' <passphrase>pp</passphrase>')
        safe = utils.safe_text(text)
        for secret in ("s3cret", "vncpw", "hunter2", "abc", "quoted1", "quoted2", "pp<", "cp1"):
            self.assertNotIn(secret, safe)
        self.assertIn("192.0.2.5", safe)

    def test_structured_and_multiline_secrets_are_hidden(self):
        safe = utils.safe_text('{"password": "hunter2", \'token\': \'t0k\'} password="line1\nline2"')
        for secret in ("hunter2", "t0k", "line1", "line2"):
            self.assertNotIn(secret, safe)

    def test_escaped_quotes_and_nested_markup_are_hidden(self):
        safe = utils.safe_text('{"password": "abc\\"def"} <passphrase><![CDATA[x</literal>y]]></passphrase>')
        for secret in ("abc", "def", "x<", "y]]"):
            self.assertNotIn(secret, safe)

    def test_unterminated_and_pathological_quotes_are_handled(self):
        self.assertNotIn("hunter2", utils.safe_text('failed: password="hunter2'))
        utils.safe_text('password="' + "\\" * 5000)

    def test_secret_looking_params_are_refused(self):
        for key in ("password", "root_pass", "console_passwd", "secret", "private_key"):
            with self.subTest(key), self.assertRaises(ValueError):
                utils.check_params({"name": "x", key: "v"})
        with self.assertRaises(ValueError):
            utils.check_params({"config": [{"password": "v"}]})
        utils.check_params({"instance": 1, "name": "snap"})
