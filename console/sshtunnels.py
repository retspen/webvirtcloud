# Copyright (C) 2014, 2015 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import functools
import logging as log
import os
import queue
import signal
import socket
import threading


class _TunnelScheduler(object):
    """
    If the user is using Spice + SSH URI + no SSH keys, we need to
    serialize connection opening otherwise ssh-askpass gets all angry.
    This handles the locking and scheduling.
    It's only instantiated once for the whole app, because we serialize
    independent of connection, vm, etc.
    """

    def __init__(self):
        self._thread = None
        self._queue = queue.Queue()
        self._lock = threading.Lock()

    def _handle_queue(self):
        while True:
            (
                lock_cb,
                cb,
                args,
            ) = self._queue.get()
            lock_cb()
            cb(*args)

    def schedule(self, lock_cb, cb, *args):
        if not self._thread:
            self._thread = threading.Thread(
                name="Tunnel thread", target=self._handle_queue, args=()
            )
            self._thread.daemon = True
        if not self._thread.is_alive():
            self._thread.start()
        self._queue.put((lock_cb, cb, args))

    def lock(self):
        self._lock.acquire()

    def unlock(self):
        self._lock.release()


_tunnel_scheduler = _TunnelScheduler()


class _Tunnel(object):
    def __init__(self):
        self._pid = None
        self._closed = False
        self._errfd = None

    def close(self):
        if self._closed:
            return
        self._closed = True

        log.debug(
            "Close tunnel PID=%s ERRFD=%s",
            self._pid,
            self._errfd and self._errfd.fileno() or None,
        )

        # Since this is a socket object, the file descriptor is closed
        # when it's garbage collected.
        self._errfd = None

        if self._pid:
            os.kill(self._pid, signal.SIGKILL)
            os.waitpid(self._pid, 0)
        self._pid = None

    def get_err_output(self):
        errout = ""
        while True:
            try:
                new = self._errfd.recv(1024)
            except Exception:
                break

            if not new:
                break

            errout += new.decode()

        return errout

    def open(self, argv, sshfd):
        if self._closed:
            return

        errfds = socket.socketpair()
        pid = os.fork()
        if pid == 0:
            errfds[0].close()

            os.dup2(sshfd.fileno(), 0)
            os.dup2(sshfd.fileno(), 1)
            os.dup2(errfds[1].fileno(), 2)
            os.execlp(*argv)
            os._exit(1)  # pylint: disable=protected-access

        sshfd.close()
        errfds[1].close()

        self._errfd = errfds[0]
        self._errfd.setblocking(0)
        log.debug("Opened tunnel PID=%d ERRFD=%d", pid, self._errfd.fileno())

        self._pid = pid


def _make_ssh_command(connhost, connuser, connport, gaddr, gport, gsocket):

    # Build SSH cmd
    argv = ["ssh", "ssh"]
    if connport:
        argv += ["-p", str(connport)]

    if connuser:
        argv += ["-l", connuser]

    argv += [connhost]

    # Build 'nc' command run on the remote host
    #
    # This ugly thing is a shell script to detect availability of
    # the -q option for 'nc': debian and suse based distros need this
    # flag to ensure the remote nc will exit on EOF, so it will go away
    # when we close the VNC tunnel. If it doesn't go away, subsequent
    # VNC connection attempts will hang.
    #
    # Fedora's 'nc' doesn't have this option, and apparently defaults
    # to the desired behavior.
    #
    if gsocket:
        nc_params = "-U %s" % gsocket
    else:
        nc_params = "%s %s" % (gaddr, gport)

    nc_cmd = (
        """nc -q 2>&1 | grep "requires an argument" >/dev/null;"""
        """if [ $? -eq 0 ] ; then"""
        """   CMD="nc -q 0 %(nc_params)s";"""
        """else"""
        """   CMD="nc %(nc_params)s";"""
        """fi;"""
        """eval "$CMD";""" % {"nc_params": nc_params}
    )

    argv.append("sh -c")
    argv.append("'%s'" % nc_cmd)

    argv_str = functools.reduce(lambda x, y: x + " " + y, argv[1:])
    log.debug("Pre-generated ssh command for info: %s", argv_str)
    return argv


class SSHTunnels(object):
    def __init__(self, connhost, connuser, connport, gaddr, gport, gsocket):
        self._tunnels = []
        self._sshcommand = _make_ssh_command(
            connhost, connuser, connport, gaddr, gport, gsocket
        )
        self._locked = False

    def open_new(self):
        t = _Tunnel()
        self._tunnels.append(t)

        # socket FDs are closed when the object is garbage collected. This
        # can close an FD behind spice/vnc's back which causes crashes.
        #
        # Dup a bare FD for the viewer side of things, but keep the high
        # level socket object for the SSH side, since it simplifies things
        # in that area.
        viewerfd, sshfd = socket.socketpair()
        _tunnel_scheduler.schedule(self._lock, t.open, self._sshcommand, sshfd)

        retfd = os.dup(viewerfd.fileno())
        log.debug("Generated tunnel fd=%s for viewer", retfd)
        return retfd

    def close_all(self):
        for l in self._tunnels:
            l.close()
        self._tunnels = []
        self.unlock()

    def get_err_output(self):
        errstrings = []
        for l in self._tunnels:
            e = l.get_err_output().strip()
            if e and e not in errstrings:
                errstrings.append(e)
        return "\n".join(errstrings)

    def _lock(self):
        _tunnel_scheduler.lock()
        self._locked = True

    def unlock(self, *args, **kwargs):
        if self._locked:
            _tunnel_scheduler.unlock(*args, **kwargs)
            self._locked = False
