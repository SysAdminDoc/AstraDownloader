#!/usr/bin/env python3
"""Find every user-facing literal the companion puts through Qt.

The catalogue source list used to be a hand-written tuple, which is why it
held 21 strings against a window that shows hundreds: nothing connected the
tuple to the code, so every string added after it was written simply never
reached a translator, while the catalogues still reported themselves whole.

This walks the GUI's syntax tree instead and also reads the marked recovery
catalogues owned by the download and health modules, and the notes in the
site registry. Those modules must not depend on Qt, so their literals are
translated at the GUI boundary.

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
it. f-strings are skipped: a string assembled at runtime cannot be a
catalogue key, and pretending otherwise fills the catalogue with entries no
lookup can ever match. Simple names used as loop labels are resolved back to
their literal tuple/list values, so a picker built from a constant sequence is
still visible to the catalogue gate.
"""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILES = (
    ROOT / "astra_downloader" / "gui.py",
    ROOT / "astra_downloader" / "gui_support.py",
    ROOT / "astra_downloader" / "gui_download_page.py",
    ROOT / "astra_downloader" / "gui_history_page.py",
    ROOT / "astra_downloader" / "gui_site_logins_page.py",
    ROOT / "astra_downloader" / "gui_sites_page.py",
    ROOT / "astra_downloader" / "gui_subscriptions_page.py",
    ROOT / "astra_downloader" / "gui_extension_page.py",
    ROOT / "astra_downloader" / "gui_settings_page.py",
    ROOT / "astra_downloader" / "setup_dialog.py",
    ROOT / "astra_downloader" / "download.py",
    ROOT / "astra_downloader" / "health.py",
    ROOT / "astra_downloader" / "sites.py",
    ROOT / "astra_downloader" / "config.py",
)
# Retain the old name for callers that used the extractor as a small library.
GUI_SOURCES = SOURCE_FILES

# The calls that translate their first argument outright. Everything else is
# derived from these. Placeholder examples are intentionally not included:
# timestamps, URLs, field syntax, and sample paths are data, not prose.
ROOT_TRANSLATING_CALLS = {
    "tr": (0,),
    "make_label": (0,),
    "tr_format": (0,),
    # These Qt methods are translated at their call sites below. Listing them
    # here lets the fixpoint follow an accessible name or tooltip passed
    # through a helper such as `_add_settings_number`.
    "setAccessibleName": (0,),
    "setAccessibleDescription": (0,),
    "setToolTip": (0,),
    "setText": (0,),
    "setWindowTitle": (0,),
    "setPlaceholderText": (0,),
    "addAction": (0,),
    "addButton": (0,),
    "addItem": (0,),
    "addTab": (1,),
    "showMessage": (1,),
    "getExistingDirectory": (1,),
    "getOpenFileName": (1,),
    "getSaveFileName": (1,),
}

RUNTIME_TEXT_ASSIGNMENTS = {
    "DOWNLOAD_FAILURE_RECOVERY",
    "SABR_LIMITED_NOTICE",
    "MANAGED_BINARY_ANTIVIRUS_ADVICE",
    "_PRIVATE_NETWORK_REFUSAL",
}
# Dicts whose every string value is user-facing: the reasons a link is
# rejected. They stay English in logs and API responses, and the GUI
# translates one where it shows it (describe_rejected_links).
RUNTIME_TEXT_TABLES = {"_URL_INPUT_MESSAGES", "MEDIA_URL_BLOCK_MESSAGES"}
RUNTIME_TEXT_FIELDS = {"error", "advice", "next_action"}
# Keyword arguments that carry user-facing text into a registry row. The
# Sites page renders a profile's auth_note and notes through make_label, and a
# failure shows a profile's note through tr(), but sites.py is a stdlib-only
# leaf, so neither call is visible here. Without this every note rendered
# English inside an otherwise translated page.
RUNTIME_TEXT_KEYWORDS = {"_profile": {"auth_note", "notes"}}

# Literals that reach Qt but must not be translated, and why. Kept explicit
# rather than filtered by a rule, so adding one is a decision someone made
# rather than a side effect of a clever pattern.
NOT_TRANSLATABLE = {
    # The product name. Translating a brand is how you get bug reports about
    # an app the user cannot find again.
    "ASTRA DOWNLOADER",
    # Tool names on the readiness rows. They name programs a user installs,
    # updates and searches for under exactly that name.
    "yt-dlp",
    "FFmpeg",
    # Status dots and separators. There is nothing to translate, and giving a
    # translator a bullet to render invites one that breaks the layout.
    "•",
    "●",
    # Input examples and syntax are data, not translatable prose.
    "0:00",
    "1:30",
    "YYYY-MM-DD",
    "https://www.youtube.com/@channel or playlist URL",
    "192.0.2.10",
    "US or 203.0.113.0/24",
    "https://proxy.example:8080",
    "https://hooks.example.com/astra",
    "%(title)s.%(ext)s",
    "en,es",
    "today-30days",
    "*-30",
    "*from-url",
    "inf",
    "--",
    "A",
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


def _runtime_literals(tree):
    """Return marked user-facing literals owned by non-GUI modules."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            keywords = RUNTIME_TEXT_KEYWORDS.get(_called_name(node), ())
            for keyword in node.keywords:
                literal = _literal(keyword.value) if keyword.arg in keywords else None
                if literal and literal.strip():
                    found.append(literal)
            continue
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(
            isinstance(target, ast.Name) and target.id in RUNTIME_TEXT_TABLES
            for target in targets
        ) and isinstance(node.value, ast.Dict):
            for child in node.value.values:
                literal = _literal(child)
                if literal:
                    found.append(literal)
            continue
        if not any(
            isinstance(target, ast.Name) and target.id in RUNTIME_TEXT_ASSIGNMENTS
            for target in targets
        ):
            continue
        value = node.value
        if isinstance(value, ast.Dict):
            for mapping in ast.walk(value):
                if not isinstance(mapping, ast.Dict):
                    continue
                for key, child in zip(mapping.keys, mapping.values):
                    if _literal(key) not in RUNTIME_TEXT_FIELDS:
                        continue
                    literal = _literal(child)
                    if literal:
                        found.append(literal)
        else:
            for child in ast.walk(value):
                literal = _literal(child)
                if literal:
                    found.append(literal)
    return found


def _static_assignments(tree):
    """Collect simple constant assignments for loop-label resolution."""
    assignments = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                assignments.setdefault(target.id, []).append(node.value)
    return assignments


def _static_sequence(node, assignments, seen=None):
    """Return literal sequence elements represented by a simple expression."""
    seen = set() if seen is None else seen
    if isinstance(node, ast.Name):
        if node.id in seen:
            return []
        seen.add(node.id)
        elements = []
        for value in assignments.get(node.id, ()):
            elements.extend(_static_sequence(value, assignments, seen.copy()))
        return elements
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return list(node.elts)
    if isinstance(node, ast.IfExp):
        return (
            _static_sequence(node.body, assignments, seen.copy())
            + _static_sequence(node.orelse, assignments, seen.copy())
        )
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice):
        # A slice holds some rows of its table. Any of them can come through,
        # so every row is a candidate, as in a loop over the whole table. The
        # Download page lays its readiness rows out three to a line this way.
        return _static_sequence(node.value, assignments, seen)
    if isinstance(node, ast.Call) and _called_name(node) == "enumerate" and node.args:
        # enumerate() pairs each element with its index: (index, element).
        return [
            ast.Tuple(elts=[ast.Constant(value=None), element], ctx=ast.Load())
            for element in _static_sequence(node.args[0], assignments, seen)
        ]
    return []


def _static_string_values(node, assignments, seen=None):
    """Resolve strings from a literal or a name bound to literals."""
    seen = set() if seen is None else seen
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.Name):
        if node.id in seen:
            return []
        seen.add(node.id)
        values = []
        for value in assignments.get(node.id, ()):
            values.extend(_static_string_values(value, assignments, seen.copy()))
        return values
    if isinstance(node, ast.IfExp):
        return (
            _static_string_values(node.body, assignments, seen.copy())
            + _static_string_values(node.orelse, assignments, seen.copy())
        )
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        values = []
        for child in node.elts:
            values.extend(_static_string_values(child, assignments, seen.copy()))
        return values
    return []


def _bind_loop_target(target, elements, assignments, bindings):
    """Bind one ``for`` target, unpacking nested tuples like Python does."""
    if isinstance(target, ast.Name):
        values = []
        for element in elements:
            values.extend(_static_string_values(element, assignments))
        if values:
            bindings.setdefault(target.id, []).extend(values)
        return
    if not isinstance(target, (ast.Tuple, ast.List)):
        return
    for index, child in enumerate(target.elts):
        parts = [
            element.elts[index] for element in elements
            if isinstance(element, (ast.Tuple, ast.List)) and index < len(element.elts)
        ]
        _bind_loop_target(child, parts, assignments, bindings)


def _loop_string_bindings(tree, assignments):
    """Map simple ``for`` target names to their constant string choices."""
    bindings = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.For, ast.AsyncFor)):
            continue
        elements = _static_sequence(node.iter, assignments)
        _bind_loop_target(node.target, elements, assignments, bindings)
    return bindings


def extract_from_source(text, translating_calls=None):
    """Return the translatable literals in one Python source file, in order."""
    tree = ast.parse(text)
    table = (discover_translating_calls(tree)
             if translating_calls is None else translating_calls)
    assignments = _static_assignments(tree)
    loop_bindings = _loop_string_bindings(tree, assignments)
    found = _runtime_literals(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        positions = table.get(_called_name(node))
        if not positions:
            continue
        for position in positions:
            if position >= len(node.args):
                continue
            argument = node.args[position]
            values = []
            value = _literal(argument)
            if value is not None:
                values.append(value)
            if isinstance(argument, ast.Name):
                values.extend(loop_bindings.get(argument.id, ()))
            for candidate in values:
                if (candidate and candidate.strip()
                        and candidate not in NOT_TRANSLATABLE):
                    found.append(candidate)
    return found


def extract_all(paths=GUI_SOURCES):
    """Every translatable literal across the GUI sources, deduplicated."""
    texts = [Path(path).read_text(encoding="utf-8") for path in paths]
    # Page mixins live in separate modules from the composition root, while
    # their controls still call helpers such as ``_make_page_header`` and
    # ``_make_tool_button``. Discover the forwarding fixpoint across the
    # complete GUI boundary so extracting a page does not lose its labels.
    trees = [ast.parse(text) for text in texts]
    combined = ast.Module(
        body=[node for tree in trees for node in tree.body],
        type_ignores=[],
    )
    translating_calls = discover_translating_calls(combined)
    seen = []
    for text in texts:
        for value in extract_from_source(text, translating_calls):
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
