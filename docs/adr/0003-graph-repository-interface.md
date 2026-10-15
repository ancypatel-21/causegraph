# ADR 0003: Graph repository interface

## Status
Accepted (Sprint 1)

## Context
The spec requires the dependency graph to be stored "behind a repository
interface," starting in-memory or with Neo4j, but kept testable without a
real graph database (section 14, step 17). Sprint 1 does not require Neo4j.

## Decision
Define `causegraph.graph.repository.GraphRepository`, an abstract interface
with the operations the RCA engine and API actually need:

- `add_node` / `add_edge`
- `get_node(node_id)`
- `neighbors(node_id, direction, depth)` — upstream/downstream/both,
  bounded-depth traversal
- `all_nodes()` / `all_edges()`

Implement exactly one backend in Sprint 1:
`causegraph.graph.in_memory.InMemoryGraphRepository`, a plain adjacency-list
structure. The static Sprint-1 topology (5 services, 1 topic, 1 cache, 1
feature, 1 model version) is constructed once in
`causegraph.graph.topology.build_reference_topology()` and injected into the
repository at service startup.

A Neo4j-backed implementation is deferred until the graph needs to grow
beyond what fits comfortably in memory, or until live topology discovery is
added; it would implement the same `GraphRepository` interface, so no caller
changes when it lands.

## Consequences
- Unit tests and the baseline RCA algorithm depend only on the interface, so
  they never need a running database.
- Swapping in Neo4j later is additive: a new class, a factory switch, zero
  changes to `causegraph/rca` or `causegraph/api`.
