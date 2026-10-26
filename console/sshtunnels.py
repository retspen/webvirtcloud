"""The VNC console of an SSH compute, carried by the SSH connection: `ssh -W`
forwards its standard input and output to the console's address or Unix
socket on the compute, so the compute needs no nc and runs no shell."""

import ipaddress
import socket
import subprocess


def tunnel_target(address, port, unix_socket):
    """Where on the compute ssh forwards to: the Unix socket, or the address
    and port, a wildcard or missing address meaning the compute's loopback."""
    if unix_socket:
        return unix_socket
    address = {None: "127.0.0.1", "": "127.0.0.1", "0.0.0.0": "127.0.0.1", "::": "::1"}.get(address, address)
    try:
        if ipaddress.ip_address(address).version == 6:
            address = f"[{address}]"
    except ValueError:  # a host name
        pass
    return f"{address}:{port}"


def open_tunnel(host, user, target):
    """A socket connected to target on host, and the ssh process carrying it.
    ssh never asks for anything: a missing key or an unknown host key fails."""
    ours, theirs = socket.socketpair()
    argv = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-W", target]
    if user:
        argv += ["-l", user]
    process = subprocess.Popen(argv + ["--", host], stdin=theirs, stdout=theirs, stderr=subprocess.PIPE)
    theirs.close()
    return ours, process


def close_tunnel(process):
    """End the ssh process; its error output, if it failed."""
    if process.poll() is None:
        process.terminate()
    _, error = process.communicate()
    return error.decode(errors="replace").strip() if process.returncode not in (0, -15) else ""
