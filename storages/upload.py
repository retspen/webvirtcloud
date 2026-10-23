"""A chunked ISO upload: a job its chunk requests run (the chunk protocol)."""

import atexit
import errno
import os
import posixpath
import stat
import threading
import time
from datetime import timedelta
from xml.sax.saxutils import escape

import paramiko
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from libvirt import VIR_ERR_NO_STORAGE_VOL, libvirtError

from computes.models import Compute
from logs.audit import audit
from operations import claims, jobs
from operations.models import Claim, Operation
from vrtManager.connection import CONN_SSH, CONN_SOCKET, CONN_TCP, CONN_TLS
from vrtManager.storage import wvmStorage

IDLE = "The upload was idle for over an hour; its partial file was deleted"
IDLE_SECONDS = 3600
SSH_CONNECT_TIMEOUT_SECONDS = 10
SSH_IO_TIMEOUT_SECONDS = 30
SSH_IDLE_SECONDS = 60
SSH_MAX_AGE_SECONDS = 600


class _SSHPool:
    """SSH connections to computes, kept for the next chunk of this process
    (one HTTP request per chunk; a new connection costs ~200 ms). A request
    takes a connection for itself and opens its own SFTP session on it. An
    idle connection is closed after SSH_IDLE_SECONDS, and none is reused
    once it is SSH_MAX_AGE_SECONDS old, so host keys and logins are checked
    again."""

    def __init__(self):
        self._lock = threading.Lock()
        self._idle = {}  # key -> (client, opened, timer)

    @staticmethod
    def _usable(client, opened):
        transport = client.get_transport()
        return transport is not None and transport.is_active() and time.monotonic() - opened < SSH_MAX_AGE_SECONDS

    def take(self, key):
        """An idle connection and when it was opened, or None"""
        with self._lock:
            entry = self._idle.pop(key, None)
        if entry is None:
            return None
        client, opened, timer = entry
        timer.cancel()
        if self._usable(client, opened):
            return client, opened
        client.close()
        return None

    def give(self, key, client, opened):
        if not self._usable(client, opened):
            client.close()
            return
        timer = threading.Timer(SSH_IDLE_SECONDS, lambda: self._expire(key, timer))
        timer.daemon = True
        with self._lock:
            kept = key not in self._idle
            if kept:
                try:
                    timer.start()
                except RuntimeError:  # no thread for the timer: not kept
                    kept = False
                else:
                    self._idle[key] = (client, opened, timer)
        if not kept:
            client.close()

    def _expire(self, key, timer):
        with self._lock:
            entry = self._idle.get(key)
            if entry is None or entry[2] is not timer:  # taken since, perhaps given back
                return
            del self._idle[key]
        entry[0].close()

    def close_all(self):
        with self._lock:
            entries, self._idle = list(self._idle.values()), {}
        for client, _opened, timer in entries:
            timer.cancel()
            client.close()

    def forget(self):
        """For a forked child: drop the parent's connections without ending
        their sessions; the parent keeps using them"""
        entries, self._lock, self._idle = list(self._idle.values()), threading.Lock(), {}
        for client, _opened, _timer in entries:
            transport = client.get_transport()
            if transport is not None:
                transport.atfork()


_ssh_pool = _SSHPool()
os.register_at_fork(after_in_child=_ssh_pool.forget)
atexit.register(_ssh_pool.close_all)


def _fsync_dir(dir_path):
    if not dir_path or not os.path.isdir(dir_path):
        return
    try:
        dir_fd = os.open(dir_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        pass


def _atomic_finalize_local(target_temp, target_final):
    parent_dir = os.path.dirname(target_final)
    # 1. Primary: POSIX os.link creates a hard link atomically and fails with FileExistsError if target_final exists.
    try:
        os.link(target_temp, target_final)
    except FileExistsError:
        # an earlier attempt linked the part file and died before unlinking it
        if not os.path.samestat(os.lstat(target_temp), os.lstat(target_final)):
            raise FileExistsError(_("Destination file already exists")) from None
    except OSError as link_err:
        # 2. Secondary: Linux kernel renameat2 with RENAME_NOREPLACE (flag 1)
        ret, err = -1, 0
        try:
            import ctypes
            libc = ctypes.CDLL("libc.so.6", use_errno=True)
            ret = libc.renameat2(
                ctypes.c_int(-100),
                target_temp.encode("utf-8"),
                ctypes.c_int(-100),
                target_final.encode("utf-8"),
                ctypes.c_uint(1),
            )
            err = ctypes.get_errno()
        except (AttributeError, OSError):  # no libc or no renameat2
            pass
        if ret == 0:
            _fsync_dir(parent_dir)
            return
        if err == errno.EEXIST:
            raise FileExistsError(_("Destination file already exists"))
        # If atomic no-replace cannot be guaranteed, fail safely without destroying target_temp
        raise OSError(_("Filesystem does not support atomic no-replace finalization: {}").format(link_err))
    _fsync_dir(parent_dir)
    try:
        os.unlink(target_temp)
        _fsync_dir(parent_dir)
    except OSError:
        pass


def _atomic_finalize_ssh(sftp, target_temp, target_final):
    """
    Finalize with standard SFTP rename, which requires an unused destination.
    Atomic visibility depends on the remote SFTP server and filesystem.
    """
    try:
        sftp.rename(target_temp, target_final)
    except OSError as err:
        # OpenSSH answers a taken destination with a generic "Failure"
        try:
            sftp.lstat(target_final)
        except OSError:
            raise err from None
        try:
            sftp.lstat(target_temp)
        except FileNotFoundError:
            return  # the rename was done; its answer was lost
        raise FileExistsError(_("Destination file already exists")) from err


def _write_pipelined(stream, chunk, offset):
    """Write chunk to an SFTP file at offset without waiting for the answer to
    each 32 KiB write, raising an error as soon as one is read. Each write is
    registered to the file, as paramiko does for prefetched reads, so its
    answer reaches the file in whatever order it comes. (paramiko's own
    pipelined writes drop their errors.)"""
    sftp = stream.sftp
    for data in chunk.chunks():
        for start in range(0, len(data), stream.MAX_REQUEST_SIZE):
            piece = data[start:start + stream.MAX_REQUEST_SIZE]
            sftp._async_request(stream, paramiko.sftp.CMD_WRITE, stream.handle, paramiko.sftp.int64(offset), piece)
            offset += len(piece)
            # answers are taken as they come, so the server never waits for us to read
            while sftp.sock.recv_ready():
                sftp._read_response()
            stream._check_exception()
    sftp._finish_responses(stream)
    return offset


class _UploadTarget:
    """The part file of an upload to a local (socket) or SSH pool, renamed to
    the image when the last chunk is written."""

    def __init__(self, conn, path, file_name, upload_id):
        self.conn = conn
        self.remote = conn.conn == CONN_SSH
        if not self.remote and conn.conn != CONN_SOCKET:
            raise ValueError(_("Unsupported connection type for file upload."))
        join = posixpath.join if self.remote else os.path.join
        normalize = posixpath.normpath if self.remote else os.path.abspath
        self.base = normalize(path)
        self.final = normalize(join(self.base, file_name))
        self.part = normalize(join(self.base, f"{file_name}.wvc_upload_{upload_id}.part"))
        for target in (self.final, self.part):
            if self.remote:
                contained = target.startswith(self.base.rstrip("/") + "/")
            else:
                contained = os.path.commonpath((self.base, target)) == self.base
            if not contained:
                raise PermissionError(_("Security issues with file uploading: path traversal detected"))
        self.ssh = None
        self.sftp = None

    def __enter__(self):
        if self.remote:
            hostname, separator, port = self.conn.host.partition(":")
            self.key = (hostname, int(port) if separator else 22, self.conn.login, self.conn.passwd)
            taken = _ssh_pool.take(self.key)
            if taken is not None:
                self.ssh, self.opened = taken
                try:
                    self._open_sftp()
                    return self
                except Exception:  # a connection the host dropped: open a new one
                    self.ssh.close()
            self.ssh, self.opened = self._connect(), time.monotonic()
            try:
                self._open_sftp()
            except Exception:
                self.ssh.close()
                raise
        return self

    def _connect(self):
        hostname, port = self.key[:2]
        ssh = paramiko.SSHClient()
        try:
            ssh.load_system_host_keys()
            ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
            ssh.connect(
                hostname=hostname, port=port,
                username=self.conn.login, password=self.conn.passwd,
                timeout=SSH_CONNECT_TIMEOUT_SECONDS,
                banner_timeout=SSH_CONNECT_TIMEOUT_SECONDS,
                auth_timeout=SSH_CONNECT_TIMEOUT_SECONDS,
                channel_timeout=SSH_CONNECT_TIMEOUT_SECONDS,
            )
        except Exception:
            ssh.close()
            raise
        return ssh

    def _open_sftp(self):
        # paramiko waits for the SFTP subsystem without a deadline; on a dead
        # connection closing it ends the wait with an error
        watchdog = threading.Timer(SSH_CONNECT_TIMEOUT_SECONDS, self.ssh.close)
        watchdog.daemon = True
        watchdog.start()
        try:
            self.sftp = self.ssh.open_sftp()
        finally:
            watchdog.cancel()
        transport = self.ssh.get_transport()
        if transport is None or not transport.is_active():
            self.sftp.close()
            raise paramiko.SSHException(_("The SFTP session did not start in time"))
        self.sftp.get_channel().settimeout(SSH_IO_TIMEOUT_SECONDS)

    def __exit__(self, exc_type, *_):
        if self.ssh is None:
            return
        try:
            self.sftp.close()
        except Exception:
            self.ssh.close()
            raise
        # after an error the connection is not trusted for the next chunk
        if exc_type is None:
            _ssh_pool.give(self.key, self.ssh, self.opened)
        else:
            self.ssh.close()

    def info(self, path):
        try:
            info = self.sftp.lstat(path) if self.remote else os.lstat(path)
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(info.st_mode):
            raise PermissionError(_("Security issues with file uploading: symlink detected"))
        return info

    def present(self):
        return self.info(self.part) is not None

    def done(self):
        return self.info(self.final) is not None

    def write(self, chunk, offset, new):
        if self.remote:
            with self.sftp.open(self.part, "wb" if new else "r+b") as stream:
                if not new:
                    stream.seek(offset)
                    stream.truncate(offset)
                # ~5x faster on a LAN than waiting for each 32 KiB write
                offset = _write_pipelined(stream, chunk, offset)
            return offset
        flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL) if new else os.O_RDWR
        flags |= getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(self.part, flags, 0o600)
        with open(fd, "wb" if new else "r+b", closefd=True) as stream:
            if not new:
                stream.seek(offset)
                stream.truncate()
            for data in chunk.chunks():
                stream.write(data)
                offset += len(data)
            stream.flush()
            os.fsync(stream.fileno())
        if new:  # the part file's name survives a host crash once its offset is committed
            _fsync_dir(self.base)
        return offset

    def finalize(self):
        if self.remote:
            _atomic_finalize_ssh(self.sftp, self.part, self.final)
        else:
            _atomic_finalize_local(self.part, self.final)

    def remove(self):
        if not self.present():
            return
        if self.remote:
            self.sftp.remove(self.part)
        else:
            os.unlink(self.part)
            _fsync_dir(self.base)


class _VolumeTarget:
    """The volume of an upload to a TCP/TLS pool, written through libvirt
    streams; it has the image's name from the first chunk."""

    def __init__(self, conn, name, size):
        self.conn = conn
        self.name = name
        self.size = size

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def present(self):
        try:
            self.conn.get_volume(self.name)
        except libvirtError as err:
            if err.get_error_code() == VIR_ERR_NO_STORAGE_VOL:
                return False
            raise
        return True

    done = present

    def write(self, chunk, offset, new):
        if new:
            xml = (
                "<volume><name>{}</name><capacity unit='bytes'>{}</capacity>"
                "<target><format type='raw'/></target></volume>"
            ).format(escape(self.name), self.size)
            self.conn.pool.createXML(xml, 0)
        volume = self.conn.get_volume(self.name)
        stream = self.conn.wvm.newStream(0)
        try:
            volume.upload(stream, offset, chunk.size, 0)
            written = 0
            for data in chunk.chunks():
                while data:
                    sent = stream.send(data)
                    if sent <= 0:
                        raise OSError(_("Libvirt stream stopped during upload"))
                    written += sent
                    data = data[sent:]
            if written != chunk.size:
                raise OSError(_("Upload chunk size changed during transfer"))
            stream.finish()
        except Exception:
            stream.abort()
            raise
        return offset + written

    def finalize(self):
        pass

    def remove(self):
        if self.present():
            self.conn.get_volume(self.name).delete(0)


def _target(conn, op):
    if conn.conn in (CONN_TCP, CONN_TLS):
        return _VolumeTarget(conn, op.params["name"], op.params["size"])
    return _UploadTarget(conn, conn.get_target_path(), op.params["name"], op.pk.hex)


def _session_key(op):
    """Held by a chunk request, and by the ending path, for the whole of its work."""
    return f"upload:{op.pk}"


def _idle(op):
    return op.heartbeat_at < timezone.now() - timedelta(seconds=IDLE_SECONDS)


def _commit(op, **fields):
    if not Operation.objects.filter(pk=op.pk, state__in=Operation.ACTIVE).update(**fields):
        raise ValueError(_("The upload has ended"))
    for name, value in fields.items():
        setattr(op, name, value)


def _complete(target, op):
    """Rename the part file to the image, unless a retry finds it done, and
    succeed; a name taken meanwhile, or an image gone, fails the upload."""
    try:
        if target.present():
            target.finalize()
        elif not target.done():
            jobs.finish(op, jobs.Outcome(Operation.FAILED, error="The uploaded image is missing"))
            raise ValueError(_("The uploaded image is missing"))
    except FileExistsError:
        target.remove()
        jobs.finish(op, jobs.Outcome(Operation.FAILED, error="An image of this name appeared before the upload "
                                                             "finished; the upload was deleted"))
        raise
    jobs.finish(op, jobs.Outcome(Operation.SUCCEEDED))


def _end(target, op, state, error=""):
    if op.intent.get("created"):
        target.remove()
    jobs.finish(op, jobs.Outcome(state, error=error))


def _refuse(target, op, state, message, error=""):
    """End the upload and refuse the chunk."""
    _end(target, op, state, error)
    raise ValueError(message)


def end(op, state, error=""):
    """Delete what the upload made and end it, unless a chunk request holds
    it: that request sees the cancel, or the next expiry pass retries. A
    requested cancel ends it cancelled. An upload whose every chunk is in is
    completed instead: a cancel then comes too late."""
    try:
        with claims.hold({_session_key(op): Claim.EXCLUSIVE}):
            op.refresh_from_db()
            if op.state not in Operation.ACTIVE or (error == IDLE and not _idle(op)):
                return  # ended already, or expiry of an upload that is not idle
            if op.cancel_requested:
                state, error = Operation.CANCELLED, ""
            if not op.intent.get("created"):
                jobs.finish(op, jobs.Outcome(state, error=error))
                return
            compute = Compute.objects.filter(pk=op.params["compute"]).first()
            if compute is None:
                jobs.finish(op, jobs.Outcome(Operation.FAILED, error="The compute was deleted"))
                return
            conn = wvmStorage(compute.hostname, compute.login, compute.password, compute.type, op.params["pool"])
            try:
                with _target(conn, op) as target:
                    # its last request died before the rename
                    if op.intent["chunk"] == op.params["chunks"]:
                        try:
                            _complete(target, op)
                        except (FileExistsError, ValueError):  # _complete failed the upload
                            pass
                    else:
                        _end(target, op, state, error)
            finally:
                conn.close()
    except claims.Busy:
        pass


def write_chunk(user, conn, compute, pool, upload_id, raw, chunk_index, chunk, request=None):
    """Write chunk chunk_index of the upload upload_id (the job's submission
    key) and commit it on the job; the last chunk renames the image."""
    kind = jobs.get_kind("volume.upload")
    raw = {**raw, "compute": compute.pk, "pool": pool}
    if chunk_index == 0 and request is not None:
        name = os.path.basename(str(raw["name"])).strip()
        with audit(request, compute, f"Storage pool {pool}", f"upload volume {name}") as entry:
            op = jobs.submit(kind.name, user, raw, upload_id)
            entry.skip = True  # the job writes its row when it ends
        jobs.remember_job(request, op)
    elif chunk_index == 0:
        op = jobs.submit(kind.name, user, raw, upload_id)
    else:
        op = Operation.objects.filter(user=user, submission_key=upload_id).first()
        if op is None:
            raise ValueError(_("Upload session not found or expired"))
        if op.kind != kind.name or op.params != kind.normalize(raw):
            raise ValueError(_("Upload session parameters changed"))

    with claims.hold({_session_key(op): Claim.EXCLUSIVE}):
        op.refresh_from_db()
        params = op.params
        last = chunk_index == params["chunks"] - 1
        if op.state == Operation.SUCCEEDED and last:
            return op  # the answer to the last chunk was lost
        if op.state not in Operation.ACTIVE:
            raise ValueError(op.error or _("The upload has ended"))
        with _target(conn, op) as target:
            expected = op.intent["chunk"]
            # once every chunk is in, a cancel comes too late: a retry completes it below
            if op.cancel_requested and expected < params["chunks"]:
                _refuse(target, op, Operation.CANCELLED, _("The upload was cancelled"))
            if chunk_index > expected:
                raise ValueError(_("Invalid chunk sequence. Expected chunk %(exp)d, got %(got)d")
                                 % {"exp": expected, "got": chunk_index})
            if chunk_index < expected:  # a retry of a committed chunk
                if last and expected == params["chunks"]:
                    _complete(target, op)
                return op
            if _idle(op):
                _refuse(target, op, Operation.FAILED, IDLE, IDLE)
            offset = op.progress_done or 0
            if chunk.size <= 0:
                raise ValueError(_("Empty upload chunk"))
            if offset + chunk.size > params["size"]:
                raise ValueError(_("Upload exceeds declared file size"))
            if last and offset + chunk.size != params["size"]:
                raise ValueError(_("Final chunk does not match declared file size"))
            present = target.present()  # refuses a symlinked part file
            # a first write that failed before creating it is retried as new
            new = not (op.intent["created"] and present)
            if new and offset:
                jobs.finish(op, jobs.Outcome(Operation.FAILED, error="The partial upload is missing"))
                raise ValueError(_("The partial upload is missing"))
            if not op.intent["created"]:
                _commit(op, intent={"chunk": expected, "created": True})
            written = target.write(chunk, offset, new)
            _commit(op, progress_done=written, progress_total=params["size"],
                    intent={"chunk": expected + 1, "created": True}, heartbeat_at=timezone.now())
            if last:  # a cancel during the write comes too late
                _complete(target, op)
            # a cancel that came during the write found this request holding the upload
            elif Operation.objects.filter(pk=op.pk, cancel_requested=True).exists():
                _refuse(target, op, Operation.CANCELLED, _("The upload was cancelled"))
    return op
