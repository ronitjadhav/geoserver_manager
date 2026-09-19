#! python3  # noqa: E265

"""
GeoServer's JSON payload shapes, tolerated in one place.

A collection comes back as `{"layers": {"layer": [...]}}`, but an empty one
is `{"layers": ""}`, a one-entry one may wrap a bare object — or, for the
`list=available` and GeoWebCache answers, a bare string — instead of a
one-item list. Every tab used to carry its own copy of these rules.

No QGIS import: the unit suite runs this on a plain Python.
"""


def unwrap(payload, list_key, item_key):
    """Entries of a collection payload, always as a list."""
    container = payload.get(list_key) if isinstance(payload, dict) else None
    if not isinstance(container, dict):
        return []
    items = container.get(item_key) or []
    if isinstance(items, (dict, str)):
        return [items]
    return list(items)


def as_list(value):
    """A GeoWebCache collection: "" when empty, bare when it has one entry."""
    if value in (None, ""):
        return []
    return [value] if isinstance(value, (dict, str)) else list(value)


def name_of(item):
    """Name of a list entry: geoservercloud returns dicts, tolerate strings."""
    return item.get("name", str(item)) if isinstance(item, dict) else str(item)


def crs_text(value):
    """A CRS, which GeoServer gives either as a string or as {"$": …}."""
    if isinstance(value, dict):
        return str(value.get("$", ""))
    return "" if value is None else str(value)


def bbox_text(box):
    """One line for a bounding box, or "" when it is not one.

    `minx, miny → maxx, maxy  (crs)` — the same words on every tab.
    """
    if not isinstance(box, dict) or not {"minx", "miny", "maxx", "maxy"} <= set(box):
        return ""
    text = "{minx}, {miny} → {maxx}, {maxy}".format(
        **{key: box[key] for key in ("minx", "miny", "maxx", "maxy")}
    )
    crs = crs_text(box.get("crs"))
    return f"{text}  ({crs})" if crs else text
