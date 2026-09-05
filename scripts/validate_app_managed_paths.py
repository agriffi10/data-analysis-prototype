"""Refuse an app-managed folder path declared or constructed outside its owner, in either tree.

Three folders — ``athenaresults/``, ``archive/`` (the user's receipt folder) and ``shared_tables/``
— are about to move under a real ``system_settings/`` prefix. Nearly every rule about them was
anchored at depth one as ``f"{root}{name}/"`` or ``` `${rootPrefix}${name}/` ```, which a move to
depth two leaves silently not matching. The names are now declared once per tree and every anchored
construction goes through one builder; this sweep is what keeps it that way, because a new literal
or a new hand-built prefix is exactly the kind of change that applies green and fails later.

**Scoped to path construction and declaration, never to the word.** ``archive`` names three facts
in this repository and is also a mode, a service name and twenty user-facing sentences; a sweep
that flagged the word would drag the wording modules across the ``cpcommon`` fence. So the Python
rules parse rather than grep, and the TypeScript rules run over source with its comments removed.

Python (AST), every shipped module under ``lambdas/`` — tests, ``conftest.py`` and ``fakes.py``
excluded, the two owners excluded:
  (a) a string constant equal to ``athenaresults`` or ``shared_tables``, with or without a leading or
      trailing slash, or equal to ``archive/`` or ``/archive/`` — a declaration (a docstring or a sentence merely
      containing the word is not EQUAL to it, so prose is never flagged);
  (b) an f-string whose literal parts carry ``<name>/`` at the start or after a ``/``: a construction;
  (c) ``"archive"`` as the value of a module-level assignment: a declaration;
  (d) ``"archive"`` as an element of a list, tuple or set literal that also holds another
      app-managed folder name: a declaration (a membership list is a path fact);
  (e) an f-string placing one of the owner's exported names (imported, or as an attribute) directly
      before a ``/`` that continues a path: a construction — ``f"{RECEIPT_FOLDER}/ is read-only"``
      is wording, told apart by the whitespace;
  (f) a concatenation ``root + RECEIPT_FOLDER + "/"`` with the same tail: a construction.
  Deliberately not flagged: ``service="archive"`` and any other call argument, dict keys and
  values, ``frozenset({"archive", "restore"})``, and prose that merely contains the word.

TypeScript (regex over comment-stripped source), every module under ``apps/portal/src`` — tests,
``src/test/`` and generated files excluded, the owner excluded:
  (a) a quoted literal exactly ``athenaresults`` or ``shared_tables``, with or without a leading or
      trailing slash, or ``archive/`` / ``/archive/``: a declaration. A bare ``'archive'`` is a
      declaration only beside another app-managed name in the same file (a membership list) or as a
      module-level ``const`` — a typed mode ``'archive' | 'restore'`` or a ``kind === 'archive'`` is not;
  (b) a template segment ``${…}<name>/``, ``${…}/<name>/`` or ``${<OWNER_NAME>}/``, or a
      concatenation ``<OWNER_NAME> + '/'``: a construction.
  Comments are removed first, and regex literals with them, so ``/^https:\\/\\//`` is neither a
      comment nor a string.
  Refusal-table keys are unquoted identifiers and invisible by design; Help copy names these
  folders in prose, which stays where it is.

Exit ``0`` when the tree is clean, ``1`` with one line per finding — ``path:line: <folder>
<declared|constructed> outside its owner (<rule>)`` — and ``2`` on a hard error: an owner file
missing, or a tree with nothing to sweep, because a sweep over nothing is not a clean sweep.
``ROOT`` is derived from this file's location and takes no override, so a copy of this script
inside a fixture tree sweeps that tree (``validate_app_managed_paths_test.py``).

Attributes:
  ROOT: The repository root.
  PY_OWNERS: The two Python files allowed to spell an app-managed folder — the shared names and
    builders, and the archive plane's own admin-bucket scratch prefix, which is the third fact of
    the word ``archive`` and stays in its domain layer.
  TS_OWNER: The one TypeScript file allowed to spell one.
  UNAMBIGUOUS: The names that mean a folder wherever they appear as a string.
  OVERLOADED: The name that is also a mode and a service, flagged only in path-shaped positions.
  MANAGED_NAMES: Every app-managed folder name, moving or not — the company that makes a bare
    ``"archive"`` in a collection literal a path fact under rule (d).
  OWNER_IDENTIFIERS: The names both owners export (and the ``ARCHIVE_FOLDER`` alias the file-ops
    layer keeps), which the imported-name rules recognise in an f-string, a template or a
    concatenation so that ``${root}${ARCHIVE_FOLDER}/`` and ``root + RECEIPT_FOLDER + "/"`` are
    seen as constructions.
"""

import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

PY_OWNERS = (
    "lambdas/control-plane-common/cpcommon/app_managed.py",
    "lambdas/archive-common/arcommon/plan.py",
)
TS_OWNER = "apps/portal/src/lib/appManagedPaths.ts"

UNAMBIGUOUS = ("athenaresults", "shared_tables")
OVERLOADED = "archive"
MOVING = (*UNAMBIGUOUS, OVERLOADED)
MANAGED_NAMES = frozenset(
    {*MOVING, "user_settings", "saved_queries", "_data-quality-reports", "shared_files", "_directory", "_config", "_fc-work"}
)
OWNER_IDENTIFIERS = ("ATHENA_RESULTS_FOLDER", "ARCHIVE_FOLDER", "SHARED_TABLES_FOLDER", "RECEIPT_FOLDER", "VAULT_ARCHIVE_SEGMENT")

_PY_EXCLUDED_PREFIXES = ("test_", "conftest.", "fakes.")
_SEGMENT = re.compile(r"(?:^|/)(athenaresults|archive|shared_tables)/")
_TS_LITERAL = re.compile(r"""(['"`])/?(athenaresults|archive|shared_tables)/?\1""")
_TS_TEMPLATE_SEGMENT = re.compile(r"\$\{[^}]*\}/?(athenaresults|archive|shared_tables)/")
_TS_TEMPLATE_IDENT = re.compile(r"\$\{(" + "|".join(OWNER_IDENTIFIERS) + r")\}/")
_IDENT_TO_NAME = {
    "ATHENA_RESULTS_FOLDER": "athenaresults",
    "ARCHIVE_FOLDER": "archive",
    "SHARED_TABLES_FOLDER": "shared_tables",
    "RECEIPT_FOLDER": "archive",
    "VAULT_ARCHIVE_SEGMENT": "archive",
}
_TS_CONCAT_IDENT = re.compile(r"\b(" + "|".join(OWNER_IDENTIFIERS) + r")\s*\+\s*['\"`]/")
_TS_MODULE_LEVEL_ARCHIVE = re.compile(r"^\s*(?:export\s+)?const\s+\w+(?:\s*:[^=]+)?\s*=\s*(['\"`])archive\1")
_TS_SIBLING = re.compile(
    r"(['\"`])(athenaresults|shared_tables|user_settings|saved_queries|_data-quality-reports|shared_files|_directory|_config|_fc-work)\1"
)
_REGEX_PRECEDERS = frozenset("=(,:[!&|?{};")


def _finding(rel: str, line: int, folder: str, verb: str, rule: str) -> str:
    """Formats one finding the way the corpus asserts on it.

    Args:
      rel: The file, relative to the root.
      line: The 1-based line.
      folder: Which of the three folders.
      verb: ``declared`` or ``constructed``.
      rule: The rule that fired, for the reader.

    Returns:
      One output line.

    Raises:
      None.
    """
    return f"{rel}:{line}: {folder} {verb} outside its owner ({rule})"


def _python_modules() -> list[pathlib.Path]:
    """Every shipped Python module under ``lambdas/``, owners included, tests excluded.

    Args:
      None.

    Returns:
      The sorted module paths.

    Raises:
      None.
    """
    return sorted(
        path
        for path in (ROOT / "lambdas").rglob("*.py")
        if not path.name.startswith(_PY_EXCLUDED_PREFIXES) and "__pycache__" not in path.parts
    )


def _imported_name(node: ast.AST) -> str | None:
    """Returns the owner identifier a name or attribute node refers to, or None.

    Args:
      node: The expression in the path position.

    Returns:
      The identifier (``RECEIPT_FOLDER``, ``app_managed.RECEIPT_FOLDER`` → ``RECEIPT_FOLDER``) when
      it is one the owner exports, else None.

    Raises:
      None.
    """
    if isinstance(node, ast.Name) and node.id in OWNER_IDENTIFIERS:
        return node.id
    if isinstance(node, ast.Attribute) and node.attr in OWNER_IDENTIFIERS:
        return node.attr
    return None


def _is_path_tail(value: object) -> bool:
    """Reports whether a string that follows a folder name continues a PATH rather than a sentence.

    ``"/"`` and ``"/x"`` do; ``"/ is read-only"`` does not — a refusal's wording quotes the folder
    with a slash and then keeps talking, and the whitespace is what tells the two apart.

    Args:
      value: The constant following the name.

    Returns:
      True for a path continuation.

    Raises:
      None.
    """
    return isinstance(value, str) and value.startswith("/") and not any(c.isspace() for c in value)


def _sweep_python_module(path: pathlib.Path) -> list[str]:
    """Applies the four Python rules to one module.

    Args:
      path: The module.

    Returns:
      The findings, in source order.

    Raises:
      None.
    """
    rel = path.relative_to(ROOT).as_posix()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
    findings: list[str] = []
    module_level_values = {
        id(node.value)
        for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None
    }
    collection_elements: dict[int, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            names = {e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
            for element in node.elts:
                collection_elements[id(element)] = names
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value
            bare = text.strip("/")
            if bare in UNAMBIGUOUS and text in (bare, f"{bare}/", f"/{bare}/"):
                findings.append(_finding(rel, node.lineno, bare, "declared", "a string constant names the folder"))
            elif text in (f"{OVERLOADED}/", f"/{OVERLOADED}/"):
                findings.append(_finding(rel, node.lineno, OVERLOADED, "declared", "a slash-suffixed string names the folder"))
            elif text == OVERLOADED:
                if id(node) in module_level_values:
                    findings.append(_finding(rel, node.lineno, OVERLOADED, "declared", "a module-level assignment"))
                elif id(node) in collection_elements and (collection_elements[id(node)] - {OVERLOADED}) & MANAGED_NAMES:
                    findings.append(_finding(rel, node.lineno, OVERLOADED, "declared", "beside another app-managed name in a collection"))
        elif isinstance(node, ast.JoinedStr):
            literal = "".join(part.value for part in node.values if isinstance(part, ast.Constant) and isinstance(part.value, str))
            for match in _SEGMENT.finditer(literal):
                findings.append(_finding(rel, node.lineno, match.group(1), "constructed", "an f-string builds the prefix"))
            for part, following in zip(node.values, node.values[1:], strict=False):
                name = _imported_name(part.value) if isinstance(part, ast.FormattedValue) else None
                if name and isinstance(following, ast.Constant) and _is_path_tail(following.value):
                    findings.append(_finding(rel, node.lineno, _IDENT_TO_NAME[name], "constructed", "an f-string builds the prefix from an imported name"))
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add) and isinstance(node.right, ast.Constant):
            left = node.left.right if isinstance(node.left, ast.BinOp) else node.left
            name = _imported_name(left)
            if name and _is_path_tail(node.right.value):
                findings.append(_finding(rel, node.lineno, _IDENT_TO_NAME[name], "constructed", "a concatenation builds the prefix from an imported name"))
    return findings


def _strip_ts_comments(source: str) -> str:
    """Blanks comments while preserving strings, template literals and every newline.

    A character-level pass rather than a regex: ``//`` inside a string is not a comment, and a
    quote inside a comment does not open a string. Newlines survive so findings keep their lines.

    Args:
      source: The module text.

    Returns:
      The text with comment bodies replaced by spaces.

    Raises:
      None.
    """
    out: list[str] = []
    i, n = 0, len(source)
    quote: str | None = None
    while i < n:
        ch = source[i]
        nxt = source[i + 1] if i + 1 < n else ""
        if quote:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(nxt)
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "'\"`":
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "/" and nxt == "/":
            while i < n and source[i] != "\n":
                out.append(" ")
                i += 1
            continue
        if ch == "/" and nxt == "*":
            end = source.find("*/", i + 2)
            end = n if end == -1 else end + 2
            out.extend("\n" if c == "\n" else " " for c in source[i:end])
            i = end
            continue
        if ch == "/" and _opens_regex(out):
            end = _regex_end(source, i)
            out.extend("\n" if c == "\n" else " " for c in source[i:end])
            i = end
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _opens_regex(out: list[str]) -> bool:
    """Decides whether a ``/`` at this point starts a regex literal rather than a division.

    The heuristic JavaScript tokenizers use: a regex may follow an operator, an opener, a
    separator, ``return`` or the start of a line; a division follows an operand.

    Args:
      out: The stripped text so far.

    Returns:
      True when the slash opens a regex literal.

    Raises:
      None.
    """
    j = len(out) - 1
    while j >= 0 and out[j] in " \t":
        j -= 1
    if j < 0 or out[j] == "\n" or out[j] in _REGEX_PRECEDERS:
        return True
    return "".join(out[max(0, j - 5) : j + 1]).endswith("return")


def _regex_end(source: str, start: int) -> int:
    """Finds the index just past the closing slash of a regex literal opening at ``start``.

    Escapes are skipped and a character class may hold an unescaped slash, so both are tracked;
    an unterminated literal ends at the line, which is where JavaScript would refuse it too.

    Args:
      source: The module text.
      start: The index of the opening slash.

    Returns:
      The index after the closing slash, or after the line's end.

    Raises:
      None.
    """
    i, n, in_class = start + 1, len(source), False
    while i < n and source[i] != "\n":
        c = source[i]
        if c == "\\":
            i += 2
            continue
        if in_class:
            in_class = c != "]"
        elif c == "[":
            in_class = True
        elif c == "/":
            return i + 1
        i += 1
    return i


def _ts_modules() -> list[pathlib.Path]:
    """Every app module under ``apps/portal/src``, owner included, tests and generated files excluded.

    Args:
      None.

    Returns:
      The sorted module paths.

    Raises:
      None.
    """
    src = ROOT / "apps" / "portal" / "src"
    return sorted(
        path
        for ext in ("*.ts", "*.tsx")
        for path in src.rglob(ext)
        if ".test." not in path.name
        and not path.name.endswith(".generated.ts")
        and (src / "test") not in path.parents
    )


def _sweep_ts_module(path: pathlib.Path) -> list[str]:
    """Applies the two TypeScript rules to one module.

    Args:
      path: The module.

    Returns:
      The findings, in source order.

    Raises:
      None.
    """
    rel = path.relative_to(ROOT).as_posix()
    findings: list[str] = []
    stripped = _strip_ts_comments(path.read_text(encoding="utf-8"))
    has_sibling = _TS_SIBLING.search(stripped) is not None
    for number, line in enumerate(stripped.split("\n"), start=1):
        for match in _TS_TEMPLATE_SEGMENT.finditer(line):
            findings.append(_finding(rel, number, match.group(1), "constructed", "a template builds the prefix"))
        for match in _TS_TEMPLATE_IDENT.finditer(line):
            findings.append(_finding(rel, number, _IDENT_TO_NAME[match.group(1)], "constructed", "a template builds the prefix from the owner's name"))
        for match in _TS_CONCAT_IDENT.finditer(line):
            findings.append(_finding(rel, number, _IDENT_TO_NAME[match.group(1)], "constructed", "a concatenation builds the prefix from the owner's name"))
        for match in _TS_LITERAL.finditer(line):
            bare = match.group(0)[1:-1] == OVERLOADED
            if bare and not has_sibling and not _TS_MODULE_LEVEL_ARCHIVE.match(line):
                continue
            findings.append(_finding(rel, number, match.group(2), "declared", "a quoted literal names the folder"))
    return findings


def main() -> int:
    """Sweeps both trees and prints every finding.

    Args:
      None.

    Returns:
      ``0`` clean, ``1`` findings, ``2`` hard error.

    Raises:
      None.
    """
    for owner in (*PY_OWNERS, TS_OWNER):
        if not (ROOT / owner).is_file():
            print(f"hard error: owner file {owner} is missing — the sweep cannot tell a declaration from its owner")
            return 2
    py_modules = [p for p in _python_modules() if p.relative_to(ROOT).as_posix() not in PY_OWNERS]
    ts_modules = [p for p in _ts_modules() if p.relative_to(ROOT).as_posix() != TS_OWNER]
    if not py_modules or not ts_modules:
        print(f"hard error: nothing to sweep ({len(py_modules)} Python modules, {len(ts_modules)} TypeScript modules besides the owners)")
        return 2
    findings: list[str] = []
    for path in py_modules:
        findings += _sweep_python_module(path)
    for path in ts_modules:
        findings += _sweep_ts_module(path)
    for line in findings:
        print(line)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
