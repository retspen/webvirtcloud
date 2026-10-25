"""
What each compute has given its VMs: vCPUs and memory of all VMs (a
shut-off VM takes its share again when it starts) and of the running ones,
against the host's CPUs and memory, and the free space of its active
storage pools. Read live from libvirt for the Computes page.
"""

import threading
import time
from concurrent import futures

from libvirt import VIR_CONNECT_LIST_STORAGE_POOLS_ACTIVE, VIR_DOMAIN_SHUTOFF, libvirtError

MAX_WORKERS = 8

# A libvirt call may hang: its thread outlives the page. Until it ends, its
# compute is not read again, so the threads stay at one per compute.
_reading = set()
_reading_lock = threading.Lock()


def read(compute):
    """The compute's capacity, or None when it cannot be reached. A VM that
    goes while it is read is skipped."""
    if compute.status is not True:
        return None
    conn = compute.connection
    _arch, memory_mib, cpus, *_ = conn.getInfo()
    vcpus = {"all": 0, "running": 0}
    assigned = {"all": 0, "running": 0}
    for dom in conn.listAllDomains(0):
        try:
            state, _max_memory, memory_kib, vcpu_count, _cpu_time = dom.info()
        except libvirtError:
            continue
        for share in ("all", "running") if state != VIR_DOMAIN_SHUTOFF else ("all",):
            vcpus[share] += vcpu_count
            assigned[share] += memory_kib * 1024
    pools = []
    for pool in conn.listAllStoragePools(VIR_CONNECT_LIST_STORAGE_POOLS_ACTIVE):
        try:
            _state, size, _allocation, available = pool.info()
        except libvirtError:
            continue
        pools.append((pool.name(), size, available))
    return {"cpus": cpus, "memory": memory_mib * 1024 * 1024, "vcpus": vcpus, "assigned": assigned,
            "pools": sorted(pools)}


def _read_once(compute):
    try:
        return read(compute)
    finally:
        with _reading_lock:
            _reading.discard(compute.id)


def read_all(computes, deadline=10.0):
    """{compute id: capacity} of the computes read by the deadline (seconds),
    in parallel; a compute down, failing, late, or still being read for an
    earlier page is left out."""
    with _reading_lock:
        computes = [compute for compute in computes if compute.id not in _reading]
        _reading.update(compute.id for compute in computes)
    pool = futures.ThreadPoolExecutor(max_workers=MAX_WORKERS)
    end = time.monotonic() + deadline
    try:
        reads = {pool.submit(_read_once, compute): compute.id for compute in computes}
        done, _late = futures.wait(reads, timeout=max(0, end - time.monotonic()))
        found = {}
        for future in done:
            try:
                result = future.result()
            except libvirtError:
                continue
            if result is not None:
                found[reads[future]] = result
        return found
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
        with _reading_lock:  # a read cancelled before it started ends nothing itself
            _reading.difference_update(cid for future, cid in reads.items() if future.cancelled())
