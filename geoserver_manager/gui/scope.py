#! python3  # noqa: E265

"""
The global-or-workspace scope that styles and layer groups share.

Rows are display strings, so the global scope needs a label the user can read;
`scope()` maps it back to the `None` the library wants. Three modules use it
(the two tabs and the main dialog's workspace-link cells), which is the point
at which CLAUDE.md says a shared helper stops living inside one tab.
"""

GLOBAL = "(global)"


def scope(workspace_label):
    """Workspace name for the API, or None for the global scope."""
    return None if workspace_label in ("", GLOBAL) else workspace_label
