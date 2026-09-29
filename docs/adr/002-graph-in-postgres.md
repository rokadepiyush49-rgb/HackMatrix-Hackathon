# 002 — Evidence graph in PostgreSQL, algorithms in-process

**Context.** SUTRA's hot graph queries are *windowed*: k-hop neighbourhoods and
time-respecting paths bounded by Δt ≤ 72 h per hop. At MVP scale these subgraphs have
hundreds to low thousands of edges.

**Decision.** Store events and typed edges in PostgreSQL. Load windowed subgraphs
into NetworkX for cycle enumeration, community detection and path search.
Semantic matching of tickets to actions (Alibi) runs over the *candidate set* for one
access — the handful of work items for that customer in the window — so it is computed
in-process and **pgvector is not required for the MVP**.

**Consequences.** One datastore to operate and back up; algorithms are unit-testable.
When interactive multi-hop queries over billions of edges are needed, add a graph store
(Neo4j / Memgraph / TigerGraph) fed from the same events; add pgvector when cross-corpus
similarity search (not per-access candidates) becomes a requirement.
