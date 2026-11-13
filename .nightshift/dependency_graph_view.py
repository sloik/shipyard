"""Reduced dependency-graph view (SPEC-NS-KIT-003).

A pure, deterministic projection helper. Explicit ``after`` metadata may repeat a gate
for clarity (gate -> planning -> children plus gate -> each child); drawing every declared
arrow clutters the graph. ``reduce_dependency_edges`` classifies the *displayed* dependency
edges into ``kept`` and ``omitted``: an edge is omitted only when another directed path
between the same two endpoints remains in the displayed dependency projection, so on a DAG
reachability is exactly preserved.

Never rewrites metadata: inputs are not mutated and nothing is written. Parent/grouping
membership is not a dependency edge and must never be passed in as one. Callers pass only
the edges whose endpoints are currently displayed, so filtering recomputes the reduction.

Conservative handling (the diagnostic edges are never hidden):
  * a self-loop edge is kept;
  * an edge with an endpoint absent from ``nodes`` (unknown/unresolved) is kept and never
    contributes to a path;
  * every edge touching a node on a directed cycle is kept, and cyclic nodes never serve
    as the middle of an alternate path (no DAG reduction inside or through a cycle);
  * external nodes are keyed ``<project>::<id>`` so identical local ids in different
    projects cannot create a false path.

The board's embedded JavaScript (``reduceDependencyEdges`` in ``board.py``) mirrors this
algorithm; ``tests/test_dependency_graph_view.py`` runs both on the same fixtures.
"""
from __future__ import annotations

from collections import deque
from typing import Any, Iterable, Mapping


def qualified_id(node_id: Any, project: Any = None) -> str:
    """Identity used for path-finding: ``project::id`` for external nodes, else the id."""
    return f"{project}::{node_id}" if project else str(node_id)


def _node_keys(nodes: Iterable[Mapping[str, Any]] | None) -> dict[str, str] | None:
    """Map plain node id -> qualified key. Local nodes win over an external of the same id."""
    if nodes is None:
        return None
    keys: dict[str, str] = {}
    for node in nodes:
        nid = str(node.get("id"))
        external = bool(node.get("external"))
        if nid in keys and external:
            continue
        keys[nid] = qualified_id(nid, node.get("project") if external else None)
    return keys


def _endpoint(edge: Mapping[str, Any], side: str, keys: dict[str, str] | None) -> str | None:
    project = edge.get(f"{side}_project")
    raw = str(edge.get(side))
    if project:
        return qualified_id(raw, project)
    if keys is None:
        return raw
    return keys.get(raw)  # None == unknown endpoint


def reduce_dependency_edges(
    edges: Iterable[Mapping[str, Any]],
    nodes: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, list]:
    """Split dependency ``edges`` (prerequisite -> dependent) into kept and omitted.

    Returns ``{"kept": [edge, ...], "omitted": [{"edge": edge, "via": [id, ...]}, ...]}``.
    ``via`` is the shortest alternate path (qualified ids, endpoints included). Both lists
    are sorted by ``(from, to)`` so the result does not depend on input order.
    """
    edge_list = [dict(e) for e in edges]
    keys = _node_keys(nodes)

    resolved: list[tuple[dict, str | None, str | None]] = []
    adjacency: dict[str, set[str]] = {}
    for edge in edge_list:
        fk, tk = _endpoint(edge, "from", keys), _endpoint(edge, "to", keys)
        resolved.append((edge, fk, tk))
        if fk is not None and tk is not None and fk != tk:
            adjacency.setdefault(fk, set()).add(tk)

    def reach(start: str) -> set[str]:
        seen: set[str] = set()
        stack = list(adjacency.get(start, ()))
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(adjacency.get(cur, ()))
        return seen

    cyclic = {n for n in adjacency if n in reach(n)}
    dag: dict[str, list[str]] = {
        n: sorted(t for t in targets if t not in cyclic)
        for n, targets in adjacency.items()
        if n not in cyclic
    }

    def alternate_path(u: str, v: str) -> list[str] | None:
        parent: dict[str, str] = {}
        queue: deque[str] = deque()
        for w in dag.get(u, ()):
            if w != v and w not in parent:
                parent[w] = u
                queue.append(w)
        while queue:
            cur = queue.popleft()
            for nxt in dag.get(cur, ()):
                if nxt == v:
                    path = [v, cur]
                    while path[-1] != u:
                        path.append(parent[path[-1]])
                    return path[::-1]
                if nxt not in parent and nxt != u:
                    parent[nxt] = cur
                    queue.append(nxt)
        return None

    verdicts: dict[tuple[str, str], list[str] | None] = {}
    kept: list[dict] = []
    omitted: list[dict] = []
    for edge, fk, tk in resolved:
        via = None
        if fk is not None and tk is not None and fk != tk and fk not in cyclic and tk not in cyclic:
            if (fk, tk) not in verdicts:
                verdicts[(fk, tk)] = alternate_path(fk, tk)
            via = verdicts[(fk, tk)]
        if via is None:
            kept.append(edge)
        else:
            omitted.append({"edge": edge, "via": via})

    kept.sort(key=lambda e: (str(e.get("from")), str(e.get("to"))))
    omitted.sort(key=lambda o: (str(o["edge"].get("from")), str(o["edge"].get("to"))))
    return {"kept": kept, "omitted": omitted}
