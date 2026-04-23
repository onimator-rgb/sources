# Plan: Split MainWindow into Sub-Controllers

## Summary
Split `oh/ui/main_window.py` (3500+ lines) into 5 focused sub-controllers.
MainWindow becomes a thin shell (~800 lines) wiring components together.

## Extraction Order (simplest → most complex)

### Phase 1: BulkActionBar (~80 lines)
- **File**: `oh/ui/bulk_action_bar.py`
- **Methods**: `_make_bulk_bar`, `_update_bulk_bar`
- **Signals**: `bulk_action_requested(str)`, `bulk_warmup_requested()`
- **Depends on**: nothing

### Phase 2: AccountsFilterBar (~350 lines)
- **File**: `oh/ui/accounts_filter_bar.py`
- **Methods**: `_make_filter_bar`, `_clear_filters`, `_update_device_filter`, `_update_group_filter`, `_show_column_chooser`, `_save_column_visibility`, `_apply_column_visibility`
- **Constants**: all `_*_FILTER_*` values
- **Signals**: `filters_changed()`
- **Depends on**: Phase 1

### Phase 3: AccountsToolbar (~200 lines)
- **File**: `oh/ui/accounts_toolbar.py`
- **Methods**: `_make_toolbar`, `_set_busy`, `_update_last_sync_label`
- **Signals**: `scan_requested()`, `fbr_requested()`, `lbr_requested()`, etc.
- **Depends on**: Phase 2

### Phase 4: AccountsTable (~800 lines)
- **File**: `oh/ui/accounts_table.py`
- **Methods**: `_make_table`, `_populate_table`, `_fill_account_row`, `_fill_orphan_row`, `_fill_fbr_cells`, `_make_item`, `_make_bool_item`, `_get_slot_number`, context menu, action menu
- **Constants**: all `COL_*`, `COLUMN_HEADERS`, color helpers
- **Signals**: `account_selected(int)`, `action_requested(str, object)`, `selection_changed()`
- **Depends on**: Phase 3

### Phase 5: DetailDrawerController (~400 lines)
- **File**: `oh/ui/detail_drawer_controller.py`
- **Methods**: `_on_account_selected`, `_load_detail_*`, `_close_detail_panel`, `_debounced_load_row`, `_copy_diagnostic`, keyboard shortcuts
- **Signals**: `action_requested(str, int)`, `drawer_closed()`
- **Depends on**: Phase 4

## Verification after each phase
1. `python -c "from oh.ui.main_window import MainWindow; print('OK')"`
2. `python -m unittest discover tests/`
3. Manual: all UI features work identically

## Risk
- High coupling between methods — iterative extraction minimizes risk
- Filter constants shared between filter bar and _apply_filter — export from filter bar module
- Column constants used everywhere — export from accounts_table module

## Complexity: XL (5 phases, ~3000 lines moving)
