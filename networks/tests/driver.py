"""libvirt's test driver for the network tests."""

from unittest.mock import patch

import libvirt


def without_inactive_flag(test):
    """The test driver refuses VIR_NETWORK_XML_INACTIVE, which real hosts take:
    the saved definition is read as the running one, the same for a network
    the test does not change while it runs."""
    xml_desc = libvirt.virNetwork.XMLDesc
    patcher = patch.object(libvirt.virNetwork, "XMLDesc", lambda net, flags=0: xml_desc(net, 0))
    patcher.start()
    test.addCleanup(patcher.stop)
