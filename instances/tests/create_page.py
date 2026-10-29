"""The VM create page rendered on libvirt's test driver, for the tests of
that page."""

from unittest.mock import patch

import libvirt
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.urls import reverse


def render_create_page(testcase, data=None):
    """GET the create page, or POST data (a create submission) to it, as a
    superuser on a test-driver compute; returns (compute, response)."""
    conn = libvirt.open("test:///default")
    testcase.addCleanup(conn.close)
    compute, _ = Compute.objects.get_or_create(name="testdrv", hostname="localhost", login="", password="", type=4)
    user = get_user_model().objects.filter(username="page").first() or \
        get_user_model().objects.create_superuser("page", "page@example.com", "pw")
    testcase.client.force_login(user)
    url = reverse("instances:create_instance", args=[compute.id, "i686", "pc"])
    with patch("vrtManager.connection.connection_manager.get_connection", return_value=conn), \
         patch("vrtManager.connection.wvmConnect.get_machine_types", return_value=["pc"]), \
         patch("vrtManager.connection.wvmConnect.get_nwfilters", return_value=[]), \
         patch("vrtManager.connection.wvmConnect.get_cpu_modes", return_value=["host-model"]):  # the test driver has none
        if data is None:
            response = testcase.client.get(url)
        else:
            response = testcase.client.post(url, {"create": "", **data})
    return compute, response
