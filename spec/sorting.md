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

The sorter must protect each preferred prefix: when all items from an original
prefix have been emitted, the emitted set is exactly that prefix plus its
transitive prerequisites. A later item may enter that emitted portion only when
it is required to unlock the prefix; unrelated later items remain behind it.

Prefix protection takes priority over minimizing movement or pair reversals.
Within the constraints imposed by protected prefixes, ordering should
predictably prefer the user's supplied order. This policy does not promise a
globally minimum inversion count, cut-and-paste count, or other movement metric.

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
