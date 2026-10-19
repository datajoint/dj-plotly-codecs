from __future__ import annotations

import base64
import datetime as dt
import json
from typing import Any

import datajoint as dj
import numpy as np
import plotly.graph_objects as go
import plotly.io as pio
import pytest

from dj_plotly_codecs import (
    EXTENSION,
    PlotlyCodec,
    PlotlyRef,
    codecs,
    decode_plotly,
    encode_plotly,
    figure_to_dict,
)


def _figure() -> go.Figure:
    fig = go.Figure(go.Scatter(x=[0, 45, 90], y=[1.0, 2.5, 0.5], name="rate"))
    fig.add_trace(go.Bar(x=["a", "b"], y=[3, 4]))
    fig.update_layout(title="Tuning")
    return fig


@pytest.fixture
def without_plotly(monkeypatch: pytest.MonkeyPatch) -> None:
    """Encode as if plotly were not installed."""
    monkeypatch.setattr(codecs, "_plotly_io", lambda: None)


# Format, without a database


def test_figure_roundtrip() -> None:
    fig = _figure()
    decoded = decode_plotly(encode_plotly(fig))
    assert go.Figure(decoded) == fig
    assert [t["type"] for t in decoded["data"]] == ["scatter", "bar"]


def test_file_is_what_plotly_writes() -> None:
    fig = _figure()
    assert encode_plotly(fig) == pio.to_json(fig).encode()
    assert pio.from_json(encode_plotly(fig).decode()) == fig


def test_dict_figure_is_validated_by_plotly() -> None:
    figure = {"data": [{"type": "scatter", "y": [1.0, float("nan")]}]}
    decoded = decode_plotly(encode_plotly(figure))
    assert decoded["data"][0]["y"] == [1.0, None]
    with pytest.raises(dj.DataJointError, match="invalid figure"):
        encode_plotly({"data": [{"type": "scatter", "not_a_property": 1}]})


@pytest.mark.usefixtures("without_plotly")
def test_dict_figure_without_plotly() -> None:
    figure = {
        "data": [
            {
                "type": "scatter",
                "x": np.array([dt.date(2026, 1, 2), dt.date(2026, 1, 3)]),
                "y": np.array([1.5, np.nan]),
                "marker": {"size": np.int64(4)},
            }
        ],
        "layout": {"title": {"text": "Rates"}},
    }
    data = encode_plotly(figure)
    assert json.loads(data) == {
        "data": [
            {
                "type": "scatter",
                "x": ["2026-01-02", "2026-01-03"],
                "y": [1.5, None],
                "marker": {"size": 4},
            }
        ],
        "layout": {"title": {"text": "Rates"}},
    }


@pytest.mark.usefixtures("without_plotly")
def test_without_plotly_refuses_unknown_values() -> None:
    with pytest.raises(dj.DataJointError, match="cannot store a value of type"):
        encode_plotly({"data": [{"y": [object()]}]})


@pytest.mark.parametrize(
    "value",
    [
        [1, 2, 3],
        "figure",
        np.zeros(3),
        {"layout": {}},
        {"data": {"type": "scatter"}},
        {"data": [1, 2]},
        {"data": [], "layout": []},
        {"data": [], "frames": {}},
        {"data": [], "config": {}},
    ],
    ids=[
        "list",
        "str",
        "array",
        "no data",
        "data not a list",
        "trace not a dict",
        "layout not a dict",
        "frames not a list",
        "unknown key",
    ],
)
def test_refuses(value: object) -> None:
    with pytest.raises(dj.DataJointError):
        PlotlyCodec().validate(value)
    with pytest.raises(dj.DataJointError):
        encode_plotly(value)


@pytest.mark.parametrize("data", [b"not json", b"[1, 2]", b'{"layout": {}}'])
def test_decode_refuses(data: bytes) -> None:
    with pytest.raises(dj.DataJointError):
        decode_plotly(data)


def test_figure_to_dict() -> None:
    assert figure_to_dict(_figure())["layout"]["title"]["text"] == "Tuning"
    assert figure_to_dict({"data": []}) == {"data": []}


def test_plotly_ref_metadata_and_repr() -> None:
    ref = PlotlyRef(
        {
            "path": "x/figure_ab.plotly.json",
            "store": None,
            "size": 1234,
            "traces": 2,
            "trace_types": ["scatter", "bar"],
            "title": "Tuning",
        },
        backend=None,
    )
    assert (ref.size, ref.traces, ref.trace_types, ref.title) == (
        1234,
        2,
        ["scatter", "bar"],
        "Tuning",
    )
    assert ref.store is None
    assert not ref.is_loaded
    assert (
        repr(ref) == "PlotlyRef(traces=2, trace_types=['scatter', 'bar'], not loaded)"
    )


class _Backend:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.reads = 0

    def get_buffer(self, path: str) -> bytes:
        assert path.endswith(EXTENSION)
        self.reads += 1
        return self.data


def test_plotly_ref_loads_once() -> None:
    backend = _Backend(encode_plotly(_figure()))
    ref = PlotlyRef(
        {
            "path": "f.plotly.json",
            "store": None,
            "size": 1,
            "traces": 2,
            "trace_types": ["scatter", "bar"],
            "title": "Tuning",
        },
        backend,
    )
    assert ref.load()["layout"]["title"]["text"] == "Tuning"
    assert ref.to_figure() == _figure()
    assert backend.reads == 1


def test_to_figure_without_plotly(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins  # noqa: PLC0415

    real_import = builtins.__import__

    def no_plotly(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.startswith("plotly"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_plotly)
    ref = PlotlyRef(
        {
            "path": "f.plotly.json",
            "store": None,
            "size": 1,
            "traces": 0,
            "trace_types": [],
            "title": None,
        },
        _Backend(b'{"data": []}'),
    )
    assert ref.load() == {"data": []}
    with pytest.raises(
        dj.DataJointError, match=r"pip install 'dj-plotly-codecs\[plotly\]'"
    ):
        ref.to_figure()


# Through DataJoint, with a database and a file store


def _declare(schema: dj.Schema) -> Any:
    @schema
    class Plot(dj.Manual):  # type: ignore[misc]
        definition = """
        id : int32
        ---
        figure : <plotly@store>
        """

    return Plot


def test_figure_roundtrip_through_datajoint(schema: dj.Schema) -> None:
    plot = _declare(schema)
    fig = _figure()
    plot.insert1({"id": 1, "figure": fig})
    ref = (plot & {"id": 1}).fetch1("figure")
    assert isinstance(ref, PlotlyRef)
    filename = ref.path.rsplit("/", 1)[1]
    assert filename.startswith("figure_")
    assert filename.endswith(EXTENSION)
    assert (ref.traces, ref.trace_types, ref.title) == (2, ["scatter", "bar"], "Tuning")
    assert ref.size == len(encode_plotly(fig))
    assert not ref.is_loaded
    assert ref.to_figure() == fig


def test_dict_roundtrip_through_datajoint(schema: dj.Schema) -> None:
    plot = _declare(schema)
    figure = {"data": [{"type": "heatmap", "z": np.eye(3)}], "layout": {}}
    plot.insert1({"id": 1, "figure": figure})
    ref = (plot & {"id": 1}).fetch1("figure")
    assert ref.trace_types == ["heatmap"]
    assert ref.title is None
    # stored as plotly writes it: since plotly 6, an array as a base64 typed array
    loaded = ref.load()
    assert loaded == json.loads(pio.to_json(figure))
    z = loaded["data"][0]["z"]
    array = np.frombuffer(base64.b64decode(z["bdata"]), z["dtype"])
    np.testing.assert_array_equal(array.reshape(3, 3), np.eye(3))


def test_insert_refuses_non_figure(schema: dj.Schema) -> None:
    plot = _declare(schema)
    with pytest.raises(dj.DataJointError):
        plot.insert1({"id": 1, "figure": np.zeros((4, 4))})
