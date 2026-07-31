"""Derive parameter-to-parameter bounds and store them in the profiles.

Some limits are not numbers but other parameters: the manual prints F01.01 as
``0.00Hz~upper limit frequency`` and the V/F corner points as ``V/F frequency
value 0~V/F frequency value 2``.  A drive enforces those relations at the
moment of the write, so the editor has to know them - see
:mod:`enc_editor.dependencies`.

The relation is already in the printed range: each side of the ``~`` is either
a number or the *description of another parameter of the same profile*.  This
script matches the two, and writes ``minimum_from`` / ``maximum_from`` into
``parameters.json``.

    python tools/build_dependencies.py                # report only
    python tools/build_dependencies.py --write        # update the profiles

A side that is not exactly one parameter description is left alone: a missing
relation only means the editor writes in address order, while a wrong one
would reorder a write batch against the manual.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

PROFILES = Path(__file__).resolve().parent.parent / "profiles"

TILDE = re.compile(r"\s*[~～]\s*")
# Trailing prose the manuals hang off the bound: "upper limit frequency (This
# function can be used to ...)".
PARENTHETICAL = re.compile(r"\s*[(（].*$", re.DOTALL)


def normalize(text: str) -> str:
    return " ".join(str(text).split()).strip(" .,:;").lower()


def description_index(parameters: list[dict]) -> dict[str, str]:
    """Map each unambiguous parameter description to its code."""
    codes: dict[str, list[str]] = {}
    for parameter in parameters:
        codes.setdefault(normalize(parameter["description"]), []).append(parameter["code"])
    return {name: found[0] for name, found in codes.items() if len(found) == 1 and name}


def resolve(side: str, index: dict[str, str]) -> str | None:
    """The code a range side names, or ``None`` when it is a plain number."""
    candidate = normalize(side)
    if candidate in index:
        return index[candidate]
    stripped = normalize(PARENTHETICAL.sub("", candidate))
    return index.get(stripped) if stripped else None


def derive(parameter: dict, index: dict[str, str]) -> dict[str, str]:
    """The ``minimum_from`` / ``maximum_from`` a printed range implies."""
    if parameter.get("read_only"):
        return {}
    sides = TILDE.split(parameter.get("range") or "")
    if len(sides) != 2:
        return {}  # no range, or an option list that happens to contain a tilde
    found = {}
    for side, field_name in zip(sides, ("minimum_from", "maximum_from")):
        code = resolve(side, index)
        if code and code != parameter["code"]:
            found[field_name] = code
    return found


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="update parameters.json")
    arguments = parser.parse_args()

    for path in sorted(PROFILES.glob("*/parameters.json")):
        parameters = json.loads(path.read_text(encoding="utf-8"))
        index = description_index(parameters)
        found: Counter[str] = Counter()
        examples: list[str] = []
        for parameter in parameters:
            bounds = derive(parameter, index)
            for field_name in ("minimum_from", "maximum_from"):
                parameter.pop(field_name, None)
                if field_name in bounds:
                    parameter[field_name] = bounds[field_name]
                    found[bounds[field_name]] += 1
            if bounds and len(examples) < 6:
                examples.append(
                    f"{parameter['code']} -> "
                    + ", ".join(f"{name}={code}" for name, code in bounds.items())
                )

        print(f"{path.parent.name}: {sum(found.values())} bounds on {len(found)} parameters")
        for code, count in found.most_common():
            print(f"  {code}: bounds {count}")
        for example in examples:
            print(f"  e.g. {example}")
        if arguments.write:
            path.write_text(
                json.dumps(parameters, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"  updated {path}")


if __name__ == "__main__":
    main()
