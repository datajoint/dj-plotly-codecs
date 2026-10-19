"""
dj-plotly-codecs: Plotly figure storage for DataJoint
"""

from __future__ import annotations

from ._version import version as __version__
from .codecs import (
    EXTENSION,
    PlotlyCodec,
    PlotlyRef,
    decode_plotly,
    encode_plotly,
    figure_to_dict,
)

__all__ = [
    "EXTENSION",
    "PlotlyCodec",
    "PlotlyRef",
    "__version__",
    "decode_plotly",
    "encode_plotly",
    "figure_to_dict",
]
