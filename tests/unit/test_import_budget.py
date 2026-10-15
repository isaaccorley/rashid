"""What ``import rashid`` and ``rashid --help`` load, checked in a fresh interpreter.

import-linter proves that no rashid module imports the geospatial stack at
module level. It cannot see an import that a third-party package makes, or
one that a module-level call triggers. This test reads ``sys.modules`` after
the import, so it catches both. The pytest process has already imported
everything, so each case runs in a subprocess.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

# Loaded only by the passes that need them, never by an import or by --help.
_HEAVY = frozenset(
    {
        "pyarrow",
        "rasterio",
        "pyproj",
        "rio_cogeo",
        "shapely",
        "numpy",
        "jsonschema",
        "jsonschema_rs",
        "referencing",
        "jsonschema_specifications",
    }
)
# Profilers run the code; the code never imports them.
_PROFILERS = frozenset({"pyinstrument", "memray"})

_REPORT = "import sys, json; print(json.dumps(sorted(sys.modules)))"


def _loaded(code: str) -> set[str]:
    result = subprocess.run(
        [sys.executable, "-c", f"{code}\n{_REPORT}"],
        capture_output=True,
        text=True,
        check=True,
        env={"PATH": "", "SYSTEMROOT": ""} if sys.platform == "win32" else {"PATH": ""},
    )
    return {name.split(".")[0] for name in json.loads(result.stdout.splitlines()[-1])}


def test_import_rashid_loads_no_heavy_module_and_no_cli_framework() -> None:
    loaded = _loaded("import rashid")
    assert "rashid" in loaded
    assert loaded & (_HEAVY | _PROFILERS | {"click"}) == set()


def test_cli_help_loads_no_heavy_module() -> None:
    code = (
        "import contextlib, io\n"
        "from rashid.cli import main\n"
        "with contextlib.redirect_stdout(io.StringIO()):\n"
        "    try:\n"
        "        main(['check', '--help'])\n"
        "    except SystemExit as exc:\n"
        "        assert exc.code == 0, exc.code\n"
    )
    loaded = _loaded(code)
    assert "click" in loaded
    assert loaded & (_HEAVY | _PROFILERS) == set()


@pytest.mark.parametrize("module", ["rashid.data.checks"])
def test_the_budget_detects_a_heavy_import(module: str) -> None:
    """The check itself can fail: the data checks module loads the geo stack."""
    pytest.importorskip("pyarrow")
    assert {"pyarrow", "rasterio"} <= _loaded(f"import {module}")
