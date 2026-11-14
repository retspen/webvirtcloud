"""Test data shared by the interface tests: a valid bridge form."""


BASE = {
    "name": "br1", "itype": "bridge", "start_mode": "onboot", "netdev": "eth1",
    "ipv4_type": "static", "ipv4_addr": "192.0.2.10/24", "ipv4_gw": "192.0.2.1",
    "ipv6_type": "static", "stp": "on", "delay": 0,
}
