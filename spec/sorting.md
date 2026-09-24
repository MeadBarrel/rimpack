# Sorting

Rimpack determines effective mod order from:

- module order in `modpack.yml`;
- order within each module;
- explicit `before`;
- explicit `after`;
- RimWorld load-order metadata from `About.xml`.

## Preferred/base order

The flattened module order is the user's preferred load order.

Given:

```yaml
modules:
  - modules/00_core.yml
  - modules/10_frameworks.yml
  - modules/20_gameplay.yml
```

and:

```text
00_core:
    A
    B

10_frameworks:
    C
    D

20_gameplay:
    E
```

the preferred order is:

```text
A
B
C
D
E
```

This order should remain unchanged except where constraints require movement.

A simple topological sort is not enough as it can override the user's preferred order
when it's not strictly required by the constraints. Sorter must ensure minimal reordering of the user's preferred order.

## Constraint graph

Relationships become ordering constraints.

```text
A before B
```

becomes:

```text
A -> B
```

and:

```text
A after B
```

becomes:

```text
B -> A
```

Equivalent relationships from `About.xml` are added to the same graph. Explicit and metadata-derived constraints have equal force; none may override or suppress another. Duplicate edges are deduplicated. `forceLoadBefore` and `forceLoadAfter` are ordering constraints with the same graph semantics as `loadBefore` and `loadAfter`.
