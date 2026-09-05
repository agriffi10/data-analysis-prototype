"""The fixture corpus for ``validate_app_managed_paths.py``.

Running the sweep against this repository proves the repository is clean and nothing about whether
any rule still fires — a rule that has gone quiet looks exactly like a clean tree. So each rule is
driven here against a planted violation and asserted on the REASON it reports (the file, the folder
and whether it was declared or constructed), never on a bare exit code; and every rule has an
``_ok`` neighbour asserting SILENCE on the shapes it must not flag, because a corpus of only
failures cannot see a false positive.

How it works, and why not pytest: as in ``validate_docs_test.py``. ``ROOT`` in the sweep is derived
from ``__file__``, so a COPY of the script inside a fixture tree sweeps that tree — no root override
exists for CI to be handed. This repo's pytest run is ``pytest lambdas/`` under a coverage floor
scoped to the fleet, so this runs as its own CI step beside the sweep it proves.

Usage: ``python3 scripts/validate_app_managed_paths_test.py`` — no arguments, standard library only,
non-zero exit if any case does not behave as declared.
"""

import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
SWEEP = REPO / "scripts" / "validate_app_managed_paths.py"

PY_OWNER = "lambdas/control-plane-common/cpcommon/app_managed.py"
PY_FACT3_OWNER = "lambdas/archive-common/arcommon/plan.py"
TS_OWNER = "apps/portal/src/lib/appManagedPaths.ts"

PY_OWNER_BODY = (
    'ATHENA_RESULTS_FOLDER = "athenaresults"\nRECEIPT_FOLDER = "archive"\n'
    'SHARED_TABLES_FOLDER = "shared_tables"\nVAULT_ARCHIVE_SEGMENT = "archive"\n'
    'def app_managed_prefix(root, folder):\n    return f"{root}{folder}/"\n'
)
PY_FACT3_BODY = 'PREFIX = "archive"\n'
TS_OWNER_BODY = (
    "export const ATHENA_RESULTS_FOLDER = 'athenaresults';\nexport const ARCHIVE_FOLDER = 'archive';\n"
    "export const SHARED_TABLES_FOLDER = 'shared_tables';\n"
    "export function appManagedPrefix(r: string, f: string): string { return `${r}${f}/`; }\n"
)
PY_BENIGN = ("lambdas/benign/benign.py", "X = 1\n")
TS_BENIGN = ("apps/portal/src/features/benign/benign.ts", "export const x = 1;\n")


def build(root: pathlib.Path, files: dict[str, str], *, owners: bool = True) -> None:
    """Writes the smallest tree the sweep accepts, plus the case's own files.

    Args:
      root: The fixture root.
      files: Relative path → content, written on top of the baseline.
      owners: Whether to write the three owner files (a case may omit them to plant their absence).

    Returns:
      None.

    Raises:
      None.
    """
    (root / "scripts").mkdir(parents=True)
    shutil.copy(SWEEP, root / "scripts" / SWEEP.name)
    baseline = dict([PY_BENIGN, TS_BENIGN])
    if owners:
        baseline.update({PY_OWNER: PY_OWNER_BODY, PY_FACT3_OWNER: PY_FACT3_BODY, TS_OWNER: TS_OWNER_BODY})
    for rel, body in {**baseline, **files}.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")


def run(root: pathlib.Path) -> tuple[int, str]:
    """Runs the copied sweep and returns its exit code and combined output.

    Args:
      root: The fixture root holding ``scripts/validate_app_managed_paths.py``.

    Returns:
      ``(returncode, stdout + stderr)``.

    Raises:
      None.
    """
    proc = subprocess.run(  # noqa: S603
        [sys.executable, str(root / "scripts" / SWEEP.name)], capture_output=True, text=True, check=False
    )
    return proc.returncode, proc.stdout + proc.stderr


CASES: list[tuple[str, dict[str, str], int, list[str]]] = [
    # name, planted files, expected exit, substrings the output must carry (empty = silence)
    (
        "py_bare_literal_fails",
        {"lambdas/x/verb.py": 'FOLDERS = ("athenaresults",)\n'},
        1,
        ["lambdas/x/verb.py:1", "athenaresults", "declared outside"],
    ),
    (
        "py_slash_suffixed_literal_fails",
        {"lambdas/x/verb.py": 'IGNORED = ("shared_tables/",)\n'},
        1,
        ["lambdas/x/verb.py:1", "shared_tables", "declared outside"],
    ),
    (
        "py_slash_suffixed_archive_in_a_binop_fails",
        {"lambdas/x/verb.py": 'def f(root):\n    return root + "archive/"\n'},
        1,
        ["lambdas/x/verb.py:2", "archive", "declared outside"],
    ),
    (
        "py_slash_led_literal_in_a_concatenation_fails",
        {"lambdas/x/verb.py": 'def f(root):\n    return root + "/athenaresults/"\n'},
        1,
        ["lambdas/x/verb.py:2", "athenaresults", "declared outside"],
    ),
    (
        "py_fstring_construction_fails",
        {"lambdas/x/verb.py": 'def f(root):\n    return f"{root}archive/x"\n'},
        1,
        ["lambdas/x/verb.py:2", "archive", "constructed outside"],
    ),
    (
        "py_fstring_leading_segment_fails",
        {"lambdas/x/verb.py": 'def f(bucket, u):\n    return f"s3://{bucket}/{u}/athenaresults/"\n'},
        1,
        ["lambdas/x/verb.py:2", "athenaresults", "constructed outside"],
    ),
    (
        "py_module_level_archive_assignment_fails",
        {"lambdas/x/verb.py": 'X = 1\nARCHIVE_FOLDER = "archive"\n'},
        1,
        ["lambdas/x/verb.py:2", "archive", "declared outside"],
    ),
    (
        "py_archive_beside_another_managed_name_fails",
        {"lambdas/x/verb.py": 'ROOTS = ("archive", "user_settings")\n'},
        1,
        ["lambdas/x/verb.py:1", "archive", "declared outside"],
    ),
    (
        "py_imported_name_in_an_fstring_fails",
        {"lambdas/x/verb.py": 'from cpcommon.app_managed import RECEIPT_FOLDER\ndef f(root):\n    return f"{root}{RECEIPT_FOLDER}/"\n'},
        1,
        ["lambdas/x/verb.py:3", "archive", "constructed outside"],
    ),
    (
        "py_imported_name_in_a_concatenation_fails",
        {"lambdas/x/verb.py": 'from cpcommon import app_managed\ndef f(root):\n    return root + app_managed.SHARED_TABLES_FOLDER + "/"\n'},
        1,
        ["lambdas/x/verb.py:3", "shared_tables", "constructed outside"],
    ),
    (
        "py_imported_name_in_wording_ok",
        {"lambdas/x/verb.py": 'from focommon.config import ARCHIVE_FOLDER\ndef f():\n    return f"{ARCHIVE_FOLDER}/ is read-only"\n'},
        0,
        [],
    ),
    (
        "py_archive_as_wording_ok",
        {
            "lambdas/x/verb.py": (
                '"""Reads the athenaresults/ folder and the archive/ folder."""\n'
                'observability.init(service="archive")\n'
                'MODES = frozenset({"archive", "restore"})\n'
                'KINDS = {"archive": 1, "restore": 2}\n'
                "def f(request):\n"
                '    return request.get("archive"), ("source", "archive")\n'
                'MSG = "the archive folder holds the receipts"\n'
            )
        },
        0,
        [],
    ),
    (
        "py_test_and_conftest_files_ok",
        {
            "lambdas/x/test_verb.py": 'X = ("athenaresults", "archive")\n',
            "lambdas/x/conftest.py": 'Y = "shared_tables"\n',
        },
        0,
        [],
    ),
    (
        "py_owners_declaring_everything_ok",
        {},
        0,
        [],
    ),
    (
        "ts_quoted_literal_fails",
        {"apps/portal/src/features/x/y.ts": "export const A = ['athenaresults'];\n"},
        1,
        ["apps/portal/src/features/x/y.ts:1", "athenaresults", "declared outside"],
    ),
    (
        "ts_quoted_literal_with_slash_fails",
        {"apps/portal/src/features/x/y.ts": 'const a = "shared_tables/";\n'},
        1,
        ["apps/portal/src/features/x/y.ts:1", "shared_tables", "declared outside"],
    ),
    (
        "ts_template_with_owner_name_fails",
        {
            "apps/portal/src/features/x/y.ts": (
                "import {ARCHIVE_FOLDER} from '../../lib/appManagedPaths';\n"
                "export const f = (r: string) => `${r}${ARCHIVE_FOLDER}/`;\n"
            )
        },
        1,
        ["apps/portal/src/features/x/y.ts:2", "archive", "constructed outside"],
    ),
    (
        "ts_template_with_literal_segment_fails",
        {"apps/portal/src/features/x/y.ts": "export const f = (r: string) => `${r}athenaresults/`;\n"},
        1,
        ["apps/portal/src/features/x/y.ts:1", "athenaresults", "constructed outside"],
    ),
    (
        "ts_template_with_slash_led_segment_fails",
        {"apps/portal/src/features/x/y.ts": "export const f = (u: string) => `${u}/athenaresults/`;\n"},
        1,
        ["apps/portal/src/features/x/y.ts:1", "athenaresults", "constructed outside"],
    ),
    (
        "ts_slash_led_literal_fails",
        {"apps/portal/src/features/x/y.ts": "export const a = '/shared_tables/';\n"},
        1,
        ["apps/portal/src/features/x/y.ts:1", "shared_tables", "declared outside"],
    ),
    (
        "ts_concatenation_with_owner_name_fails",
        {"apps/portal/src/features/x/y.ts": "import {ARCHIVE_FOLDER} from '../../lib/appManagedPaths';\nexport const f = (r: string) => r + ARCHIVE_FOLDER + '/';\n"},
        1,
        ["apps/portal/src/features/x/y.ts:2", "archive", "constructed outside"],
    ),
    (
        "ts_template_starting_with_owner_name_fails",
        {"apps/portal/src/features/x/y.ts": "import {ARCHIVE_FOLDER} from '../../lib/appManagedPaths';\nexport const f = (id: string) => `${ARCHIVE_FOLDER}/${id}`;\n"},
        1,
        ["apps/portal/src/features/x/y.ts:2", "archive", "constructed outside"],
    ),
    (
        "ts_regex_literal_does_not_hide_a_construction_fails",
        {"apps/portal/src/features/x/y.ts": "export const re = /^https:\\/\\//; export const f = (root: string) => `${root}archive/`;\n"},
        1,
        ["apps/portal/src/features/x/y.ts:1", "archive", "constructed outside"],
    ),
    (
        "ts_apostrophe_in_a_regex_does_not_open_a_string_ok",
        {"apps/portal/src/features/x/y.ts": "export const re = /[^']+/;\n// the 'shared_tables' folder\nexport const x = 1;\n"},
        0,
        [],
    ),
    (
        "ts_typed_mode_archive_ok",
        {"apps/portal/src/features/x/y.ts": "export type Mode = 'archive' | 'restore';\nexport const is = (k: string) => k === 'archive';\n"},
        0,
        [],
    ),
    (
        "ts_module_level_archive_const_fails",
        {"apps/portal/src/features/x/y.ts": "export const KIND = 'archive';\n"},
        1,
        ["apps/portal/src/features/x/y.ts:1", "archive", "declared outside"],
    ),
    (
        "ts_archive_beside_a_sibling_fails",
        {"apps/portal/src/features/x/y.ts": "export const A = ['user_settings', 'archive'];\n"},
        1,
        ["apps/portal/src/features/x/y.ts:1", "archive", "declared outside"],
    ),
    (
        "ts_comments_are_not_code_ok",
        {
            "apps/portal/src/features/x/y.ts": (
                "/** Files under `archive/` are read-only; see 'athenaresults'. */\n"
                "// 'shared_tables' is never a destination\n"
                "export const x = 1; // `${root}archive/`\n"
            )
        },
        0,
        [],
    ),
    (
        "ts_string_carrying_slashes_does_not_hide_a_literal_fails",
        {"apps/portal/src/features/x/y.ts": "const u = 'https://x/y'; const f = 'shared_tables';\n"},
        1,
        ["apps/portal/src/features/x/y.ts:1", "shared_tables", "declared outside"],
    ),
    (
        "ts_test_and_generated_files_ok",
        {
            "apps/portal/src/features/x/y.test.ts": "const a = ['athenaresults', 'archive'];\n",
            "apps/portal/src/test/fixtures.ts": "export const a = 'shared_tables';\n",
            "apps/portal/src/types/apiContract.generated.ts": "export type M = 'archive';\n",
        },
        0,
        [],
    ),
    (
        "ts_owner_declaring_everything_ok",
        {},
        0,
        [],
    ),
]


def main() -> int:
    """Runs every case and the wiring check; prints one line per case.

    Args:
      None.

    Returns:
      ``0`` when every case behaved as declared, else ``1``.

    Raises:
      None.
    """
    failures: list[str] = []
    for name, files, expected_exit, needles in CASES:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            build(root, files)
            code, out = run(root)
        problems = []
        if code != expected_exit:
            problems.append(f"exit {code}, expected {expected_exit}")
        if needles:
            problems += [f"output lacks {needle!r}" for needle in needles if needle not in out]
        elif out.strip():
            problems.append(f"expected silence, got: {out.strip()[:200]}")
        print(("FAIL " if problems else "ok   ") + name + ("" if not problems else " — " + "; ".join(problems)))
        if problems:
            failures.append(name)

    # Two hard errors: a tree with nothing to sweep, and an owner that has gone missing.
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        build(root, {}, owners=False)
        code, out = run(root)
    if code != 2 or "owner" not in out:
        failures.append("missing_owner_is_a_hard_error")
        print(f"FAIL missing_owner_is_a_hard_error — exit {code}: {out.strip()[:200]}")
    else:
        print("ok   missing_owner_is_a_hard_error")
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        build(root, {})
        (root / PY_BENIGN[0]).unlink()
        code, out = run(root)
    if code != 2 or "nothing to sweep" not in out:
        failures.append("empty_tree_is_a_hard_error")
        print(f"FAIL empty_tree_is_a_hard_error — exit {code}: {out.strip()[:200]}")
    else:
        print("ok   empty_tree_is_a_hard_error")

    # The wiring: CI runs the sweep AND this corpus, unconditionally. A step behind an `if:` whose
    # output never exists is skipped on every run while looking wired. Plain string parsing, not a
    # regex over the whole workflow: the step list is split on its `- name:` lines and each block is
    # read on its own.
    workflow = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    blocks = workflow.split("\n      - name: ")
    for script in ("scripts/validate_app_managed_paths.py", "scripts/validate_app_managed_paths_test.py"):
        matching = [b for b in blocks if f"run: python3 {script}\n" in b or b.rstrip().endswith(f"run: python3 {script}")]
        if len(matching) != 1:
            failures.append(f"ci_runs_{script}")
            print(f"FAIL ci_wiring — {len(matching)} step(s) run {script}, expected exactly one")
            continue
        block = matching[0]
        keys = [line.strip() for line in block.splitlines() if not line.strip().startswith("#")]
        if any(k.startswith(("if:", "continue-on-error:")) for k in keys):
            failures.append(f"ci_step_unconditional_{script}")
            print(f"FAIL ci_wiring — the step running {script} is conditional or non-blocking")
        else:
            print(f"ok   ci_wiring {script}")

    if failures:
        print(f"\n{len(failures)} case(s) did not behave as declared: {', '.join(failures)}")
        return 1
    print(f"\nall {len(CASES) + 4} cases behaved as declared")
    return 0


if __name__ == "__main__":
    sys.exit(main())
