"""The VNC console of an SSH compute, carried by the SSH connection: `ssh -W`
forwards its standard input and output to the console's address or Unix
socket on the compute, so the compute needs no nc and runs no shell."""

import ipaddress
import socket
import subprocess
import tempfile


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


class Tunnel:
    """The ssh process that carries a console, and its error output, kept in
    a file: a pipe nobody reads while the console runs would stop ssh once
    it filled."""

    def __init__(self, argv, sock):
        self.errors = tempfile.TemporaryFile()
        self.process = subprocess.Popen(argv, stdin=sock, stdout=sock, stderr=self.errors)

    def close(self):
        """End ssh, killed if it does not stop within 5 seconds; its error
        output if it failed, else ""."""
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self.errors.seek(0)
        error = self.errors.read().decode(errors="replace").strip()
        self.errors.close()
        return error if self.process.returncode not in (0, -15) else ""


def open_tunnel(host, user, target):
    """A socket connected to target on host, and the Tunnel carrying it.
    ssh never asks for anything: a missing key or an unknown host key fails."""
    ours, theirs = socket.socketpair()
    argv = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-W", target]
    if user:
        argv += ["-l", user]
    tunnel = Tunnel(argv + ["--", host], theirs)
    theirs.close()
    return ours, tunnel
