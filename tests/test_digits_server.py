#!/usr/bin/env python3
"""Tests for the Digits MCP server.

These run with **zero dependencies** — just the standard library:

    python3 -m unittest discover -s tests

They also work under pytest if you have it (`pytest tests/`), but pytest is
never required.

The whole point of Digits is that it shells out to AppleScript, which only
exists on a Mac with Numbers installed. So the test strategy is to replace the
one function that touches AppleScript — ``digits_server._run`` — with a fake
that records the script it was handed and returns a canned response. Every tool
ultimately funnels through ``_run``, so this lets us exercise argument
validation, AppleScript generation, and response parsing on any machine (CI
included) without Numbers ever being involved.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path

# --- import server/digits_server.py without needing it to be on PYTHONPATH ---
_SERVER_PATH = Path(__file__).resolve().parent.parent / "server" / "digits_server.py"
_spec = importlib.util.spec_from_file_location("digits_server", _SERVER_PATH)
ds = importlib.util.module_from_spec(_spec)
sys.modules["digits_server"] = ds
_spec.loader.exec_module(ds)

RS, US, FS = ds._RS, ds._US, ds._FS


class FakeOsascript:
    """Context-manager that swaps ``ds._run`` for a recording fake.

    Usage::

        with FakeOsascript("Sheet 1") as fake:
            ds.list_sheets({})
        assert "tell application" in fake.scripts[0]
    """

    def __init__(self, *responses: str):
        # If a single callable is passed, use it to compute responses.
        self._responses = list(responses)
        self._i = 0
        self.scripts: list[str] = []
        self._orig = None

    def _fake_run(self, script: str) -> str:
        self.scripts.append(script)
        if not self._responses:
            return ""
        resp = self._responses[min(self._i, len(self._responses) - 1)]
        self._i += 1
        return resp

    def __enter__(self) -> "FakeOsascript":
        self._orig = ds._run
        ds._run = self._fake_run  # type: ignore[assignment]
        return self

    def __exit__(self, *exc) -> None:
        ds._run = self._orig  # type: ignore[assignment]


class TestHelpers(unittest.TestCase):
    """Pure helper functions — no AppleScript involved."""

    def test_quote_escapes_quotes_and_backslashes(self):
        self.assertEqual(ds._q('a"b'), '"a\\"b"')
        self.assertEqual(ds._q("a\\b"), '"a\\\\b"')

    def test_target_defaults_to_front_active_first(self):
        self.assertEqual(
            ds._target(None, None, None),
            "table 1 of active sheet of front document",
        )

    def test_target_with_explicit_names(self):
        ref = ds._target("Budget", "May", "Expenses")
        self.assertIn('document "Budget"', ref)
        self.assertIn('sheet "May"', ref)
        self.assertIn('table "Expenses"', ref)

    def test_parse_cell_types(self):
        self.assertIsNone(ds._parse_cell(""))
        self.assertEqual(ds._parse_cell("42"), 42)
        self.assertIsInstance(ds._parse_cell("42"), int)
        self.assertEqual(ds._parse_cell("3.5"), 3.5)
        self.assertEqual(ds._parse_cell("hello"), "hello")

    def test_as_value_rendering(self):
        self.assertEqual(ds._as_value(True), "true")
        self.assertEqual(ds._as_value(False), "false")
        self.assertEqual(ds._as_value(None), '""')
        self.assertEqual(ds._as_value(7), "7")
        self.assertEqual(ds._as_value("=SUM(A1:A2)"), '"=SUM(A1:A2)"')


class TestReadTableParsing(unittest.TestCase):
    def test_parses_grid_and_types(self):
        grid = US.join(["Item", "Amount"]) + RS + US.join(["Rent", "1200"])
        with FakeOsascript(grid):
            out = ds.read_table({})
        self.assertEqual(out["row_count"], 2)
        self.assertEqual(out["rows"][0], ["Item", "Amount"])
        self.assertEqual(out["rows"][1], ["Rent", 1200])
        self.assertNotIn("formulas", out)

    def test_include_formulas_splits_value_and_formula(self):
        # Each cell is "value<FS>formula" when include_formulas is on.
        cell_a = "Total" + FS + ""
        cell_b = "1200" + FS + "=SUM(B1:B1)"
        grid = cell_a + US + cell_b
        with FakeOsascript(grid):
            out = ds.read_table({"include_formulas": True})
        self.assertEqual(out["rows"][0], ["Total", 1200])
        self.assertEqual(out["formulas"][0], [None, "=SUM(B1:B1)"])

    def test_max_rows_bounds_are_validated(self):
        with FakeOsascript(""):
            with self.assertRaises(ds.ToolError):
                ds.read_table({"max_rows": 0})
            with self.assertRaises(ds.ToolError):
                ds.read_table({"max_rows": 5000})


class TestSetCells(unittest.TestCase):
    def test_builds_one_script_for_batch(self):
        with FakeOsascript("") as fake:
            msg = ds.set_cells(
                {"updates": [{"cell": "A1", "value": "Rent"}, {"cell": "B1", "value": 1200}]}
            )
        self.assertEqual(msg, "Updated 2 cell(s).")
        # A batch must be a single AppleScript round-trip, not one per cell.
        self.assertEqual(len(fake.scripts), 1)
        script = fake.scripts[0]
        self.assertIn('set value of cell "A1" to "Rent"', script)
        self.assertIn('set value of cell "B1" to 1200', script)

    def test_formula_string_is_passed_through(self):
        with FakeOsascript("") as fake:
            ds.set_cells({"updates": [{"cell": "C1", "value": "=SUM(A1:B1)"}]})
        self.assertIn('set value of cell "C1" to "=SUM(A1:B1)"', fake.scripts[0])

    def test_rejects_empty_updates(self):
        with FakeOsascript(""):
            with self.assertRaises(ds.ToolError):
                ds.set_cells({"updates": []})

    def test_rejects_malformed_update(self):
        with FakeOsascript(""):
            with self.assertRaises(ds.ToolError):
                ds.set_cells({"updates": [{"cell": "A1"}]})  # missing "value"


class TestRowColumnGuards(unittest.TestCase):
    def test_add_row_count_bounds(self):
        with FakeOsascript("10"):
            with self.assertRaises(ds.ToolError):
                ds.add_row({"count": 0})
            with self.assertRaises(ds.ToolError):
                ds.add_row({"count": 101})

    def test_add_column_count_bounds(self):
        with FakeOsascript("5"):
            with self.assertRaises(ds.ToolError):
                ds.add_column({"count": 27})

    def test_insert_row_reports_new_count(self):
        with FakeOsascript("11") as fake:
            msg = ds.insert_row({"after_row": 3, "count": 1})
        self.assertIn("after row 3", fake.scripts[0])
        self.assertIn("11 rows", msg)


class TestExportGuards(unittest.TestCase):
    def test_export_rejects_unknown_format(self):
        with FakeOsascript(""):
            with self.assertRaises(ds.ToolError):
                ds.export_document({"path": "/tmp/x.pdf", "format": "tiff"})

    def test_export_maps_format_to_numbers_enum(self):
        with FakeOsascript("") as fake:
            ds.export_document({"path": "/tmp/x.xlsx", "format": "xlsx"})
        self.assertIn("Microsoft Excel", fake.scripts[0])


class TestErrorMapping(unittest.TestCase):
    """_run turns raw osascript failures into actionable ToolErrors."""

    def _patch_subprocess(self, returncode, stderr):
        class _Proc:
            pass

        proc = _Proc()
        proc.returncode = returncode
        proc.stdout = ""
        proc.stderr = stderr

        orig = ds.subprocess.run
        ds.subprocess.run = lambda *a, **k: proc  # type: ignore
        self.addCleanup(lambda: setattr(ds.subprocess, "run", orig))

    def test_permission_error_is_actionable(self):
        self._patch_subprocess(1, "error: Not authorized to send Apple events (-1743)")
        with self.assertRaises(ds.ToolError) as cm:
            ds._run("noop")
        self.assertIn("Privacy & Security", str(cm.exception))

    def test_missing_target_points_to_list_tools(self):
        self._patch_subprocess(1, "Can't get table 1 (-1728)")
        with self.assertRaises(ds.ToolError) as cm:
            ds._run("noop")
        self.assertIn("numbers_list_tables", str(cm.exception))


class TestMcpProtocol(unittest.TestCase):
    """The JSON-RPC stdio surface."""

    def setUp(self):
        self.sent: list[dict] = []
        self._orig_send = ds._send
        ds._send = lambda msg: self.sent.append(msg)
        self.addCleanup(lambda: setattr(ds, "_send", self._orig_send))

    def test_initialize_reports_server_info(self):
        ds._handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        info = self.sent[0]["result"]["serverInfo"]
        self.assertEqual(info["name"], "digits")
        self.assertEqual(info["version"], ds.SERVER_VERSION)

    def test_tools_list_exposes_every_tool_with_schema(self):
        ds._handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = self.sent[0]["result"]["tools"]
        self.assertEqual(len(tools), len(ds.TOOLS))
        for t in tools:
            self.assertIn("name", t)
            self.assertIn("description", t)
            self.assertIn("inputSchema", t)

    def test_tools_call_success(self):
        with FakeOsascript("Doc 1"):
            ds._handle(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "numbers_list_sheets", "arguments": {}},
                }
            )
        result = self.sent[0]["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(result["content"][0]["type"], "text")

    def test_tools_call_unknown_tool(self):
        ds._handle(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "numbers_nope", "arguments": {}},
            }
        )
        self.assertIn("error", self.sent[0])
        self.assertEqual(self.sent[0]["error"]["code"], -32602)

    def test_tool_error_is_reported_as_iserror(self):
        ds._handle(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": "numbers_set_cells", "arguments": {"updates": []}},
            }
        )
        self.assertTrue(self.sent[0]["result"]["isError"])

    def test_unknown_method_returns_method_not_found(self):
        ds._handle({"jsonrpc": "2.0", "id": 6, "method": "frobnicate"})
        self.assertEqual(self.sent[0]["error"]["code"], -32601)


class TestHealthCheck(unittest.TestCase):
    def test_flags_non_macos(self):
        # health_check imports `platform` lazily; patch the shared module object
        # so the lazy `import platform` inside it sees our stub.
        import platform as _pl

        _orig = _pl.system
        _pl.system = lambda: "Linux"
        self.addCleanup(lambda: setattr(_pl, "system", _orig))
        report = ds.health_check({})
        self.assertEqual(report["status"], "issues_found")
        self.assertTrue(any("macOS" in i for i in report["issues"]))

    def test_reports_ok_when_numbers_responds(self):
        import platform as _pl
        import shutil as _sh

        _orig_sys, _orig_which = _pl.system, _sh.which
        _pl.system = lambda: "Darwin"
        _sh.which = lambda name: "/usr/bin/osascript"
        self.addCleanup(lambda: setattr(_pl, "system", _orig_sys))
        self.addCleanup(lambda: setattr(_sh, "which", _orig_which))
        with FakeOsascript("15.2", ""):  # version, then list_documents (empty)
            report = ds.health_check({})
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["numbers_version"], "15.2")
        self.assertEqual(report["automation_permission"], "granted")


if __name__ == "__main__":
    unittest.main(verbosity=2)
