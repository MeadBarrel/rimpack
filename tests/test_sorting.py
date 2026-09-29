"""Behavioral and exhaustive tests for prefix-preserving stable sorting."""

from __future__ import annotations

import random
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from itertools import permutations, product

import pytest

from rimpack.sdk.sorting import CycleError, SortingItem, stable_toposort

Edge = tuple[int, int]


@dataclass(frozen=True)
class OpaqueKey:
    """Hashable identity used to prove that values need not be orderable."""

    label: str


def _items_from_edges(
    node_count: int, edges: Iterable[Edge]
) -> tuple[SortingItem[int], ...]:
    """Translate indexed edges into before declarations for a preferred order."""
    successors: list[list[int]] = [[] for _ in range(node_count)]
    for source, target in edges:
        successors[source].append(target)
    return tuple(
        SortingItem(node, before=tuple(successors[node])) for node in range(node_count)
    )


def _text_item(
    item: str,
    before: Collection[str] = (),
    after: Collection[str] = (),
) -> SortingItem[str]:
    """Build a broadly typed string item for mixed-literal test fixtures."""
    return SortingItem(item, before=before, after=after)


def _all_oriented_graphs(node_count: int) -> Iterable[frozenset[Edge]]:
    """Yield every simple directed orientation choice for each node pair."""
    pairs = [
        (left, right)
        for left in range(node_count)
        for right in range(left + 1, node_count)
    ]
    for choices in product((0, 1, 2), repeat=len(pairs)):
        edges: set[Edge] = set()
        for (left, right), choice in zip(pairs, choices, strict=True):
            if choice == 1:
                edges.add((left, right))
            elif choice == 2:
                edges.add((right, left))
        yield frozenset(edges)


def _valid_orders(node_count: int, edges: Iterable[Edge]) -> list[tuple[int, ...]]:
    """Independently enumerate all permutations that respect every edge."""
    edge_list = tuple(edges)
    valid: list[tuple[int, ...]] = []
    for order in permutations(range(node_count)):
        positions = {node: position for position, node in enumerate(order)}
        if all(positions[source] < positions[target] for source, target in edge_list):
            valid.append(order)
    return valid


def _prefix_closures(
    node_count: int, edges: Iterable[Edge]
) -> tuple[frozenset[int], ...]:
    """Compute each preferred prefix plus its transitive prerequisites."""
    predecessors: list[list[int]] = [[] for _ in range(node_count)]
    for source, target in edges:
        predecessors[target].append(source)

    closures: list[frozenset[int]] = []
    for prefix_length in range(1, node_count + 1):
        closure = set(range(prefix_length))
        pending = list(closure)
        while pending:
            node = pending.pop()
            for predecessor in predecessors[node]:
                if predecessor not in closure:
                    closure.add(predecessor)
                    pending.append(predecessor)
        closures.append(frozenset(closure))
    return tuple(closures)


def _assert_prefix_preservation(order: Sequence[int], edges: Iterable[Edge]) -> None:
    """Assert each preferred prefix completes with exactly its ancestors."""
    edge_list = tuple(edges)
    closures = _prefix_closures(len(order), edge_list)
    positions = {node: position for position, node in enumerate(order)}
    for prefix_length, closure in enumerate(closures, start=1):
        completion = max(positions[node] for node in range(prefix_length)) + 1
        assert set(order[:completion]) == closure


def _inversion_count(order: Sequence[int]) -> int:
    """Count output pairs whose input indices are reversed."""
    return sum(
        order[left] > order[right]
        for left in range(len(order))
        for right in range(left + 1, len(order))
    )


def _reference_urgencies(node_count: int, edges: Iterable[Edge]) -> tuple[int, ...]:
    """Compute each node's earliest reachable input position by graph search."""
    successors: list[list[int]] = [[] for _ in range(node_count)]
    for source, target in edges:
        successors[source].append(target)

    urgencies: list[int] = []
    for source in range(node_count):
        reached = {source}
        pending = list(successors[source])
        while pending:
            target = pending.pop()
            if target not in reached:
                reached.add(target)
                pending.extend(successors[target])
        urgencies.append(min(reached))
    return tuple(urgencies)


def _reference_candidates(
    node_count: int, edges: Iterable[Edge], urgency: Sequence[int]
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Build both specified Kahn candidates using simple ordered ready lists."""
    edge_list = tuple(edges)
    successors: list[set[int]] = [set() for _ in range(node_count)]
    predecessors: list[set[int]] = [set() for _ in range(node_count)]
    for source, target in edge_list:
        successors[source].add(target)
        predecessors[target].add(source)

    indegree = [len(incoming) for incoming in predecessors]
    forward: list[int] = []
    while len(forward) < node_count:
        ready = [
            node
            for node in range(node_count)
            if indegree[node] == 0 and node not in forward
        ]
        source = min(ready, key=lambda node: (urgency[node], node))
        forward.append(source)
        indegree[source] = -1
        for target in successors[source]:
            indegree[target] -= 1

    remaining_outdegree = [len(outgoing) for outgoing in successors]
    removed: list[int] = []
    while len(removed) < node_count:
        sinks = [
            node
            for node in range(node_count)
            if remaining_outdegree[node] == 0 and node not in removed
        ]
        sink = max(sinks)
        removed.append(sink)
        remaining_outdegree[sink] = -1
        for source in predecessors[sink]:
            remaining_outdegree[source] -= 1
    return tuple(forward), tuple(reversed(removed))


def _reference_best_of_two(node_count: int, edges: Iterable[Edge]) -> tuple[int, ...]:
    """Select the lower-inversion Kahn candidate independently in each layer."""
    edge_list = tuple(edges)
    urgency = _reference_urgencies(node_count, edge_list)
    forward, reverse = _reference_candidates(node_count, edge_list, urgency)
    forward_groups: dict[int, list[int]] = {}
    reverse_groups: dict[int, list[int]] = {}
    for node in forward:
        forward_groups.setdefault(urgency[node], []).append(node)
    for node in reverse:
        reverse_groups.setdefault(urgency[node], []).append(node)

    result: list[int] = []
    for layer in sorted(forward_groups):
        candidates = (forward_groups[layer], reverse_groups[layer])
        result.extend(
            min(candidates, key=lambda group: (_inversion_count(group), tuple(group)))
        )
    return tuple(result)


def _assert_graph_properties(
    node_count: int,
    edges: Iterable[Edge],
    valid_orders: Sequence[tuple[int, ...]],
) -> None:
    """Check validity, exact prefix closure, idempotence, and the layer rule."""
    edge_list = tuple(edges)
    entries = _items_from_edges(node_count, edge_list)
    result = stable_toposort(entries)
    assert result in valid_orders
    assert result == _reference_best_of_two(node_count, edge_list)
    _assert_prefix_preservation(result, edge_list)
    assert (
        stable_toposort(
            tuple(
                next(entry for entry in entries if entry.item == node)
                for node in result
            )
        )
        == result
    )

    if all(source < target for source, target in edge_list):
        assert result == tuple(range(node_count))


def test_empty_singleton_unconstrained_and_valid_inputs() -> None:
    """Handle trivial inputs and preserve every already-valid preferred order."""
    assert stable_toposort(()) == ()
    only = object()
    assert stable_toposort((SortingItem(only),)) == (only,)
    assert stable_toposort(tuple(SortingItem(value) for value in (3, 1, 2))) == (
        3,
        1,
        2,
    )
    assert stable_toposort(
        (
            _text_item("A", before=("B",)),
            _text_item("B", before=("C",)),
            _text_item("C"),
        )
    ) == ("A", "B", "C")


def test_before_after_mixed_repeated_and_missing_references() -> None:
    """Normalize both directions, duplicates, and absent references correctly."""
    before_items = (
        _text_item("B"),
        _text_item("A", before=("B", "B", "missing")),
    )
    after_items = (
        _text_item("B", after=("A", "A", "missing")),
        _text_item("A"),
    )
    assert stable_toposort(before_items) == ("A", "B")
    assert stable_toposort(after_items) == ("A", "B")

    mixed = (
        _text_item("C", after=("B",)),
        _text_item("A", before=("B",)),
        _text_item("B", after=("A",), before=("C",)),
    )
    assert stable_toposort(mixed) == ("A", "B", "C")


def test_input_uniqueness_hashability_and_opaque_equal_references() -> None:
    """Reject invalid keys while retaining supplied objects for equal references."""
    with pytest.raises(ValueError, match="unique"):
        stable_toposort((_text_item("same"), _text_item("same")))
    with pytest.raises(ValueError, match="unique"):
        stable_toposort(
            (SortingItem(OpaqueKey("same")), SortingItem(OpaqueKey("same")))
        )
    with pytest.raises(TypeError):
        stable_toposort((SortingItem([]),))  # type: ignore[arg-type]

    supplied_a = OpaqueKey("a")
    supplied_b = OpaqueKey("b")
    reference_b = OpaqueKey("b")
    result = stable_toposort(
        (
            SortingItem(supplied_b, after=(OpaqueKey("a"),)),
            SortingItem(supplied_a, before=(reference_b,)),
        )
    )
    assert result == (supplied_a, supplied_b)
    assert result[0] is supplied_a
    assert result[1] is supplied_b


def test_constraint_collection_types_are_not_mutated() -> None:
    """Read list, tuple, set, and frozen-set declarations without changing them."""
    before = ["B"]
    after = ("A",)
    set_before = {"D"}
    frozen_after = frozenset({"C"})
    snapshots = (before.copy(), after, set_before.copy(), frozen_after)
    items = [
        _text_item("A", before=before),
        _text_item("B", after=after),
        _text_item("C", before=set_before),
        _text_item("D", after=frozen_after),
    ]
    item_snapshot = items.copy()

    assert stable_toposort(items) == ("A", "B", "C", "D")
    assert items == item_snapshot
    assert (before, after, set_before, frozen_after) == snapshots


def test_self_and_long_cycles_report_blocked_items_not_partial_results() -> None:
    """Reject self, short, and long cycles with downstream blocked diagnostics."""
    cycle_cases = (
        (_text_item("A", before=("A",)),),
        (_text_item("A", before=("B",)), _text_item("B", before=("A",))),
        (
            _text_item("A", before=("B",)),
            _text_item("B", before=("C",)),
            _text_item("C", before=("A",)),
        ),
    )
    for items in cycle_cases:
        with pytest.raises(CycleError):
            stable_toposort(items)

    blocked = (
        _text_item("A", before=("B",)),
        _text_item("B", before=("A", "C")),
        _text_item("C"),
        _text_item("unrelated"),
    )
    with pytest.raises(CycleError) as error:
        stable_toposort(blocked)
    message = str(error.value)
    assert "blocked items" in message
    assert message.index("'A'") < message.index("'B'") < message.index("'C'")
    assert "unrelated" not in message


def test_prefix_regressions_preserve_only_required_early_prerequisites() -> None:
    """Keep valid prefixes intact and move prerequisites without label rules."""
    assert stable_toposort(
        (
            _text_item("Core", before=("DLC",)),
            _text_item("DLC"),
            _text_item("ModA"),
            _text_item("ModB"),
        )
    ) == ("Core", "DLC", "ModA", "ModB")

    assert stable_toposort(
        (
            _text_item("Core", before=("DLC",)),
            _text_item("DLC"),
            _text_item("Mod"),
            _text_item("RequiredPatcher", before=("Core",)),
        )
    ) == ("RequiredPatcher", "Core", "DLC", "Mod")

    assert stable_toposort(
        (
            _text_item("Core", before=("DLC",)),
            _text_item("DLC", before=("Ideology",)),
            _text_item("Ideology"),
            _text_item("Mod", before=("Ideology",)),
            _text_item("FreeMod"),
        )
    ) == ("Core", "DLC", "Mod", "Ideology", "FreeMod")

    assert stable_toposort(
        (
            _text_item("Base", before=("Expansion",)),
            _text_item("Expansion", before=("Scenario",)),
            _text_item("Scenario"),
            _text_item("Helper", before=("Scenario",)),
            _text_item("Free"),
        )
    ) == ("Base", "Expansion", "Helper", "Scenario", "Free")


def test_late_prerequisites_preserve_unrelated_trailing_order() -> None:
    """Do not move unrelated tail items ahead of the prefix they do not unlock."""
    expected = ("P", "A", "B", "C", "X", "Y")
    assert (
        stable_toposort(
            (
                _text_item("A", after=("P",)),
                _text_item("B", after=("P",)),
                _text_item("C", after=("P",)),
                _text_item("X"),
                _text_item("Y"),
                _text_item("P"),
            )
        )
        == expected
    )

    assert stable_toposort(
        (
            _text_item("Core", before=("DLC",)),
            _text_item("DLC"),
            _text_item("Mod"),
            _text_item("P", before=("Core",)),
            _text_item("Q", before=("Core",)),
            _text_item("R", before=("Core",)),
        )
    ) == ("P", "Q", "R", "Core", "DLC", "Mod")


def test_five_item_forward_reverse_and_prefix_tradeoff_regressions() -> None:
    """Keep probe counterexamples for candidate quality and prefix priority."""
    forward_case = _items_from_edges(
        5,
        ((1, 0), (2, 1), (3, 0), (4, 2)),
    )
    reverse_case = _items_from_edges(
        5,
        ((1, 0), (2, 0), (3, 1), (4, 1)),
    )
    assert stable_toposort(forward_case) == (4, 2, 1, 3, 0)
    assert stable_toposort(reverse_case) == (2, 3, 4, 1, 0)

    # This fixture deliberately prefers prefix integrity to one fewer inversion.
    assert stable_toposort(
        (
            _text_item("Core", before=("DLC",)),
            _text_item("DLC"),
            _text_item("Mod"),
            _text_item("P", before=("Core",)),
            _text_item("Q", before=("Core",)),
            _text_item("R", before=("Core",)),
        )
    ) == ("P", "Q", "R", "Core", "DLC", "Mod")


def test_candidate_winners_ties_and_independent_group_choices() -> None:
    """Cover forward, reverse, lexicographic-tie, and mixed-layer selection."""
    forward_edges = {(1, 0), (2, 0), (3, 4), (4, 1)}
    forward_urgency = _reference_urgencies(5, forward_edges)
    forward, reverse = _reference_candidates(5, forward_edges, forward_urgency)
    assert _inversion_count(forward) < _inversion_count(reverse)
    assert stable_toposort(_items_from_edges(5, forward_edges)) == forward

    reverse_edges = {(1, 2), (2, 0), (3, 0), (4, 1)}
    reverse_urgency = _reference_urgencies(5, reverse_edges)
    forward, reverse = _reference_candidates(5, reverse_edges, reverse_urgency)
    assert _inversion_count(reverse) < _inversion_count(forward)
    assert stable_toposort(_items_from_edges(5, reverse_edges)) == reverse

    tie_edges = {(1, 0), (2, 0), (3, 1)}
    tie_urgency = _reference_urgencies(4, tie_edges)
    tie_forward, tie_reverse = _reference_candidates(4, tie_edges, tie_urgency)
    assert tie_forward == (2, 3, 1, 0)
    assert tie_reverse == (3, 1, 2, 0)
    assert _inversion_count(tie_forward) == _inversion_count(tie_reverse)
    assert stable_toposort(_items_from_edges(4, tie_edges)) == tie_forward

    mixed_edges = {
        (0, 1),
        (0, 3),
        (1, 3),
        (4, 3),
        (5, 3),
        (5, 4),
        (6, 3),
        (7, 5),
        (8, 2),
        (8, 3),
        (8, 5),
        (8, 7),
        (9, 2),
        (9, 5),
        (10, 5),
        (10, 8),
        (11, 0),
        (11, 4),
    }
    urgency = _reference_urgencies(12, mixed_edges)
    forward, reverse = _reference_candidates(12, mixed_edges, urgency)
    expected = (11, 0, 1, 9, 10, 8, 2, 7, 5, 4, 6, 3)
    actual = stable_toposort(_items_from_edges(12, mixed_edges))
    assert actual == expected
    assert tuple(node for node in actual if urgency[node] == 2) == tuple(
        node for node in forward if urgency[node] == 2
    )
    assert tuple(node for node in actual if urgency[node] == 3) == tuple(
        node for node in reverse if urgency[node] == 3
    )


def test_legacy_ten_item_fixture_obeys_new_prefix_rule() -> None:
    """Validate the legacy graph semantically without retaining its old exact order."""
    entries: tuple[SortingItem[int], ...] = (
        SortingItem(0, before=(1,)),
        SortingItem(1),
        SortingItem(2, after=(4,)),
        SortingItem(3),
        SortingItem(4, before=(2,), after=(5,)),
        SortingItem(5),
        SortingItem(6),
        SortingItem(7, before=(4,)),
        SortingItem(8, before=(1, 2)),
        SortingItem(9, before=(3, 6), after=(1,)),
    )
    edges: set[Edge] = set()
    for entry in entries:
        edges.update((entry.item, target) for target in entry.before)
        edges.update((source, entry.item) for source in entry.after)

    result = stable_toposort(entries)
    positions = {node: position for position, node in enumerate(result)}
    assert all(positions[source] < positions[target] for source, target in edges)
    _assert_prefix_preservation(result, edges)
    assert (
        stable_toposort(
            tuple(
                next(entry for entry in entries if entry.item == node)
                for node in result
            )
        )
        == result
    )


def test_exhaustive_labelled_dags_through_four_nodes() -> None:
    """Check all small DAGs against enumerated linear extensions and closures."""
    for node_count in range(1, 5):
        for edges in _all_oriented_graphs(node_count):
            valid_orders = _valid_orders(node_count, edges)
            if not valid_orders:
                continue
            _assert_graph_properties(node_count, edges, valid_orders)

            base = stable_toposort(_items_from_edges(node_count, edges))
            # Reordering and duplicating declarations must not change the graph.
            reordered_constraints = tuple(
                SortingItem(
                    node,
                    before=tuple(
                        reversed(
                            tuple(target for source, target in edges if source == node)
                        )
                    )
                    * 2,
                )
                for node in range(node_count)
            )
            assert stable_toposort(reordered_constraints) == base

            # Declare edges through before or after without changing output.
            mixed = tuple(
                SortingItem(
                    node,
                    before=tuple(
                        target
                        for source, target in edges
                        if source == node and (source + target) % 2 == 0
                    ),
                    after=tuple(
                        source
                        for source, target in edges
                        if target == node and (source + target) % 2 != 0
                    ),
                )
                for node in range(node_count)
            )
            assert stable_toposort(mixed) == base

            # Add every redundant transitive edge, exercising closure invariance.
            reachability = [set() for _ in range(node_count)]
            for source, target in edges:
                reachability[source].add(target)
            for source in range(node_count):
                pending = list(reachability[source])
                while pending:
                    target = pending.pop()
                    for descendant in reachability[target]:
                        if descendant not in reachability[source]:
                            reachability[source].add(descendant)
                            pending.append(descendant)
            closure_edges = {
                (source, target)
                for source, descendants in enumerate(reachability)
                for target in descendants
            }
            assert stable_toposort(_items_from_edges(node_count, closure_edges)) == base


def test_fixed_seed_larger_dag_samples() -> None:
    """Check bounded random DAGs with independent topological enumeration."""
    rng = random.Random(391_2026)
    for node_count in range(5, 8):
        for _ in range(12):
            hidden_order = list(range(node_count))
            rng.shuffle(hidden_order)
            edges = {
                (hidden_order[left], hidden_order[right])
                for left in range(node_count)
                for right in range(left + 1, node_count)
                if rng.random() < 0.24
            }
            valid_orders = _valid_orders(node_count, edges)
            assert valid_orders
            _assert_graph_properties(node_count, edges, valid_orders)


def test_several_thousand_node_sparse_and_chain_smoke_cases() -> None:
    """Exercise iterative traversal and sparse graph handling at scale."""
    chain_size = 3_000
    chain = tuple(
        SortingItem(node, before=(node - 1,) if node else ())
        for node in range(chain_size)
    )
    assert stable_toposort(chain) == tuple(reversed(range(chain_size)))

    sparse_size = 4_000
    sparse = tuple(
        SortingItem(
            node,
            before=(0,) if node >= sparse_size - 4 else (),
        )
        for node in range(sparse_size)
    )
    assert stable_toposort(sparse) == (
        *range(sparse_size - 4, sparse_size),
        0,
        *range(1, sparse_size - 4),
    )
