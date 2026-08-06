#!/usr/bin/env python3
"""Find every user-facing literal the companion GUI puts through Qt.

The catalogue source list used to be a hand-written tuple, which is why it
held 21 strings against a window that shows hundreds: nothing connected the
tuple to the code, so every string added after it was written simply never
reached a translator, while the catalogues still reported themselves whole.

This walks the GUI's syntax tree instead.

The part that matters is that the set of translating calls is DISCOVERED, not
listed. `tr()` and `make_label()` are the roots, but most strings never touch
them directly — they are passed to a helper like `_make_tool_button(text)` or
`_make_page_header(title, subtitle)`, which forwards the argument onward. A
hand-written list of those helpers and their argument positions would drift
exactly the way the original tuple did, so instead the forwarding functions
are found by fixpoint: any function that passes one of its own parameters
into a known translating position becomes a translating call itself, at that
parameter's position.

`self` is dropped from the offsets, because a bound call site does not pass
it. f-strings and names are skipped: a string assembled at runtime cannot be
a catalogue key, and pretending otherwise fills the catalogue with entries no
lookup can ever match.
"""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUI_SOURCES = (
    ROOT / "astra_downloader" / "gui.py",
)

# The calls that translate their first argument outright. Everything else is
# derived from these.
ROOT_TRANSLATING_CALLS = {"tr": (0,), "make_label": (0,)}

# Literals that reach Qt but must not be translated, and why. Kept explicit
# rather than filtered by a rule, so adding one is a decision someone made
# rather than a side effect of a clever pattern.
NOT_TRANSLATABLE = {
    # The product name. Translating a brand is how you get bug reports about
    # an app the user cannot find again.
    "ASTRA DOWNLOADER",
    # Status dots and separators. There is nothing to translate, and giving a
    # translator a bullet to render invites one that breaks the layout.
    "•",
    "●",
}


def _literal(node):
    """The string a node represents, or None if it is not a plain literal."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _called_name(node):
    """The bare name of whatever a Call node calls."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def discover_translating_calls(tree):
    """Map every translating callable to the argument positions it translates.

    Grows from ROOT_TRANSLATING_CALLS by fixpoint, so a helper that forwards
    into another helper is found too.
    """
    table = {name: set(indices)
             for name, indices in ROOT_TRANSLATING_CALLS.items()}
    functions = [node for node in ast.walk(tree)
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    changed = True
    while changed:
        changed = False
        for function in functions:
            names = [argument.arg for argument in function.args.args]
            # A bound call site passes no `self`, so the caller's positions
            # are shifted by one wherever it is present.
            offset = 1 if names and names[0] == "self" else 0
            forwarded = set()
            for inner in ast.walk(function):
                if not isinstance(inner, ast.Call):
                    continue
                positions = table.get(_called_name(inner))
                if not positions:
                    continue
                for position in positions:
                    if position >= len(inner.args):
                        continue
                    argument = inner.args[position]
                    if isinstance(argument, ast.Name) and argument.id in names:
                        index = names.index(argument.id) - offset
                        if index >= 0:
                            forwarded.add(index)
            if forwarded - table.get(function.name, set()):
                table.setdefault(function.name, set()).update(forwarded)
                changed = True
    return {name: tuple(sorted(indices)) for name, indices in table.items()}


def extract_from_source(text):
    """Return the translatable literals in one Python source file, in order."""
    tree = ast.parse(text)
    table = discover_translating_calls(tree)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        positions = table.get(_called_name(node))
        if not positions:
            continue
        for position in positions:
            if position >= len(node.args):
                continue
            value = _literal(node.args[position])
            if value and value.strip() and value not in NOT_TRANSLATABLE:
                found.append(value)
    return found


def extract_all(paths=GUI_SOURCES):
    """Every translatable literal across the GUI sources, deduplicated."""
    seen = []
    for path in paths:
        for value in extract_from_source(Path(path).read_text(encoding="utf-8")):
            if value not in seen:
                seen.append(value)
    return seen


def main():
    """Write the extracted strings as UTF-8 JSON.

    Deliberately not printed: the Windows console is cp1252 and several of
    these strings carry a bullet or an ellipsis, so printing them raises
    UnicodeEncodeError and the tool looks broken when it is not.
    """
    import json

    strings = extract_all()
    destination = ROOT / "build" / "companion-translatable-strings.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(strings, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"{len(strings)} translatable strings -> {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
