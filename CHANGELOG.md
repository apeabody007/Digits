# Changelog

All notable changes to Digits are documented here. This project follows
[Semantic Versioning](https://semver.org/).

## [0.4.0] — 2026-06-13

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
