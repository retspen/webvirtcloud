import argparse
import unittest


class TestCLIParsers(unittest.TestCase):
    def test_novncd_parser_defaults(self):
        # We test the parser specification without importing django
        parser = argparse.ArgumentParser(description="WebVirtCloud noVNC daemon")
        parser.add_argument("-v", "--verbose", dest="verbose", action="store_true", default=False)
        parser.add_argument("-d", "--debug", dest="debug", action="store_true", default=False)
        parser.add_argument("-H", "--host", dest="host", action="store", default="0.0.0.0")
        parser.add_argument("-p", "--port", dest="port", action="store", type=int, default=6080)
        parser.add_argument("-c", "--cert", dest="cert", action="store", default="cert.pem")

        opts = parser.parse_args([])
        self.assertFalse(opts.verbose)
        self.assertFalse(opts.debug)
        self.assertEqual(opts.host, "0.0.0.0")
        self.assertEqual(opts.port, 6080)
        self.assertEqual(opts.cert, "cert.pem")

    def test_novncd_parser_custom_args(self):
        parser = argparse.ArgumentParser(description="WebVirtCloud noVNC daemon")
        parser.add_argument("-v", "--verbose", dest="verbose", action="store_true", default=False)
        parser.add_argument("-d", "--debug", dest="debug", action="store_true", default=False)
        parser.add_argument("-H", "--host", dest="host", action="store", default="0.0.0.0")
        parser.add_argument("-p", "--port", dest="port", action="store", type=int, default=6080)
        parser.add_argument("-c", "--cert", dest="cert", action="store", default="cert.pem")

        opts = parser.parse_args(["-v", "-d", "-H", "192.168.1.50", "-p", "7000", "-c", "/etc/ssl/cert.pem"])
        self.assertTrue(opts.verbose)
        self.assertTrue(opts.debug)
        self.assertEqual(opts.host, "192.168.1.50")
        self.assertEqual(opts.port, 7000)
        self.assertEqual(opts.cert, "/etc/ssl/cert.pem")

    def test_socketiod_parser_defaults_and_custom(self):
        parser = argparse.ArgumentParser(description="WebVirtCloud Socket.IO daemon")
        parser.add_argument("-v", "--verbose", dest="verbose", action="store_true", default=False)
        parser.add_argument("-d", "--debug", dest="debug", action="store_true", default=False)
        parser.add_argument("-H", "--host", dest="host", action="store", default="localhost")
        parser.add_argument("-p", "--port", dest="port", action="store", type=int, default=6081)

        opts_def = parser.parse_args([])
        self.assertFalse(opts_def.verbose)
        self.assertFalse(opts_def.debug)
        self.assertEqual(opts_def.host, "localhost")
        self.assertEqual(opts_def.port, 6081)

        opts_custom = parser.parse_args(["--verbose", "--host", "10.0.0.1", "--port", "9000"])
        self.assertTrue(opts_custom.verbose)
        self.assertEqual(opts_custom.host, "10.0.0.1")
        self.assertEqual(opts_custom.port, 9000)


if __name__ == "__main__":
    unittest.main()
