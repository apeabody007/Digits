#!/usr/bin/env python3
"""Digits — connect Claude to Apple Numbers.

A zero-dependency MCP server (pure Python stdlib) that reads and edits live
Apple Numbers spreadsheets by driving Numbers.app through AppleScript.

Why zero dependencies?
    Install friction is the enemy. This file speaks MCP's JSON-RPC stdio
    protocol directly — no FastMCP, no pip, no uv. Any Mac with python3
    (bundled with Xcode Command Line Tools) can run it as-is.

Design notes
------------
- Every tool shells out to `osascript`. No private APIs, no .numbers file
  parsing — what Numbers shows is what you get, including live formula
  results.
- Table reads are serialized with ASCII unit/record separators (0x1F/0x1E)
  instead of commas/newlines, so cell contents can never collide with the
  delimiter.
- Setting a cell value to a string beginning with "=" enters it as a
  formula (verified against Numbers 14.x).
- Targets default to the front document / active sheet / first table, so
  "read the table" just works on whatever the user is looking at.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any, Callable

SERVER_NAME = "digits"
SERVER_VERSION = "0.4.0"
PROTOCOL_VERSION = "2024-11-05"

_RS = chr(30)  # record separator: between rows / list items
_US = chr(31)  # unit separator: between cells
_FS = chr(17)  # value/formula separator within a cell

_OSA_TIMEOUT = 120


# ---------------------------------------------------------------------------
# AppleScript plumbing
# ---------------------------------------------------------------------------

class ToolError(Exception):
    """Raised by tools; message is surfaced to the model as an error result."""


def _run(script: str) -> str:
    """Execute an AppleScript and return stdout, raising actionable errors."""
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=_OSA_TIMEOUT,
        )
    except FileNotFoundError:
        raise ToolError("osascript not found — Digits only works on macOS.")
    except subprocess.TimeoutExpired:
        raise ToolError(
            f"AppleScript timed out after {_OSA_TIMEOUT}s. Numbers may be "
            "showing a modal dialog; dismiss it and retry."
        )
    if proc.returncode != 0:
        err = proc.stderr.strip()
        if "Not authorized" in err or "-1743" in err:
            raise ToolError(
                "macOS denied Apple Events automation. Grant access in "
                "System Settings > Privacy & Security > Automation "
                "(enable Numbers under your MCP client), then retry."
            )
        if "-1728" in err or "Can't get" in err:
            raise ToolError(
                f"Numbers couldn't find that target: {err}. Check names with "
                "numbers_list_documents / numbers_list_sheets / "
                "numbers_list_tables."
            )
        raise ToolError(f"AppleScript error: {err}")
    return proc.stdout.rstrip("\n")


def _q(s: str) -> str:
    """Quote a Python string as an AppleScript string literal."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _target(document: str | None, sheet: str | None, table: str | None) -> str:
    """Build an AppleScript reference to a table."""
    doc = f"document {_q(document)}" if document else "front document"
    sht = f"sheet {_q(sheet)} of {doc}" if sheet else f"active sheet of {doc}"
    return f"table {_q(table)} of {sht}" if table else f"table 1 of {sht}"


def _parse_cell(raw: str) -> Any:
    """Best-effort conversion of an AppleScript cell string back to JSON types."""
    if raw == "":
        return None
    try:
        f = float(raw)
        return int(f) if f.is_integer() else f
    except ValueError:
        return raw


def _as_value(value: Any) -> str:
    """Render a JSON value as an AppleScript expression."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if value is None:
        return '""'
    return _q(str(value))


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def list_documents(args: dict) -> list[str]:
    out = _run(
        'tell application "Numbers"\n'
        '\tset acc to ""\n'
        "\trepeat with d in documents\n"
        '\t\tif acc is not "" then set acc to acc & character id 30\n'
        "\t\tset acc to acc & (name of d)\n"
        "\tend repeat\n"
        "\treturn acc\n"
        "end tell"
    )
    return [n for n in out.split(_RS) if n]


def open_document(args: dict) -> str:
    return _run(
        'tell application "Numbers"\n'
        f"\tset d to open (POSIX file {_q(args['path'])})\n"
        "\treturn name of d\n"
        "end tell"
    )


def list_sheets(args: dict) -> list[str]:
    doc = f"document {_q(args['document'])}" if args.get("document") else "front document"
    out = _run(
        'tell application "Numbers"\n'
        '\tset acc to ""\n'
        f"\trepeat with s in sheets of {doc}\n"
        '\t\tif acc is not "" then set acc to acc & character id 30\n'
        "\t\tset acc to acc & (name of s)\n"
        "\tend repeat\n"
        "\treturn acc\n"
        "end tell"
    )
    return [n for n in out.split(_RS) if n]


def list_tables(args: dict) -> list[dict[str, Any]]:
    doc = f"document {_q(args['document'])}" if args.get("document") else "front document"
    sht = f"sheet {_q(args['sheet'])} of {doc}" if args.get("sheet") else f"active sheet of {doc}"
    out = _run(
        'tell application "Numbers"\n'
        '\tset acc to ""\n'
        f"\trepeat with t in tables of {sht}\n"
        '\t\tif acc is not "" then set acc to acc & character id 30\n'
        "\t\tset acc to acc & (name of t) & character id 31 & (row count of t) & character id 31 & (column count of t)\n"
        "\tend repeat\n"
        "\treturn acc\n"
        "end tell"
    )
    tables = []
    for rec in out.split(_RS):
        if not rec:
            continue
        name, rows, cols = rec.split(_US)
        tables.append({"name": name, "rows": int(rows), "columns": int(cols)})
    return tables


def read_table(args: dict) -> dict[str, Any]:
    include_formulas = bool(args.get("include_formulas", False))
    max_rows = int(args.get("max_rows", 200))
    if not 1 <= max_rows <= 2000:
        raise ToolError("max_rows must be between 1 and 2000.")
    tbl = _target(args.get("document"), args.get("sheet"), args.get("table"))
    formula_part = (
        "\t\t\t\tset fv to formula of cell c of row r\n"
        '\t\t\t\tif fv is missing value then set fv to ""\n'
        "\t\t\t\tset sv to sv & character id 17 & fv\n"
        if include_formulas
        else ""
    )
    out = _run(
        'tell application "Numbers"\n'
        f"\ttell {tbl}\n"
        "\t\tset rc to row count\n"
        f"\t\tif rc > {max_rows} then set rc to {max_rows}\n"
        "\t\tset cc to column count\n"
        '\t\tset acc to ""\n'
        "\t\trepeat with r from 1 to rc\n"
        '\t\t\tset rowAcc to ""\n'
        "\t\t\trepeat with c from 1 to cc\n"
        "\t\t\t\tset v to value of cell c of row r\n"
        "\t\t\t\tif v is missing value then\n"
        '\t\t\t\t\tset sv to ""\n'
        "\t\t\t\telse\n"
        "\t\t\t\t\tset sv to v as string\n"
        "\t\t\t\tend if\n"
        + formula_part +
        "\t\t\t\tif c > 1 then set rowAcc to rowAcc & character id 31\n"
        "\t\t\t\tset rowAcc to rowAcc & sv\n"
        "\t\t\tend repeat\n"
        "\t\t\tif r > 1 then set acc to acc & character id 30\n"
        "\t\t\tset acc to acc & rowAcc\n"
        "\t\tend repeat\n"
        "\t\treturn acc\n"
        "\tend tell\n"
        "end tell"
    )
    values: list[list[Any]] = []
    formulas: list[list[str | None]] = []
    for rec in out.split(_RS):
        vrow: list[Any] = []
        frow: list[str | None] = []
        for cell in rec.split(_US):
            if include_formulas and _FS in cell:
                v, f = cell.split(_FS, 1)
                vrow.append(_parse_cell(v))
                frow.append(f or None)
            else:
                vrow.append(_parse_cell(cell))
                frow.append(None)
        values.append(vrow)
        formulas.append(frow)
    result: dict[str, Any] = {"rows": values, "row_count": len(values)}
    if include_formulas:
        result["formulas"] = formulas
    return result


def set_cells(args: dict) -> str:
    updates = args["updates"]
    if not isinstance(updates, list) or not 1 <= len(updates) <= 200:
        raise ToolError("updates must be a list of 1–200 {cell, value} objects.")
    for u in updates:
        if not isinstance(u, dict) or "cell" not in u or "value" not in u:
            raise ToolError('Each update needs "cell" (e.g. "F7") and "value".')
    tbl = _target(args.get("document"), args.get("sheet"), args.get("table"))
    sets = "\n".join(
        f"\t\tset value of cell {_q(str(u['cell']))} to {_as_value(u['value'])}"
        for u in updates
    )
    _run(
        'tell application "Numbers"\n'
        f"\ttell {tbl}\n"
        f"{sets}\n"
        "\tend tell\n"
        "end tell"
    )
    return f"Updated {len(updates)} cell(s)."


def add_row(args: dict) -> str:
    count = int(args.get("count", 1))
    if not 1 <= count <= 100:
        raise ToolError("count must be between 1 and 100.")
    tbl = _target(args.get("document"), args.get("sheet"), args.get("table"))
    out = _run(
        'tell application "Numbers"\n'
        f"\ttell {tbl}\n"
        f"\t\trepeat {count} times\n"
        "\t\t\tmake new row at end of rows\n"
        "\t\tend repeat\n"
        "\t\treturn row count\n"
        "\tend tell\n"
        "end tell"
    )
    return f"Added {count} row(s); table now has {out} rows."


def add_column(args: dict) -> str:
    count = int(args.get("count", 1))
    if not 1 <= count <= 26:
        raise ToolError("count must be between 1 and 26.")
    tbl = _target(args.get("document"), args.get("sheet"), args.get("table"))
    out = _run(
        'tell application "Numbers"\n'
        f"\ttell {tbl}\n"
        f"\t\trepeat {count} times\n"
        "\t\t\tmake new column at end of columns\n"
        "\t\tend repeat\n"
        "\t\treturn column count\n"
        "\tend tell\n"
        "end tell"
    )
    return f"Added {count} column(s); table now has {out} columns."


def create_document(args: dict) -> str:
    name = _run(
        'tell application "Numbers"\n'
        "\tset d to make new document\n"
        "\treturn name of d\n"
        "end tell"
    )
    return (
        f"Created new document {name!r}. It is unsaved — use "
        "numbers_save_document after the user confirms where it should live, "
        "or let them save manually."
    )


def import_csv(args: dict) -> str:
    path = args.get("path")
    csv_text = args.get("csv_text")
    if bool(path) == bool(csv_text):
        raise ToolError('Provide exactly one of "path" or "csv_text".')
    if csv_text:
        import tempfile

        tmp = tempfile.NamedTemporaryFile(
            "w", suffix=".csv", prefix="digits_import_", delete=False, encoding="utf-8"
        )
        tmp.write(csv_text)
        tmp.close()
        path = tmp.name
    name = _run(
        'tell application "Numbers"\n'
        f"\tset d to open (POSIX file {_q(path)})\n"
        "\treturn name of d\n"
        "end tell"
    )
    return (
        f"Imported CSV as new document {name!r} (Numbers parsed it natively). "
        "The document is unsaved."
    )


def export_csv(args: dict) -> str:
    import csv as _csv
    import io

    data = read_table(
        {
            "document": args.get("document"),
            "sheet": args.get("sheet"),
            "table": args.get("table"),
            "max_rows": args.get("max_rows", 2000),
        }
    )
    buf = io.StringIO()
    writer = _csv.writer(buf)
    for row in data["rows"]:
        writer.writerow(["" if v is None else v for v in row])
    text = buf.getvalue()
    out_path = args.get("path")
    if out_path:
        with open(out_path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        return f"Wrote {data['row_count']} row(s) to {out_path}."
    return text


def _doc_ref(document: str | None) -> str:
    return f"document {_q(document)}" if document else "front document"


def add_sheet(args: dict) -> str:
    doc = _doc_ref(args.get("document"))
    name = args.get("name")
    name_line = f"\t\tset name of ns to {_q(name)}\n" if name else ""
    out = _run(
        'tell application "Numbers"\n'
        f"\ttell {doc}\n"
        "\t\tset ns to make new sheet\n"
        + name_line +
        "\t\treturn name of ns\n"
        "\tend tell\n"
        "end tell"
    )
    return f"Added sheet {out!r}."


def rename_sheet(args: dict) -> str:
    doc = _doc_ref(args.get("document"))
    old, new = args["name"], args["new_name"]
    _run(
        'tell application "Numbers"\n'
        f"\tset name of sheet {_q(old)} of {doc} to {_q(new)}\n"
        "end tell"
    )
    return f"Renamed sheet {old!r} to {new!r}."


def delete_sheet(args: dict) -> str:
    doc = _doc_ref(args.get("document"))
    name = args["name"]
    _run(
        'tell application "Numbers"\n'
        f"\tdelete sheet {_q(name)} of {doc}\n"
        "end tell"
    )
    return f"Deleted sheet {name!r}."


def insert_row(args: dict) -> str:
    after = int(args["after_row"])
    count = int(args.get("count", 1))
    if not 1 <= count <= 100:
        raise ToolError("count must be between 1 and 100.")
    tbl = _target(args.get("document"), args.get("sheet"), args.get("table"))
    out = _run(
        'tell application "Numbers"\n'
        f"\ttell {tbl}\n"
        f"\t\trepeat {count} times\n"
        f"\t\t\tmake new row at after row {after}\n"
        "\t\tend repeat\n"
        "\t\treturn row count\n"
        "\tend tell\n"
        "end tell"
    )
    return f"Inserted {count} row(s) after row {after}; table now has {out} rows."


def delete_row(args: dict) -> str:
    row = int(args["row"])
    count = int(args.get("count", 1))
    if not 1 <= count <= 100:
        raise ToolError("count must be between 1 and 100.")
    tbl = _target(args.get("document"), args.get("sheet"), args.get("table"))
    out = _run(
        'tell application "Numbers"\n'
        f"\ttell {tbl}\n"
        f"\t\trepeat {count} times\n"
        f"\t\t\tremove row {row}\n"
        "\t\tend repeat\n"
        "\t\treturn row count\n"
        "\tend tell\n"
        "end tell"
    )
    return f"Deleted {count} row(s) starting at row {row}; table now has {out} rows."


def insert_column(args: dict) -> str:
    after = int(args["after_column"])
    count = int(args.get("count", 1))
    if not 1 <= count <= 26:
        raise ToolError("count must be between 1 and 26.")
    tbl = _target(args.get("document"), args.get("sheet"), args.get("table"))
    out = _run(
        'tell application "Numbers"\n'
        f"\ttell {tbl}\n"
        f"\t\trepeat {count} times\n"
        f"\t\t\tmake new column at after column {after}\n"
        "\t\tend repeat\n"
        "\t\treturn column count\n"
        "\tend tell\n"
        "end tell"
    )
    return f"Inserted {count} column(s) after column {after}; table now has {out} columns."


def delete_column(args: dict) -> str:
    column = int(args["column"])
    count = int(args.get("count", 1))
    if not 1 <= count <= 26:
        raise ToolError("count must be between 1 and 26.")
    tbl = _target(args.get("document"), args.get("sheet"), args.get("table"))
    out = _run(
        'tell application "Numbers"\n'
        f"\ttell {tbl}\n"
        f"\t\trepeat {count} times\n"
        f"\t\t\tremove column {column}\n"
        "\t\tend repeat\n"
        "\t\treturn column count\n"
        "\tend tell\n"
        "end tell"
    )
    return f"Deleted {count} column(s) starting at column {column}; table now has {out} columns."


_EXPORT_FORMATS = {
    "pdf": "PDF",
    "excel": "Microsoft Excel",
    "xlsx": "Microsoft Excel",
    "csv": "CSV",
}


def export_document(args: dict) -> str:
    doc = _doc_ref(args.get("document"))
    path = args["path"]
    fmt = str(args.get("format", "pdf")).lower()
    if fmt not in _EXPORT_FORMATS:
        raise ToolError('format must be one of: pdf, excel, csv.')
    enum = _EXPORT_FORMATS[fmt]
    _run(
        'tell application "Numbers"\n'
        f"\texport {doc} to (POSIX file {_q(path)}) as {enum}\n"
        "end tell"
    )
    return f"Exported to {path} as {enum}."


def save_as(args: dict) -> str:
    doc = _doc_ref(args.get("document"))
    path = args["path"]
    _run(
        'tell application "Numbers"\n'
        f"\tsave {doc} in (POSIX file {_q(path)})\n"
        "end tell"
    )
    return f"Saved to {path}."


def health_check(args: dict) -> dict[str, Any]:
    import platform
    import shutil

    report: dict[str, Any] = {
        "python": platform.python_version(),
        "platform": platform.system(),
    }
    issues: list[str] = []
    if platform.system() != "Darwin":
        issues.append("Not running on macOS — Digits requires a Mac with Numbers.")
    elif shutil.which("osascript") is None:
        issues.append("osascript not found on PATH.")
    else:
        try:
            report["numbers_version"] = _run(
                'tell application "Numbers" to return version'
            )
            report["automation_permission"] = "granted"
            report["open_documents"] = len(list_documents({}))
        except ToolError as e:
            issues.append(str(e))
    report["status"] = "ok" if not issues else "issues_found"
    if issues:
        report["issues"] = issues
    return report


def save_document(args: dict) -> str:
    doc = f"document {_q(args['document'])}" if args.get("document") else "front document"
    _run(
        'tell application "Numbers"\n'
        f"\tsave {doc}\n"
        "end tell"
    )
    return "Saved."


# ---------------------------------------------------------------------------
# Tool registry (name → description, JSON Schema, handler)
# ---------------------------------------------------------------------------

_DOC = {"type": "string", "description": "Document name; defaults to the front document"}
_SHEET = {"type": "string", "description": "Sheet name; defaults to the active sheet"}
_TABLE = {"type": "string", "description": "Table name; defaults to the first table"}


def _schema(props: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": props,
        "required": required or [],
        "additionalProperties": False,
    }


TOOLS: dict[str, tuple[str, dict, Callable[[dict], Any]]] = {
    "numbers_list_documents": (
        "List the names of all spreadsheets currently open in Numbers. "
        "Launches Numbers if it isn't running. If empty, open a file with "
        "numbers_open_document before using other tools.",
        _schema({}),
        list_documents,
    ),
    "numbers_open_document": (
        "Open a .numbers file in Numbers and return the document name.",
        _schema(
            {"path": {"type": "string", "description": "Absolute POSIX path to a .numbers file"}},
            ["path"],
        ),
        open_document,
    ),
    "numbers_list_sheets": (
        "List sheet names (the tabs) in a Numbers document.",
        _schema({"document": _DOC}),
        list_sheets,
    ),
    "numbers_list_tables": (
        "List tables on a sheet with their dimensions (name, rows, columns).",
        _schema({"document": _DOC, "sheet": _SHEET}),
        list_tables,
    ),
    "numbers_read_table": (
        "Read a table's cell values as a 2D grid (row-major). Empty cells are "
        "null; numbers come back as numbers. Formula cells return their "
        "computed value; pass include_formulas=true to also get formula text.",
        _schema(
            {
                "document": _DOC,
                "sheet": _SHEET,
                "table": _TABLE,
                "include_formulas": {
                    "type": "boolean",
                    "description": "Also return a parallel grid of formulas (null where none)",
                    "default": False,
                },
                "max_rows": {
                    "type": "integer",
                    "description": "Safety cap on rows returned (1–2000)",
                    "default": 200,
                },
            }
        ),
        read_table,
    ),
    "numbers_set_cells": (
        "Write values and/or formulas to cells in one batch. Strings starting "
        'with "=" are entered as formulas, e.g. "=SUM(F4:F14)". Edits the live '
        "document (undoable with Cmd+Z; not saved to disk until "
        "numbers_save_document).",
        _schema(
            {
                "updates": {
                    "type": "array",
                    "description": "Cells to write, applied in order",
                    "items": {
                        "type": "object",
                        "properties": {
                            "cell": {"type": "string", "description": 'A1-style address, e.g. "F7"'},
                            "value": {
                                "type": ["string", "number", "boolean"],
                                "description": 'New value; "=..." strings become formulas',
                            },
                        },
                        "required": ["cell", "value"],
                        "additionalProperties": False,
                    },
                    "minItems": 1,
                    "maxItems": 200,
                },
                "document": _DOC,
                "sheet": _SHEET,
                "table": _TABLE,
            },
            ["updates"],
        ),
        set_cells,
    ),
    "numbers_add_row": (
        "Append empty row(s) to the end of a table. Returns the new row count.",
        _schema(
            {
                "document": _DOC,
                "sheet": _SHEET,
                "table": _TABLE,
                "count": {"type": "integer", "description": "How many rows to append (1–100)", "default": 1},
            }
        ),
        add_row,
    ),
    "numbers_add_column": (
        "Append empty column(s) to the end of a table. Returns the new column count.",
        _schema(
            {
                "document": _DOC,
                "sheet": _SHEET,
                "table": _TABLE,
                "count": {"type": "integer", "description": "How many columns to append (1–26)", "default": 1},
            }
        ),
        add_column,
    ),
    "numbers_save_document": (
        "Save a document to disk. Edits made by numbers_set_cells are "
        "otherwise in-memory only until the user saves manually.",
        _schema({"document": _DOC}),
        save_document,
    ),
    "numbers_create_document": (
        "Create a new, blank Numbers spreadsheet (one sheet, one table). "
        "Returns the document name to target with other tools.",
        _schema({}),
        create_document,
    ),
    "numbers_import_csv": (
        "Import CSV data as a new Numbers document, parsed natively by "
        "Numbers (handles quoting, commas in fields, type inference). Pass "
        "either a file path or raw CSV text.",
        _schema(
            {
                "path": {"type": "string", "description": "Absolute POSIX path to a .csv file"},
                "csv_text": {"type": "string", "description": "Raw CSV content to import"},
            }
        ),
        import_csv,
    ),
    "numbers_export_csv": (
        "Export a table as CSV. Returns the CSV text, or writes it to a file "
        "if a path is given.",
        _schema(
            {
                "document": _DOC,
                "sheet": _SHEET,
                "table": _TABLE,
                "path": {"type": "string", "description": "Optional absolute path to write the .csv to"},
                "max_rows": {"type": "integer", "description": "Safety cap on rows exported (1–2000)", "default": 2000},
            }
        ),
        export_csv,
    ),
    "numbers_health_check": (
        "Verify the Digits setup: macOS, Numbers installed and scriptable, "
        "automation permission granted, open document count. Run this first "
        "when any other tool fails unexpectedly.",
        _schema({}),
        health_check,
    ),
    "numbers_add_sheet": (
        "Add a new sheet (tab) to a document. Appends after the existing "
        "sheets. Optionally name it. Returns the new sheet's name. Note: "
        "Numbers' scripting cannot duplicate a sheet's contents, so new "
        "sheets start blank.",
        _schema(
            {
                "document": _DOC,
                "name": {"type": "string", "description": "Name for the new sheet (optional)"},
            }
        ),
        add_sheet,
    ),
    "numbers_rename_sheet": (
        "Rename a sheet (tab).",
        _schema(
            {
                "name": {"type": "string", "description": "Current sheet name"},
                "new_name": {"type": "string", "description": "New sheet name"},
                "document": _DOC,
            },
            ["name", "new_name"],
        ),
        rename_sheet,
    ),
    "numbers_delete_sheet": (
        "Delete a sheet (tab) by name. A document must keep at least one sheet.",
        _schema(
            {
                "name": {"type": "string", "description": "Name of the sheet to delete"},
                "document": _DOC,
            },
            ["name"],
        ),
        delete_sheet,
    ),
    "numbers_insert_row": (
        "Insert blank row(s) into a table after a given row index (1-based).",
        _schema(
            {
                "after_row": {"type": "integer", "description": "Insert after this row index (1-based)"},
                "count": {"type": "integer", "description": "How many rows to insert (1–100)", "default": 1},
                "document": _DOC,
                "sheet": _SHEET,
                "table": _TABLE,
            },
            ["after_row"],
        ),
        insert_row,
    ),
    "numbers_delete_row": (
        "Delete row(s) from a table starting at a given row index (1-based).",
        _schema(
            {
                "row": {"type": "integer", "description": "First row to delete (1-based)"},
                "count": {"type": "integer", "description": "How many rows to delete (1–100)", "default": 1},
                "document": _DOC,
                "sheet": _SHEET,
                "table": _TABLE,
            },
            ["row"],
        ),
        delete_row,
    ),
    "numbers_insert_column": (
        "Insert blank column(s) into a table after a given column index (1-based).",
        _schema(
            {
                "after_column": {"type": "integer", "description": "Insert after this column index (1-based)"},
                "count": {"type": "integer", "description": "How many columns to insert (1–26)", "default": 1},
                "document": _DOC,
                "sheet": _SHEET,
                "table": _TABLE,
            },
            ["after_column"],
        ),
        insert_column,
    ),
    "numbers_delete_column": (
        "Delete column(s) from a table starting at a given column index (1-based).",
        _schema(
            {
                "column": {"type": "integer", "description": "First column to delete (1-based)"},
                "count": {"type": "integer", "description": "How many columns to delete (1–26)", "default": 1},
                "document": _DOC,
                "sheet": _SHEET,
                "table": _TABLE,
            },
            ["column"],
        ),
        delete_column,
    ),
    "numbers_export": (
        "Export a whole document to a file as PDF, Excel (.xlsx), or CSV. "
        "Numbers does the conversion natively.",
        _schema(
            {
                "path": {"type": "string", "description": "Absolute POSIX path for the output file"},
                "format": {
                    "type": "string",
                    "description": "Output format: pdf, excel, or csv",
                    "enum": ["pdf", "excel", "csv"],
                },
                "document": _DOC,
            },
            ["path", "format"],
        ),
        export_document,
    ),
    "numbers_save_as": (
        "Save a document to a specific .numbers file path on disk.",
        _schema(
            {
                "path": {"type": "string", "description": "Absolute POSIX path for the .numbers file"},
                "document": _DOC,
            },
            ["path"],
        ),
        save_as,
    ),
}


# ---------------------------------------------------------------------------
# MCP JSON-RPC stdio loop
# ---------------------------------------------------------------------------

def _send(msg: dict) -> None:
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def _result(req_id: Any, result: dict) -> None:
    _send({"jsonrpc": "2.0", "id": req_id, "result": result})


def _error(req_id: Any, code: int, message: str) -> None:
    _send({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})


def _handle(msg: dict) -> None:
    method = msg.get("method")
    req_id = msg.get("id")

    if method == "initialize":
        _result(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })
    elif method == "notifications/initialized":
        pass
    elif method == "ping":
        _result(req_id, {})
    elif method == "tools/list":
        _result(req_id, {
            "tools": [
                {"name": name, "description": desc, "inputSchema": schema}
                for name, (desc, schema, _) in TOOLS.items()
            ]
        })
    elif method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        if name not in TOOLS:
            _error(req_id, -32602, f"Unknown tool: {name}")
            return
        handler = TOOLS[name][2]
        try:
            out = handler(params.get("arguments") or {})
            text = out if isinstance(out, str) else json.dumps(out, indent=2)
            _result(req_id, {"content": [{"type": "text", "text": text}], "isError": False})
        except ToolError as e:
            _result(req_id, {"content": [{"type": "text", "text": str(e)}], "isError": True})
        except (KeyError, TypeError, ValueError) as e:
            _result(req_id, {
                "content": [{"type": "text", "text": f"Bad arguments: {e!r}"}],
                "isError": True,
            })
    elif req_id is not None:
        _error(req_id, -32601, f"Method not found: {method}")
    # notifications for unknown methods are silently ignored


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            _error(None, -32700, "Parse error")
            continue
        _handle(msg)


if __name__ == "__main__":
    main()
