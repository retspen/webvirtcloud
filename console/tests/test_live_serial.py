"""Live serial console: socketiod opens a running wvc-test VM's console on the
TCP host (TEST_LIBVIRT_HOST, with its password) and on the SSH host
(TEST_LIBVIRT_SSH_HOST). The VM has no graphics and no OS; SeaBIOS writes its
banner to the serial port. Runs only with TEST_LIBVIRT_HOST set."""

import os
import time
import unittest

import libvirt

from django.contrib.auth import get_user_model
from django.test import TransactionTestCase
from vrtManager.connection import connection_manager

from accounts.models import UserInstance
from computes.models import Compute
from console import tokens
from console.tests.test_socketiod_child import consoles, console, start_socketiod, socketio
from instances.models import Instance
from instances.tests import livetest

P = livetest.PREFIX


def wait_for(condition, seconds=30):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.2)


def serial_vm(conn, name):
    """A paused VM without graphics whose BIOS writes to the serial console once resumed."""
    dom = conn.defineXML(
        f"<domain type='kvm'><name>{name}</name><memory unit='MiB'>64</memory><vcpu>1</vcpu>"
        "<os><type arch='x86_64' machine='q35'>hvm</type><bios useserial='yes'/></os>"
        "<devices><serial type='pty'><target port='0'/></serial><console type='pty'/></devices></domain>"
    )
    dom.createWithFlags(libvirt.VIR_DOMAIN_START_PAUSED)
    return dom


@unittest.skipIf(socketio is None, "python-socketio is not installed")
class LiveSerialConsoleTestCase(TransactionTestCase):
    def setUp(self):
        if not livetest.enabled():
            self.skipTest("Set TEST_LIBVIRT_HOST to run the live libvirt tests")
        self.user = get_user_model().objects.create_user("serial-live", password="pw")
        self.hosts = [(os.environ["TEST_LIBVIRT_HOST"], os.environ.get("TEST_LIBVIRT_LOGIN", ""),
                       os.environ.get("TEST_LIBVIRT_PASSWORD", ""), int(os.environ.get("TEST_LIBVIRT_TYPE", 4)))]
        if os.environ.get("TEST_LIBVIRT_SSH_HOST"):
            self.hosts.append((os.environ["TEST_LIBVIRT_SSH_HOST"], os.environ.get("TEST_LIBVIRT_SSH_LOGIN", "root"), "", 2))
        self.server, self.port = start_socketiod(self)

    def token(self, host, login, password, conn_type):
        compute = Compute.objects.create(name=f"{P}{host}-{conn_type}", hostname=host, login=login, password=password, type=conn_type)
        conn = connection_manager.get_connection(host, login, password, conn_type)
        before = livetest.inventory(conn)
        self.addCleanup(lambda: self.assertEqual(livetest.inventory(conn), before))
        self.addCleanup(livetest.cleanup, conn)
        dom = serial_vm(conn, f"{P}serial-{conn_type}")
        vm = Instance.objects.create(compute=compute, name=dom.name(), uuid=dom.UUIDString())
        UserInstance.objects.create(user=self.user, instance=vm)
        return tokens.SIGNER.sign(f"{compute.id}:{vm.uuid}:{self.user.id}"), dom

    def admin_token(self, token):
        host, uuid, _user = tokens.SIGNER.unsign(token).split(":")
        admin, _ = get_user_model().objects.get_or_create(username="serial-live-admin", is_superuser=True)
        return tokens.SIGNER.sign(f"{host}:{uuid}:{admin.id}")

    def test_the_console_of_a_running_vm_opens_once(self):
        for args in self.hosts:
            with self.subTest(host=args[0], type=args[3]):
                token, dom = self.token(*args)
                client, received = console(self.port, token)
                time.sleep(1)  # the console is open on the paused VM; its BIOS writes once it runs
                dom.resume()
                deadline = time.monotonic() + 30
                while "SeaBIOS" not in "".join(received["output"]) and time.monotonic() < deadline:
                    time.sleep(0.2)
                self.assertIn("SeaBIOS", "".join(received["output"]))
                # one client per VM; a superuser takes a console left open over
                with self.assertRaises(socketio.exceptions.ConnectionError):
                    console(self.port, token)
                admin_client, admin_received = console(self.port, self.admin_token(token))
                wait_for(lambda: received["taken_over"])
                self.assertEqual(received["taken_over"], ["serial-live-admin"])
                client.disconnect()
                # the VM stops: the terminal says so
                dom.destroy()
                wait_for(lambda: "not running" in "".join(admin_received["output"]))
                self.assertIn("The VM is not running", "".join(admin_received["output"]))
                admin_client.disconnect()
                wait_for(lambda: not consoles(self.server.pid))
                self.assertEqual(consoles(self.server.pid), [])
