"""Plotly figure codec implementation for DataJoint."""

from __future__ import annotations

import datetime as dt
import json
import math
from collections.abc import Mapping
from typing import Any

import numpy as np
from datajoint import DataJointError
from datajoint.builtin_codecs import SchemaCodec

EXTENSION = ".plotly.json"
_KEYS = frozenset({"data", "layout", "frames"})


def _plotly_io() -> Any:
    """``plotly.io``, or None when plotly is not installed."""
    try:
        import plotly.io as pio  # noqa: PLC0415
    except ImportError:
        return None
    return pio


def _is_figure_object(value: Any) -> bool:
    """True for a plotly ``Figure`` (anything with ``to_plotly_json``)."""
    return callable(getattr(value, "to_plotly_json", None))


def _check_figure_dict(figure: Mapping[str, Any]) -> None:
    """Raise unless ``figure`` has the structure of a Plotly figure."""
    unknown = sorted(str(k) for k in set(figure) - _KEYS)
    if unknown:
        msg = (
            "<plotly> figures have the keys 'data', 'layout' and 'frames' only, "
            f"got {unknown}"
        )
        raise DataJointError(msg)
    data = figure.get("data")
    if not isinstance(data, (list, tuple)):
        msg = "<plotly> requires a figure with a 'data' list of traces"
        raise DataJointError(msg)
    if not all(isinstance(trace, Mapping) for trace in data):
        msg = "<plotly> requires every trace in 'data' to be a dict"
        raise DataJointError(msg)
    if not isinstance(figure.get("layout", {}), Mapping):
        msg = "<plotly> requires the figure's 'layout' to be a dict"
        raise DataJointError(msg)
    if not isinstance(figure.get("frames", []), (list, tuple)):
        msg = "<plotly> requires the figure's 'frames' to be a list"
        raise DataJointError(msg)


def figure_to_dict(figure: Any) -> dict[str, Any]:
    """
    Return a figure as a plain dict, checking that it is one.

    Parameters
    ----------
    figure : plotly.graph_objects.Figure or dict
        A plotly ``Figure``, or a dict with a ``data`` list of traces and optional
        ``layout`` and ``frames``, as ``Figure.to_plotly_json()`` returns.

    Returns
    -------
    dict
        The figure's ``data``, ``layout`` and ``frames``.

    Raises
    ------
    DataJointError
        If the value is not a figure.
    """
    if _is_figure_object(figure):
        figure = figure.to_plotly_json()
    elif not isinstance(figure, Mapping):
        msg = (
            "<plotly> requires a plotly Figure or a dict with 'data' and 'layout', "
            f"got {type(figure).__name__}"
        )
        raise DataJointError(msg)
    _check_figure_dict(figure)
    return dict(figure)


def _jsonable(value: Any) -> Any:
    """Plain JSON values, as plotly writes them: arrays as lists, NaN and inf as null."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return _jsonable(value.tolist())
    if isinstance(value, np.generic):
        return _jsonable(value.item())
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    msg = f"<plotly> cannot store a value of type {type(value).__name__} in a figure"
    raise DataJointError(msg)


def encode_plotly(figure: Any) -> bytes:
    """
    Encode a Plotly figure as the bytes of a JSON file.

    With plotly installed, the figure is validated and serialized by
    ``plotly.io.to_json``, as ``Figure.write_json`` writes it. Without plotly, a dict
    figure is checked for its structure and written as plain JSON: numpy arrays as
    lists, NaN and infinity as ``null``, dates and times as ISO 8601 strings.

    Parameters
    ----------
    figure : plotly.graph_objects.Figure or dict
        The figure.

    Returns
    -------
    bytes
        A UTF-8 JSON file that Plotly reads with ``plotly.io.read_json`` and renders
        in a browser with ``Plotly.newPlot``.

    Raises
    ------
    DataJointError
        If the value is not a figure, or plotly finds it invalid.
    """
    as_dict = figure_to_dict(figure)
    pio = _plotly_io()
    if pio is None:
        text = json.dumps(_jsonable(as_dict), separators=(",", ":"), allow_nan=False)
    else:
        try:
            text = pio.to_json(figure if _is_figure_object(figure) else as_dict)
        except ValueError as e:
            msg = f"<plotly> invalid figure: {e}"
            raise DataJointError(msg) from e
    return text.encode()


def decode_plotly(data: bytes) -> dict[str, Any]:
    """
    Decode the bytes of a figure's JSON file.

    Parameters
    ----------
    data : bytes
        A JSON file written by :func:`encode_plotly` or by plotly's ``write_json``.

    Returns
    -------
    dict
        The figure's ``data``, ``layout`` and ``frames``.

    Raises
    ------
    DataJointError
        If the file is not JSON or not a figure.
    """
    try:
        figure = json.loads(data)
    except ValueError as e:
        msg = f"<plotly> file is not JSON: {e}"
        raise DataJointError(msg) from e
    if not isinstance(figure, dict):
        msg = "<plotly> file is not a figure"
        raise DataJointError(msg)
    _check_figure_dict(figure)
    return figure


def _summary(figure: Mapping[str, Any]) -> dict[str, Any]:
    """What the row records about a figure: its traces, their types, and its title."""
    types = [str(trace.get("type", "scatter")) for trace in figure["data"]]
    title = figure.get("layout", {}).get("title")
    if isinstance(title, Mapping):
        title = title.get("text")
    return {
        "traces": len(types),
        "trace_types": list(dict.fromkeys(types)),
        "title": title if isinstance(title, str) else None,
    }


class PlotlyRef:
    """
    Lazy reference to a Plotly figure stored as a ``.plotly.json`` file.

    The number of traces, their types, the title, and the file's size are known
    without downloading the file. :meth:`load` downloads it and returns the figure
    as a dict; :meth:`to_figure` returns a plotly ``Figure``.
    """

    __slots__ = ("_backend", "_cached", "_meta")

    def __init__(self, metadata: dict[str, Any], backend: Any) -> None:
        """
        Initialize from the row's metadata and the storage backend.

        Parameters
        ----------
        metadata : dict
            JSON metadata: ``{path, store, size, traces, trace_types, title}``.
        backend : StorageBackend
            Storage backend for file operations.
        """
        self._meta = metadata
        self._backend = backend
        self._cached: dict[str, Any] | None = None

    @property
    def path(self) -> str:
        """Storage path within the store."""
        return str(self._meta["path"])

    @property
    def store(self) -> str | None:
        """Store name (None for the default store)."""
        store = self._meta.get("store")
        return None if store is None else str(store)

    @property
    def size(self) -> int:
        """Size of the JSON file in bytes (no I/O required)."""
        return int(self._meta["size"])

    @property
    def traces(self) -> int:
        """Number of traces (no I/O required)."""
        return int(self._meta["traces"])

    @property
    def trace_types(self) -> list[str]:
        """Trace types, each once, in order of appearance (no I/O required)."""
        return list(self._meta["trace_types"])

    @property
    def title(self) -> str | None:
        """The figure's title, if it has one (no I/O required)."""
        title = self._meta.get("title")
        return None if title is None else str(title)

    @property
    def is_loaded(self) -> bool:
        """True if the figure has been downloaded and cached."""
        return self._cached is not None

    def load(self) -> dict[str, Any]:
        """
        Download, decode, and return the figure.

        Returns
        -------
        dict
            The figure's ``data``, ``layout`` and ``frames``, as JSON values. The
            dict is cached: modify a copy.
        """
        if self._cached is None:
            self._cached = decode_plotly(self._backend.get_buffer(self.path))
        return self._cached

    def to_figure(self) -> Any:
        """
        Return the figure as a plotly ``Figure``.

        Returns
        -------
        plotly.graph_objects.Figure
            A new figure built from :meth:`load`.

        Raises
        ------
        DataJointError
            If plotly is not installed.
        """
        try:
            import plotly.graph_objects as go  # noqa: PLC0415
        except ImportError as e:
            msg = "<plotly> to_figure() requires plotly: pip install 'dj-plotly-codecs[plotly]'"
            raise DataJointError(msg) from e
        return go.Figure(self.load())

    def __repr__(self) -> str:
        status = "loaded" if self.is_loaded else "not loaded"
        return (
            f"PlotlyRef(traces={self.traces}, trace_types={self.trace_types}, {status})"
        )


def _require_context(context: dict[str, Any] | None, *names: str) -> dict[str, Any]:
    """
    Return ``context``, checked to carry ``names``.

    DataJoint 2.3.4 and later pass ``context`` to every codec that declares it:
    ``schema``, ``table``, ``field``, and ``config`` on insert, ``config`` on
    fetch. The codec reads them there only, never from underscore keys in ``key``.
    """
    missing = [n for n in names if context is None or context.get(n) is None]
    if context is None or missing:
        msg = (
            "<plotly> needs the context that DataJoint 2.3.4 and later pass to codecs "
            f"(missing: {', '.join(missing)}); install datajoint>=2.3.4"
        )
        raise DataJointError(msg)
    return context


def _primary_key(key: dict[str, Any] | None) -> dict[str, Any]:
    """The primary key values in ``key``, without the underscore keys DataJoint 2.3 adds."""
    return {k: v for k, v in (key or {}).items() if not k.startswith("_")}


class PlotlyCodec(SchemaCodec):  # type: ignore[misc]
    """
    Schema-addressed storage for Plotly figures as ``.plotly.json`` files.

    The ``<plotly@>`` codec stores a figure as the standard JSON file that Plotly
    reads (``plotly.io.read_json``) and that ``Plotly.newPlot`` renders in a
    browser, using the same schema-addressed paths as ``<npy@>``:
    ``{schema_prefix}/{schema}/{table}/{pk}/{attribute}_{token}.plotly.json``.

    Store only - requires ``@`` modifier. Installing ``dj-plotly-codecs``
    registers ``<plotly@>`` with DataJoint through the ``datajoint.codecs``
    entry point. Plotly itself is optional (``dj-plotly-codecs[plotly]``): it
    validates figures on insert and builds ``Figure`` objects on fetch.

    Accepted values:
        - a ``plotly.graph_objects.Figure``
        - a dict with a ``data`` list of traces and optional ``layout`` and
          ``frames``, as ``Figure.to_plotly_json()`` returns

    Anything else is refused, and so is a figure plotly finds invalid.

    Example::

        @schema
        class TuningPlot(dj.Computed):
            definition = '''
            -> Tuning
            ---
            figure : <plotly@>     # a figure any Plotly viewer renders
            '''

            def make(self, key):
                fig = go.Figure(go.Scatter(x=angles, y=rates))
                self.insert1({**key, "figure": fig})

        ref = (TuningPlot & key).fetch1("figure")  # PlotlyRef (lazy)
        ref.traces, ref.trace_types, ref.title     # no download
        ref.to_figure().show()                     # downloads the file

    Storage Details:
        - File format: JSON, as ``Figure.write_json`` writes it
        - Path: ``{schema_prefix}/{schema}/{table}/{pk}/{attribute}_{token}.plotly.json``
        - Database column: JSON with ``{path, store, size, traces, trace_types, title}``

    Deletion: Requires garbage collection via ``dj.gc.GarbageCollector``.

    See Also
    --------
    PlotlyRef : The lazy figure reference returned on fetch.
    """

    name = "plotly"

    def validate(self, value: Any) -> None:
        """
        Validate that value is a Plotly figure.

        Raises
        ------
        DataJointError
            If value is neither a plotly ``Figure`` nor a dict with the structure of
            one.
        """
        figure_to_dict(value)

    def encode(
        self,
        value: Any,
        *,
        key: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        store_name: str | None = None,
    ) -> dict[str, Any]:
        """
        Encode the figure as JSON and upload it to storage.

        Returns
        -------
        dict
            JSON metadata: ``{path, store, size, traces, trace_types, title}``.

        Raises
        ------
        DataJointError
            If ``context`` lacks the ``schema``, ``table``, ``field``, or
            ``config`` that DataJoint 2.3.4 and later pass.
        """
        context = _require_context(context, "schema", "table", "field", "config")
        config = context["config"]
        data = encode_plotly(value)
        path, _ = self._build_path(
            context["schema"],
            context["table"],
            context["field"],
            _primary_key(key),
            ext=EXTENSION,
            store_name=store_name,
            config=config,
        )
        backend = self._get_backend(store_name, config=config)
        backend.put_buffer(data, path)
        # Record the store by name; DataJoint 2.3 has no resolver and keeps None for the default store.
        resolve = getattr(config, "resolve_store_name", None)
        return {
            "path": path,
            "store": resolve(store_name) if resolve else store_name,
            "size": len(data),
            **_summary(decode_plotly(data)),
        }

    def decode(
        self,
        stored: dict[str, Any],
        *,
        key: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> PlotlyRef:
        """
        Create a lazy PlotlyRef from stored metadata.

        Raises
        ------
        DataJointError
            If ``context`` lacks the ``config`` that DataJoint 2.3.4 and later pass.
        """
        del key  # the stored metadata locates the file
        config = _require_context(context, "config")["config"]
        backend = self._get_backend(stored.get("store"), config=config)
        return PlotlyRef(stored, backend)
