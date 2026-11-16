"""The Balance page's proposal: which running VMs to migrate so that the
hosts give their running VMs about the same memory, then the same vCPUs."""


def propose(loads, vms, room):
    """The moves [(VM, source, target)] and the loads after them.

    loads: {host: (memory KiB, vCPUs)} that each host gives its running VMs,
    all of them, also those that cannot move. vms: the VMs that may move,
    (VM, host, memory KiB, vCPUs, the hosts it may go to). room: {host: its
    memory KiB its running and paused VMs leave}; the VMs moved to a host
    fit in it without those moved away, so the moves may run in any order.

    The proposal is made twice, step by step, each step taking the move
    that most lowers the sum of the squared memory loads, then of the
    squared vCPU loads: once the move that lowers it most, once the move
    that lowers it most for the memory it moves. The one that evens out the
    hosts more is taken, and of two that do it as well, the one that moves
    less memory: small VMs rather than a large one."""
    sizes = {vm[0]: vm[2] for vm in vms}

    def rank(plan):
        moves, after = plan
        squares = tuple(sum(load[i] ** 2 for load in after.values()) for i in (0, 1))
        return squares, sum(sizes[pk] for pk, _source, _target in moves)

    return min((_steps(loads, vms, room, per_memory) for per_memory in (False, True)), key=rank)


def _steps(loads, vms, room, per_memory):
    """The moves and the loads after them, a move at a time while one lowers
    the sums of squares; each VM moves at most once."""
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
                if change >= (0, 0):
                    continue
                gain = (change[0] / ram, change[1]) if per_memory and ram else change
                if best is None or gain < best[0]:
                    best = (gain, vm, target)
        if best is None:
            return moves, loads
        _gain, vm, target = best
        pk, source, ram, vcpus, _targets = vm
        for i, size in enumerate((ram, vcpus)):
            loads[source][i] -= size
            loads[target][i] += size
        room[target] -= ram
        left.remove(vm)
        moves.append((pk, source, target))
