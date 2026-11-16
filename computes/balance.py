"""Where VMs migrate: the Balance page's proposal (propose), which running
VMs to migrate so that the hosts give their running VMs about the same
share of their memory, then of their CPUs; and a bulk migration's spread
over the other hosts (spread). A host twice as large takes twice as much."""

from fractions import Fraction


def _share(load, size):
    """The load (memory KiB, vCPUs) as shares of the host's size (memory KiB, CPUs), exact."""
    return tuple(Fraction(part, max(whole, 1)) for part, whole in zip(load, size))


def _spread_of(load, size):
    """What a host adds to the sums propose lowers: each part of its load
    squared over its size. The sums are least when every host has the same
    share, as a sum of squared shares is not: it is least when a host twice
    as large has half the share."""
    return tuple(Fraction(part ** 2, max(whole, 1)) for part, whole in zip(load, size))


def propose(loads, vms, room, sizes):
    """The moves [(VM, source, target)] and the loads after them.

    loads: {host: (memory KiB, vCPUs)} that each host gives its running VMs,
    all of them, also those that cannot move. vms: the VMs that may move,
    (VM, host, memory KiB, vCPUs, the hosts it may go to). room: {host: its
    memory KiB its running and paused VMs leave}; the VMs moved to a host
    fit in it without those moved away, so the moves may run in any order.
    sizes: {host: (memory KiB, CPUs)}.

    The proposal is made twice, step by step, each step taking the move
    that most lowers the sum of the hosts' memory, then vCPUs, squared over
    their size (_spread_of): once the move that lowers it most, once the move
    that lowers it most for the memory it moves. The one that evens out the
    hosts more is taken, and of two that do it as well, the one that moves
    less memory: small VMs rather than a large one."""
    memory = {vm[0]: vm[2] for vm in vms}

    def rank(plan):
        moves, after = plan
        spreads = [_spread_of(load, sizes[host]) for host, load in after.items()]
        return tuple(sum(part[i] for part in spreads) for i in (0, 1)), sum(memory[pk] for pk, _source, _target in moves)

    return min((_steps(loads, vms, room, sizes, per_memory) for per_memory in (False, True)), key=rank)


def _steps(loads, vms, room, sizes, per_memory):
    """The moves and the loads after them, a move at a time while one lowers
    the sums (_spread_of); each VM moves at most once."""
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
                # the change of each sum: ((s - x)² - s²) / S + ((t + x)² - t²) / T
                change = tuple(
                    Fraction(size * (size - 2 * loads[source][i]), max(sizes[source][i], 1))
                    + Fraction(size * (size + 2 * loads[target][i]), max(sizes[target][i], 1))
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


def spread(loads, vms, room, sizes):
    """Where each VM of a host being emptied goes: {VM: target}, and the
    loads after. loads, room and sizes as propose's, of the hosts the VMs
    may go to. vms: (VM, memory KiB, vCPUs, whether it holds its memory (not
    shut off), the hosts it may go to).

    The largest VMs first, each to the host it may go to that has the least
    share of its memory, then of its CPUs, with it; one that holds its
    memory only where it fits the room. A shut-off VM counts too: it takes
    its memory when it starts. A VM no host takes is left out."""
    loads = {host: list(load) for host, load in loads.items()}
    room = dict(room)
    placed = {}
    for pk, ram, vcpus, holds, targets in sorted(vms, key=lambda vm: (-vm[1], -vm[2], vm[0])):
        fits = sorted(target for target in targets if not holds or ram <= room[target])
        if not fits:
            continue
        target = min(fits, key=lambda host: _share((loads[host][0] + ram, loads[host][1] + vcpus), sizes[host]))
        loads[target][0] += ram
        loads[target][1] += vcpus
        if holds:
            room[target] -= ram
        placed[pk] = target
    return placed, loads
