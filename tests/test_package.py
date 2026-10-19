from __future__ import annotations

import importlib.metadata

import datajoint as dj

import dj_plotly_codecs as m


def test_version():
    assert importlib.metadata.version("dj_plotly_codecs") == m.__version__


def test_entry_point():
    (entry_point,) = importlib.metadata.entry_points(
        group="datajoint.codecs", name="plotly"
    )
    assert entry_point.load() is m.PlotlyCodec


def test_codec_registered():
    assert isinstance(dj.get_codec("plotly"), m.PlotlyCodec)
