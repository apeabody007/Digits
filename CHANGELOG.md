# Changelog

All notable changes to Digits are documented here. This project follows
[Semantic Versioning](https://semver.org/).

## [0.5.0] — 2026-06-13

No new MCP tools — this release is about making the project easier to trust,
adopt, and extend.

### Added
- **Test suite** (`tests/test_digits_server.py`): 27 stdlib-`unittest` tests
  that mock the AppleScript bridge (`digits_server._run`), so they run on any
  machine — including non-macOS CI — without Numbers. Coverage spans the
  helper functions, AppleScript generation, table parsing, argument
  validation, error mapping, and the MCP JSON-RPC surface. Run with
  `python3 -m unittest discover -s tests` (or `pytest tests/`).
- **Command-line flags** when running `digits_server.py` directly:
  `--version`, `--health-check` (exits non-zero on a bad setup),
  `--list-tools`, and `--help`. With no arguments it still speaks MCP over
  stdio as before.
- **Two new bundled skills:**
  - `monthly-report` — roll raw rows up into a per-category summary with
    month-over-month deltas on its own sheet, with optional PDF/Excel export.
  - `data-cleanup` — profile a table for duplicates, blanks, inconsistent
    labels, and text in number columns, then fix it safely (batched value
    edits, bottom-up row deletion) after user sign-off.

### Changed
- **README** expanded with a full per-tool parameter reference (collapsible,
  with request/response examples), a "Verify your setup" section for the new
  CLI flags, a "Performance & atomicity" section explaining the per-call
  `osascript` model and the batch-everything-in-one-`set_cells` guidance, a
  workaround for each documented limitation, and a Development section.
- **Config files commented:** `.mcp.json`, `.claude-plugin/plugin.json`, and
  `.claude-plugin/marketplace.json` each carry an `_comment` explaining their
  purpose and the need to keep versions in sync.

## [0.4.0] — 2026-06-13

Added a second wave of editing tools so Digits can manage spreadsheet
structure, not just cell contents.

### Added
- **Sheet management:** `numbers_add_sheet`, `numbers_rename_sheet`,
  `numbers_delete_sheet`.
- **Row/column editing at an index:** `numbers_insert_row`,
  `numbers_delete_row`, `numbers_insert_column`, `numbers_delete_column`
  (previously rows/columns could only be appended at the end).
- **Document export:** `numbers_export` to PDF, Excel (.xlsx), or CSV, using
  Numbers' native exporter.
- **Save to a path:** `numbers_save_as`.

### Notes
- Numbers' scripting cannot duplicate a sheet's contents (error -1717) or
  reorder sheets (error -10000), so `numbers_add_sheet` creates blank sheets
  appended at the end. These are platform limitations, documented in the
  README.

## [0.3.0] — 2026-06-12

### Added
- `numbers_create_document`, `numbers_import_csv`, `numbers_export_csv`,
  `numbers_health_check`.
- `marketplace.json` for one-line install from GitHub.

## [0.2.0] — 2026-06-12

### Changed
- Rewrote the server as a **zero-dependency** pure-stdlib MCP server
  (dropped FastMCP / uv). Runs on the `python3` bundled with macOS.
- Renamed the project to **Digits**.

## [0.1.0] — 2026-06-12

### Added
- Initial release: AppleScript-backed MCP server with core tools
  (`list_documents`, `list_sheets`, `list_tables`, `read_table`, `set_cells`,
  `add_row`, `add_column`, `save_document`) and a `budget-review` skill.
