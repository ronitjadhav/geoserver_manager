# Invariants

Eleven rules that the code enforces and a change must not break. Each one was
a real bug or a measured GeoServer behaviour, so a change that seems to make
one of them unnecessary usually has not understood it yet. The
[architecture](architecture.md) page explains the pieces they name; the
[conventions](conventions.md) page refers to them by number.

1. **Row cache and tab callbacks are reset together.** `_setup_table` clears `_all_rows`/`_filtered_rows`;
   `_reset_table_state` clears those *and* every callback and the pagination buttons. A loader that fails
   mid-fetch must leave an empty table, never the previous type's rows under the new type's Delete
   handler. That was a real wrong-target delete (`tests/qgis/test_dlg_main.py` guards it).
2. **Qt's table sorting stays off** (`_setup_table` forces it); a header click sorts `_filtered_rows` itself
   (`_on_header_clicked`), so the order on screen *is* the order of the row cache. Rows are mapped back by
   index, and Qt reordering the items on its own would make *Delete Selected* act on a different resource
   than the one highlighted. The sort survives a reload of the same tab and is dropped when the columns change.
3. **Edits merge onto what the server has.** GeoServer applies a datastore PUT by *replacing* the whole
   `connectionParameters` map. Never route an edit through the typed `create_*` helpers. Use
   `_update_datastore_from_values`, which overlays only the form's own keys onto the fetched params and
   keeps the server's `type`; `enabled` is the edit form's checkbox when it has one, else the server's.
   GeoServer ignores `enabled: false` on a POST (the store is created enabled, measured on 2.28.5). Only a
   PUT disables one, which is why the checkbox exists in edit mode only.
4. **Add refuses an existing name.** `create_workspace` / `create_datastore` are upserts (POST, then PUT
   on 409). Check `_resource_exists` first or a live resource is silently reconfigured and reported "created".
5. **Never show a password.** GeoServer returns `passwd` and `WFSDataStoreFactory:PASSWORD` encrypted (`crypt1:…`) or
   not at all; prefilled, the ciphertext would read as the password and get edited into garbage. GeoServer *does*
   accept its own ciphertext back (measured on 2.28.5: a PostGIS store still listed its tables after the round
   trip, and stopped doing so with a wrong plaintext). So on edit the field is blank. Blank means **keep** (the stored
   value is sent back) and typed means **replace**. The encryption is randomised: the same plaintext saves as a
   different `crypt1:` value every time, so ciphertexts cannot be compared.
6. **No rename for datastores** (`name` is read-only in edit mode). A rename would upsert: duplicate the
   store, or overwrite whatever holds the new name.
7. **Delete confirmations name the cascade.** Both delete paths send `recurse=true`.
8. **`isVisible()` lies on inactive tab pages.** `ResourceFormDialog` tracks hidden fields in
   `_hidden_keys`; validation uses that, not Qt, and switches to the tab holding the offending field.
9. **A fetch never touches a widget.** It runs in a worker thread; everything it learns comes
   back as `(rows, failures)` and is rendered by `_render_rows` on the GUI thread. A cancelled
   or failed load renders nothing, which is safe only because the loader reset the table
   *before* starting the task. That is what keeps "no stale rows" true here too. An upload's
   `work(task)` is held to the same rule: the file, the paths and the REST client are arguments
   captured on the GUI side, and progress goes through `task.setProgress`.
10. **A loaded table outlives its connection.** `refresh_ui()` clears `self.gs` at once and re-probes in a
   task, so for up to `PROBE_TIMEOUT` the rows on screen and their buttons belong to a client that is gone.
   Every user-triggered action therefore passes `_require_connection()`, and that check lives at the five
   places actions are dispatched: the Add button, Delete Selected, the row-action buttons, the link-cell
   click and the Del key (a selection change re-enables the button while the probe runs). It never lives in
   the twenty methods behind them, so a new tab cannot forget it. A refresh also disables the
   header buttons immediately; the loader re-arms them. This was a reported crash:
   `AttributeError: 'NoneType' object has no attribute 'get_workspaces'` from *Publish a Layer*.
11. **Nav labels in `TABS` are logic keys as well as text.** The `tr("Actions")` column and the
   `tr("Workspace")` key in `_extra_click_callbacks` must match the header strings exactly.
