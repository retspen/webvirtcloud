"""Jobs of the storages app (operations framework)."""

import contextlib
import logging
import os
import posixpath
import re
import time
from urllib.parse import unquote, urljoin, urlsplit

import urllib3

from django.core.exceptions import PermissionDenied
from django.utils.translation import gettext, gettext_noop
from libvirt import libvirtError
from vrtManager import util
from vrtManager.storage import FILE_POOL_TYPES, wvmStorage

from computes.models import Compute
from operations import claims, utils
from operations.jobs import Cancelled, Kind, Outcome, Plan, register
from operations.models import Claim, Operation

from storages import upload

logger = logging.getLogger(__name__)


def _log(op, state, action):
    compute, _sep, pool = op.resource_label.rpartition("/")  # a pool name has no "/"
    message = f"Storage pool {pool}: {action}"
    return compute, "", "", message if state == Operation.SUCCEEDED else f"{message} ({state})"


def is_iso(name):
    """An ISO image, by its name: libvirt calls its format raw. It is uploaded, not cloned."""
    return name.lower().endswith(".iso")


def _storage(params):
    c = Compute.objects.get(pk=params["compute"])
    return c, wvmStorage(c.hostname, c.login, c.password, c.type, params["pool"])


@register
class CloneVolume(Kind):
    name = "volume.clone"
    label = gettext_noop("Clone volume")
    time_limit = 12 * 3600  # a copy cannot be stopped: over time is only noted

    def normalize(self, raw):
        fmt = str(raw.get("format") or "") if raw.get("convert") else ""
        return {"compute": int(raw["compute"]), "pool": str(raw["pool"]), "image": str(raw["image"]),
                "name": str(raw["name"]), "format": fmt, "prealloc": fmt == "qcow2" and bool(raw.get("meta_prealloc"))}

    def validate(self, user, params):
        if not user.is_superuser:
            raise PermissionDenied

    def precheck(self, op, ctx):
        if op.user is None or not op.user.is_active or not op.user.is_superuser:
            raise PermissionDenied
        # a volume made outside the panel since the job was queued may have taken the name
        stg = _storage(op.params)[1]
        if op.intent["target"] in stg.get_volumes():
            raise util.OperationError(gettext_noop("Name of volume already in use"))
        # the source's format, which names the copy, may have changed before its claim was taken (a download ended)
        if stg.clone_name(op.params["name"], op.params["format"] or stg.get_volume_format_type(op.params["image"])) \
                != op.intent["target"]:
            raise util.OperationError(gettext_noop("The volume changed since the copy was asked; ask it again"))
        stg.refuse_running_copy(op.params["image"])  # the VM may have started since

    def plan(self, user, params):
        compute, stg = _storage(params)
        volumes = stg.get_volumes()
        if params["image"] not in volumes:
            raise util.OperationError(gettext_noop("The pool has no volume named %(name)s"), name=params["image"])
        if is_iso(params["image"]):
            raise util.OperationError(gettext_noop("An ISO image is not cloned"))
        stg.refuse_running_copy(params["image"])
        target = stg.clone_name(params["name"], params["format"] or stg.get_volume_format_type(params["image"]))
        if target in volumes:
            raise util.OperationError(gettext_noop("Name of volume already in use"))
        pool = claims.pool_key(compute.pk, params["pool"])
        # the source shared: not copied while a download writes it
        return Plan(claims={claims.compute_key(compute.pk): Claim.SHARED, pool: Claim.SHARED,
                            claims.volume_key(compute.pk, params["pool"], params["image"]): Claim.SHARED,
                            claims.volume_key(compute.pk, params["pool"], target): Claim.EXCLUSIVE},
                    resource=pool, label=f"{compute.name}/{params['pool']}", intent={"target": target})

    def run(self, op, ctx):
        _compute, stg = _storage(op.params)
        ctx.record_intent()
        ctx.set_phase(gettext_noop("Copying the volume"))
        created = stg.clone_volume(stg.get_volume(op.params["image"]), op.intent["target"], op.params["format"] or None,
                                   op.params["prealloc"])
        ctx.record_intent(created=created)
        return {}

    def reconcile(self, op):
        if op.intent.get("created"):
            return Outcome(Operation.SUCCEEDED)
        _compute, stg = _storage(op.params)  # unreachable: recovery waits and retries
        if op.intent["target"] in stg.get_volumes():
            return Outcome(Operation.UNCERTAIN, error=utils.say(gettext_noop(
                "The copy exists, but the job did not see it finish; check it, then resolve this job.")))
        return Outcome(Operation.FAILED, error=utils.say(gettext_noop("The copy was not made")))

    def log_entry(self, op, state):
        return _log(op, state, f"clone volume {op.params['image']} as {op.intent['target']}")


@register
class UploadVolume(Kind):
    """An ISO upload: its chunk requests run it (storages.upload)."""

    name = "volume.upload"
    label = gettext_noop("Upload ISO image")
    cancellable = True
    progress_bytes = True
    runs_in_request = True

    def normalize(self, raw):
        return {"compute": int(raw["compute"]), "pool": str(raw["pool"]),
                "name": os.path.basename(str(raw["name"])).strip(), "size": int(raw["size"]),
                "chunks": int(raw["chunks"])}

    def validate(self, user, params):
        if not user.is_superuser:
            raise PermissionDenied
        name = params["name"]
        if not name or name in (".", "..") or "\x00" in name:
            raise ValueError(gettext("Invalid file name"))
        if len(name) <= 4 or not is_iso(name):
            raise ValueError(gettext("Only .iso files can be uploaded"))
        if params["size"] <= 0:
            raise ValueError(gettext("Invalid file size"))
        if params["chunks"] < 1:
            raise ValueError(gettext("Invalid chunk index or total chunks"))

    def plan(self, user, params):
        compute, stg = _storage(params)
        with contextlib.suppress(libvirtError):  # refused while a volume is cloned in the pool
            stg.refresh()
        if params["name"] in stg.get_volumes():
            raise FileExistsError(f"The pool has a volume named {params['name']}")
        pool = claims.pool_key(compute.pk, params["pool"])
        return Plan(claims={claims.compute_key(compute.pk): Claim.SHARED, pool: Claim.SHARED,
                            claims.volume_key(compute.pk, params["pool"], params["name"]): Claim.EXCLUSIVE},
                    resource=pool, label=f"{compute.name}/{params['pool']}", intent={"chunk": 0, "created": False})

    def cancel(self, op):
        try:
            upload.end(op, Operation.CANCELLED)
        except Exception as err:  # the next chunk or the expiry ends it
            logger.error("cancelling upload %s failed: %s", op.pk, utils.safe_text(err))

    def expire(self, op):
        upload.end(op, Operation.FAILED, utils.say(upload.IDLE))

    def log_entry(self, op, state):
        return _log(op, state, f"upload volume {op.params['name']}")


# a volume's name as the pool page's forms take it
VOLUME_NAME = re.compile(r"[A-Za-z0-9._-]{1,120}")
FETCH_REDIRECTS = 5
FETCH_TIMEOUT = urllib3.Timeout(connect=10, read=60)
BAD_ADDRESS = gettext_noop("Give an http or https address")


def url_file_name(url):
    """The file name a URL ends in, or "" (also for an address it cannot read)."""
    try:
        return posixpath.basename(unquote(urlsplit(url).path))
    except ValueError:
        return ""


def url_scheme(url):
    """The scheme of a URL with a host, or "" (also for an address it cannot read: an unmatched bracket)."""
    try:
        parts = urlsplit(url)
        return parts.scheme if parts.hostname else ""
    except ValueError:
        return ""


def _download_error(err):
    """A failed request as the job tells it: what went wrong, not the address (a signed one would show)."""
    return util.OperationError(gettext_noop("The file could not be downloaded: %(error)s"),
                               error=str(getattr(err, "reason", None) or type(err).__name__))


def open_download(url):
    """The final answer to a GET of url, its body not read: up to FETCH_REDIRECTS redirects followed
    by hand, each to http or https and none of their bodies read (requests reads them); the file
    asked uncompressed. Refused unless it is a 200 of an uncompressed body."""
    http = urllib3.PoolManager(timeout=FETCH_TIMEOUT, retries=False)
    for _hop in range(FETCH_REDIRECTS + 1):
        if url_scheme(url) not in ("http", "https"):
            raise util.OperationError(BAD_ADDRESS)
        try:
            answer = http.request("GET", url, headers={"Accept-Encoding": "identity"}, preload_content=False,
                                  redirect=False, decode_content=False)
        except urllib3.exceptions.HTTPError as err:
            raise _download_error(err) from None
        location = answer.headers.get("Location")
        if answer.status in (301, 302, 303, 307, 308) and location:
            answer.close()
            try:
                url = urljoin(url, location)
            except ValueError:  # a Location it cannot read
                raise util.OperationError(BAD_ADDRESS) from None
            continue
        if answer.status != 200 or answer.headers.get("Content-Encoding", "identity") != "identity":
            answer.close()
            raise util.OperationError(gettext_noop("The server answered %(status)s, not the whole file"),
                                      status=f"{answer.status} {answer.reason or ''}".strip())
        return answer
    raise util.OperationError(gettext_noop("The address is redirected more than %(count)s times"), count=FETCH_REDIRECTS)


@register
class FetchVolume(Kind):
    """A volume of a pool of files made from a file at a URL (an ISO or a disk image), streamed by
    the worker into the pool through libvirt; the server must tell the file's size. A cancel or a
    failure deletes what it wrote."""

    name = "volume.fetch"
    label = gettext_noop("Download volume")
    cancellable = True
    progress_bytes = True

    def normalize(self, raw):
        url = str(raw["url"]).strip()
        return {"compute": int(raw["compute"]), "pool": str(raw["pool"]), "url": url,
                "name": str(raw.get("name") or "").strip() or url_file_name(url)}

    def validate(self, user, params):
        if not user.is_superuser:
            raise PermissionDenied
        if url_scheme(params["url"]) not in ("http", "https"):
            raise util.OperationError(BAD_ADDRESS)
        if not VOLUME_NAME.fullmatch(params["name"]) or params["name"] in (".", ".."):
            raise util.OperationError(gettext_noop("A volume's name is letters, digits, '.', '_' and '-'"))

    def plan(self, user, params):
        compute, stg = _storage(params)
        if stg.get_type() not in FILE_POOL_TYPES:
            raise util.OperationError(gettext_noop("Files are downloaded into a pool of files (dir, fs, netfs)"))
        with contextlib.suppress(libvirtError):  # refused while a volume is cloned in the pool
            stg.refresh()
        if params["name"] in stg.get_volumes():
            raise util.OperationError(gettext_noop("The pool has a volume named %(name)s"), name=params["name"])
        pool = claims.pool_key(compute.pk, params["pool"])
        return Plan(claims={claims.compute_key(compute.pk): Claim.SHARED, pool: Claim.SHARED,
                            claims.volume_key(compute.pk, params["pool"], params["name"]): Claim.EXCLUSIVE},
                    resource=pool, label=f"{compute.name}/{params['pool']}", intent={"created": False})

    def precheck(self, op, ctx):
        if op.user is None or not op.user.is_active:
            raise PermissionDenied
        self.validate(op.user, op.params)
        # a volume made outside the panel since the job was queued may have taken the name
        stg = _storage(op.params)[1]
        with contextlib.suppress(libvirtError):
            stg.refresh()
        if op.params["name"] in stg.get_volumes():
            raise util.OperationError(gettext_noop("The pool has a volume named %(name)s"), name=op.params["name"])

    @staticmethod
    def _stop_if_cancelled(op):
        op.refresh_from_db(fields=["cancel_requested"])
        if op.cancel_requested:
            raise Cancelled

    def run(self, op, ctx):
        _compute, stg = _storage(op.params)
        name = op.params["name"]
        self._stop_if_cancelled(op)
        with contextlib.closing(open_download(op.params["url"])) as answer:
            size = answer.headers.get("Content-Length", "").strip(" \t")
            if not size.isdigit():
                raise util.OperationError(gettext_noop("The server does not tell the file's size"))
            size = int(size)
            if size > stg.get_size()[1]:
                raise util.OperationError(gettext_noop("The file is larger than the pool's free space"))
            # the volume is this job's from before it exists: a crash while libvirt makes it leaves it to recovery
            ctx.record_intent(created=True, done=0, total=size)
            try:
                stg.new_raw_volume(name, size)
            except BaseException:  # a name taken meanwhile: libvirt refused, nothing of another's is deleted
                ctx.record_intent(created=False)
                raise

            def chunks():
                done, checked = 0, time.monotonic()
                try:
                    for data in answer.stream(2**20, decode_content=False):
                        done += len(data)
                        if done > size:
                            raise util.OperationError(gettext_noop("The server sent more than the file's size"))
                        if time.monotonic() - checked >= 1:  # each second: a cancel seen, the progress shown
                            self._stop_if_cancelled(op)
                            ctx.record_intent(done=done)
                            checked = time.monotonic()
                        yield data
                except urllib3.exceptions.HTTPError as err:  # the connection lost, a read timeout
                    raise _download_error(err) from None

            try:
                if stg.write_volume(name, size, chunks()) != size:
                    raise util.OperationError(gettext_noop("The download ended early"))
                self._stop_if_cancelled(op)  # asked during its last second
            except BaseException as err:
                try:
                    stg.delete_volume_if_present(name)
                except Exception:  # recovery deletes it: a cancel that left the volume is not told done
                    raise util.OperationError(gettext_noop("The download stopped and its volume was not deleted")) from err
                raise
        ctx.record_intent(done=size)
        with contextlib.suppress(libvirtError):  # libvirt reads the file's format (qcow2, ...) again
            stg.refresh()
        return {}

    def progress(self, op):
        return (op.intent["done"], op.intent["total"]) if "total" in op.intent else None

    def cancel(self, op):
        """run sees the cancel within a second, between two reads."""

    def reconcile(self, op):
        if op.intent.get("created"):
            _compute, stg = _storage(op.params)
            stg.delete_volume_if_present(op.params["name"])
        return Outcome(Operation.FAILED, error=utils.say(gettext_noop("The download stopped; what it wrote was deleted")))

    def log_entry(self, op, state):
        # the address's host only: a signed address's query would show in the log
        return _log(op, state, f"download volume {op.params['name']} from {urlsplit(op.params['url']).hostname}")

