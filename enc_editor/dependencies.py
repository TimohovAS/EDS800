"""Parameters that bound each other, and the order they must be written in.

A drive checks a value against its neighbours at the moment of the write, not
at the end of a batch.  Raising EN600's reference frequency to 90 Hz is
rejected while the upper limit F01.11 still reads 50, even when the same batch
raises that limit two rows later - the table simply reached F01.01 first,
because it writes in address order.

The manuals state the relation in the printed range ("0.00Hz~upper limit
frequency"), and the profiles carry it as ``maximum_from`` / ``minimum_from``
next to the parameter (see ``tools/build_dependencies.py``).  From that this
module can:

* :func:`order_writes` - move a bound out of the way first, so the batch the
  user asked for actually goes through, and
* :func:`conflicts` - report what no ordering can fix, before the drive is
  touched at all.

Values are compared in engineering units (Hz, %, seconds) rather than raw
registers, so a bound still holds between parameters of different scale.
"""

from __future__ import annotations

import heapq
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Protocol, Sequence

from . import codecs
from .codecs import Problem

# Profile field -> which side of the range it bounds.
BOUND_FIELDS = {"minimum_from": "minimum", "maximum_from": "maximum"}


class Target(Protocol):
    """What :func:`order_writes` needs of a write target."""

    parameter: Mapping[str, Any]
    raw_value: int

    @property
    def code(self) -> str: ...


@dataclass(frozen=True)
class Dependency:
    """One parameter takes a bound from another."""

    code: str
    provider: str
    kind: str  # "minimum" or "maximum"

    @property
    def satisfied_by(self):
        """The comparison the drive enforces: value against the bound."""
        if self.kind == "maximum":
            return lambda value, bound: value <= bound
        return lambda value, bound: value >= bound


def dependencies(parameter: Mapping[str, Any]) -> tuple[Dependency, ...]:
    """The bounds ``parameter`` takes from other parameters."""
    return tuple(
        Dependency(parameter["code"], parameter[field_name], kind)
        for field_name, kind in BOUND_FIELDS.items()
        if parameter.get(field_name)
    )


def _engineering(raw: Any, parameter: Mapping[str, Any]) -> float:
    return float(raw) / (parameter.get("scale") or 1)


def _stored(
    code: str, parameters: Mapping[str, Mapping[str, Any]], loaded: Mapping[str, Any]
) -> float | None:
    """What the drive currently holds, or ``None`` if it was never read."""
    if code not in loaded or code not in parameters:
        return None
    try:
        return _engineering(loaded[code], parameters[code])
    except (TypeError, ValueError):
        return None


def _requested(targets: Iterable[Target]) -> dict[str, float]:
    return {target.code: _engineering(target.raw_value, target.parameter) for target in targets}


def order_writes(
    targets: Sequence[Target],
    parameters: Mapping[str, Mapping[str, Any]],
    loaded: Mapping[str, Any],
) -> list[Target]:
    """Reorder a write batch so every bound is in place when it is needed.

    Which parameter goes first depends on the direction the bound moves: a
    ceiling that rises has to be written before the value that needs the room,
    a ceiling that falls only after the value has come down.  Both cases are
    decided by asking which of the two orders the drive would accept.

    Parameters not covered by a rule keep their original position.
    """
    requested = _requested(targets)
    edges: list[tuple[str, str]] = []
    for target in targets:
        for dependency in dependencies(target.parameter):
            if dependency.provider not in requested:
                continue  # the bound is not moving; only conflicts() can help
            edge = _edge(dependency, requested, parameters, loaded)
            if edge is not None:
                edges.append(edge)
    return _in_dependency_order(targets, edges)


def _edge(
    dependency: Dependency,
    requested: Mapping[str, float],
    parameters: Mapping[str, Mapping[str, Any]],
    loaded: Mapping[str, Any],
) -> tuple[str, str] | None:
    """Which of the two has to be written first, ``None`` if it does not matter."""
    accepts = dependency.satisfied_by
    stored_value = _stored(dependency.code, parameters, loaded)
    stored_bound = _stored(dependency.provider, parameters, loaded)

    # Moving the bound first works while the value already in the drive stays
    # inside the new bound.
    bound_first = stored_value is not None and accepts(
        stored_value, requested[dependency.provider]
    )
    # Writing the value first works while it fits the bound as it stands.
    value_first = stored_bound is not None and accepts(
        requested[dependency.code], stored_bound
    )
    if bound_first and value_first:
        return None  # either way round is fine; leave the batch as it came
    if value_first:
        return (dependency.code, dependency.provider)
    # Covers a bound that has to widen first, and the case where nothing was
    # read: moving the bound first is what a widening batch needs.
    return (dependency.provider, dependency.code)


def _in_dependency_order(
    targets: Sequence[Target], edges: Iterable[tuple[str, str]]
) -> list[Target]:
    """Topological sort that keeps the original order wherever it is free."""
    positions = {target.code: index for index, target in enumerate(targets)}
    successors: dict[str, set[str]] = defaultdict(set)
    predecessors: dict[str, int] = defaultdict(int)
    for first, second in edges:
        if first == second or second in successors[first]:
            continue
        successors[first].add(second)
        predecessors[second] += 1

    ready = [index for index, target in enumerate(targets) if not predecessors[target.code]]
    heapq.heapify(ready)
    ordered: list[Target] = []
    while ready:
        target = targets[heapq.heappop(ready)]
        ordered.append(target)
        for successor in successors[target.code]:
            predecessors[successor] -= 1
            if not predecessors[successor]:
                heapq.heappush(ready, positions[successor])

    if len(ordered) < len(targets):
        # Rules that contradict each other must not cost the user a write:
        # append what the sort could not place, in the order it came in.
        placed = {target.code for target in ordered}
        ordered.extend(target for target in targets if target.code not in placed)
    return ordered


def conflicts(
    targets: Sequence[Target],
    parameters: Mapping[str, Mapping[str, Any]],
    loaded: Mapping[str, Any],
) -> list[tuple[str, Problem]]:
    """Values the drive will refuse whatever order they are written in.

    A bound that is part of the same batch is judged by its new value - that
    is what makes raising a limit and its dependants together legitimate.  A
    bound that is neither being written nor known is left to the drive.
    """
    requested = _requested(targets)
    found: list[tuple[str, Problem]] = []
    for target in targets:
        for dependency in dependencies(target.parameter):
            bound = requested.get(dependency.provider)
            if bound is None:
                bound = _stored(dependency.provider, parameters, loaded)
            if bound is None:
                continue
            if dependency.satisfied_by(requested[target.code], bound):
                continue
            found.append((target.code, _problem(dependency, bound, parameters)))
    return found


def _problem(
    dependency: Dependency,
    bound: float,
    parameters: Mapping[str, Mapping[str, Any]],
) -> Problem:
    provider = parameters.get(dependency.provider, {})
    scale = provider.get("scale") or 1
    unit = provider.get("unit") or ""
    return Problem(
        f"valid.{dependency.kind}_from",
        {
            "code": dependency.provider,
            "limit": codecs.format_value(round(bound * scale), provider),
            "unit": f" {unit}" if unit else "",
        },
    )
