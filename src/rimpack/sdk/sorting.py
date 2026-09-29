"""Deterministic, prefix-preserving topological sorting for SDK callers."""

from collections import deque
from collections.abc import Collection, Hashable, Sequence
from heapq import heapify, heappop, heappush
from typing import NamedTuple


class SortingItem[T: Hashable](NamedTuple):
    """An item and the values it must precede or follow.

    ``before`` contains items that must follow this item, while ``after``
    contains items that must precede it. Constraint references not present in
    the sorted input are ignored.
    """

    item: T
    before: Collection[T] = ()
    after: Collection[T] = ()


class CycleError(ValueError):
    """Raised when ordering constraints contain a directed cycle."""


def _record_edge(
    source: int,
    target: int,
    successors: list[set[int]],
    predecessors: list[set[int]],
) -> None:
    """Add one deduplicated indexed edge to both adjacency directions."""
    if target not in successors[source]:
        successors[source].add(target)
        predecessors[target].add(source)


def _build_adjacency[T: Hashable](
    entries: Sequence[SortingItem[T]], item_indices: dict[T, int]
) -> tuple[list[set[int]], list[set[int]]]:
    """Normalize before/after declarations to deduplicated indexed edges.

    References absent from ``item_indices`` are deliberately skipped. The
    indexed graph keeps later graph passes independent of item equality,
    hashing, and ordering behavior.
    """
    node_count = len(entries)
    successors = [set() for _ in range(node_count)]
    predecessors = [set() for _ in range(node_count)]

    for source, entry in enumerate(entries):
        for reference in entry.before:
            try:
                target = item_indices[reference]
            except KeyError:
                continue
            _record_edge(source, target, successors, predecessors)

        for reference in entry.after:
            try:
                predecessor = item_indices[reference]
            except KeyError:
                continue
            _record_edge(predecessor, source, successors, predecessors)

    return successors, predecessors


def _topological_order[T: Hashable](
    entries: Sequence[SortingItem[T]],
    successors: list[set[int]],
    predecessors: list[set[int]],
) -> list[int]:
    """Return an iterative topological order or report all blocked input items."""
    indegree = [len(incoming) for incoming in predecessors]
    ready = deque(index for index, degree in enumerate(indegree) if degree == 0)
    order: list[int] = []

    while ready:
        source = ready.popleft()
        order.append(source)
        for target in successors[source]:
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)

    if len(order) != len(entries):
        blocked = [
            entries[index].item for index, degree in enumerate(indegree) if degree > 0
        ]
        raise CycleError(
            f"Ordering constraints contain a cycle; blocked items: {blocked!r}"
        )

    return order


def _forward_kahn(
    urgency: Sequence[int],
    successors: list[set[int]],
    predecessors: list[set[int]],
) -> list[int]:
    """Build the forward candidate, preferring low urgency then input rank."""
    indegree = [len(incoming) for incoming in predecessors]
    ready: list[tuple[int, int]] = [
        (urgency[index], index) for index, degree in enumerate(indegree) if degree == 0
    ]
    # Heapify makes the initial ready-set construction linear.
    heapify(ready)
    order: list[int] = []

    while ready:
        _, source = heappop(ready)
        order.append(source)
        for target in successors[source]:
            indegree[target] -= 1
            if indegree[target] == 0:
                heappush(ready, (urgency[target], target))

    return order


def _reverse_kahn(
    successors: list[set[int]], predecessors: list[set[int]]
) -> list[int]:
    """Build a second candidate by removing latest available sinks first."""
    outdegree = [len(outgoing) for outgoing in successors]
    ready: list[int] = [-index for index, degree in enumerate(outdegree) if degree == 0]
    heapify(ready)
    removed: list[int] = []

    while ready:
        sink = -heappop(ready)
        removed.append(sink)
        for source in predecessors[sink]:
            outdegree[source] -= 1
            if outdegree[source] == 0:
                heappush(ready, -source)

    return list(reversed(removed))


def _count_inversions(indices: Sequence[int]) -> int:
    """Count reversed input-rank pairs with a coordinate-compressed Fenwick tree."""
    coordinates = {value: rank for rank, value in enumerate(sorted(indices), start=1)}
    tree = [0] * (len(indices) + 1)
    seen = 0
    inversions = 0

    for value in indices:
        position = coordinates[value]
        cursor = position
        not_greater = 0
        while cursor:
            not_greater += tree[cursor]
            cursor -= cursor & -cursor
        inversions += seen - not_greater

        cursor = position
        while cursor < len(tree):
            tree[cursor] += 1
            cursor += cursor & -cursor
        seen += 1

    return inversions


def stable_toposort[T: Hashable](
    items: Sequence[SortingItem[T]],
) -> tuple[T, ...]:
    """Return a deterministic topological order that protects preferred prefixes.

    Input position is the preferred order and constraints take precedence. A
    later item moves into an earlier prefix only when it is a transitive
    prerequisite of that prefix. Within each urgency group, this function
    selects the lower-inversion order from forward and reverse Kahn candidates;
    ties use the lexicographically smaller sequence of original positions.

    Duplicate input values raise ``ValueError`` and cyclic constraints raise
    ``CycleError``. Missing constraint references are ignored. The input and
    constraint collections are read but never mutated, and returned values are
    the original objects supplied in ``items``.
    """
    entries = tuple(items)
    item_indices: dict[T, int] = {}
    for index, entry in enumerate(entries):
        if entry.item in item_indices:
            raise ValueError("Input items must be unique.")
        item_indices[entry.item] = index

    successors, predecessors = _build_adjacency(entries, item_indices)
    if all(
        source < target
        for source, outgoing in enumerate(successors)
        for target in outgoing
    ):
        return tuple(entry.item for entry in entries)

    topological = _topological_order(entries, successors, predecessors)
    urgency = list(range(len(entries)))
    for source in reversed(topological):
        for target in successors[source]:
            urgency[source] = min(urgency[source], urgency[target])

    forward = _forward_kahn(urgency, successors, predecessors)
    reverse = _reverse_kahn(successors, predecessors)

    forward_groups: dict[int, list[int]] = {}
    reverse_groups: dict[int, list[int]] = {}
    for index in forward:
        forward_groups.setdefault(urgency[index], []).append(index)
    for index in reverse:
        reverse_groups.setdefault(urgency[index], []).append(index)

    selected: list[int] = []
    for group_urgency in sorted(forward_groups):
        forward_group = forward_groups[group_urgency]
        reverse_group = reverse_groups[group_urgency]
        if forward_group == reverse_group:
            selected.extend(forward_group)
            continue

        forward_cost = _count_inversions(forward_group)
        reverse_cost = _count_inversions(reverse_group)
        if (forward_cost, forward_group) <= (reverse_cost, reverse_group):
            selected.extend(forward_group)
        else:
            selected.extend(reverse_group)

    return tuple(entries[index].item for index in selected)
