"""The Balance page's proposal: which running VMs to migrate so that the
hosts give their running VMs about the same memory, then the same vCPUs."""


def propose(loads, vms, room):
    """The moves [(VM, source, target)] and the loads after them.

    loads: {host: (memory KiB, vCPUs)} that each host gives its running VMs,
    all of them, also those that cannot move. vms: the VMs that may move,
    (VM, host, memory KiB, vCPUs, the hosts it may go to). room: {host: its
    memory KiB its running and paused VMs leave}; the VMs moved to a host
    fit in it without those moved away, so the moves may run in any order.

    Each step takes the one move that most lowers the sum of the squared
    memory loads, then of the squared vCPU loads, and stops when none does:
    each VM moves at most once."""
    loads = {host: list(load) for host, load in loads.items()}
    room = dict(room)
    left, moves = sorted(vms), []
    while True:
        best = None
        for vm in left:
            pk, source, ram, vcpus, targets = vm
            for target in sorted(targets):
                if ram > room[target]:
                    continue
                # the change of each sum of squares: (s - x)² + (t + x)² - s² - t²
                change = tuple(2 * size * (loads[target][i] - loads[source][i] + size)
                               for i, size in enumerate((ram, vcpus)))
                if change < (0, 0) and (best is None or change < best[0]):
                    best = (change, vm, target)
        if best is None:
            return moves, loads
        _change, vm, target = best
        pk, source, ram, vcpus, _targets = vm
        for i, size in enumerate((ram, vcpus)):
            loads[source][i] -= size
            loads[target][i] += size
        room[target] -= ram
        left.remove(vm)
        moves.append((pk, source, target))
