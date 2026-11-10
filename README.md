# dj-plotly-codecs

DataJoint codecs for storing [Plotly](https://plotly.com/python/) figures as
JSON files with schema-addressed paths.

## Overview

This package provides a DataJoint codec that stores Plotly figures as standard
Plotly JSON files in object storage, using DataJoint's schema-addressed storage
system. The stored file is the one `Figure.write_json` writes: Plotly reads it
back with `plotly.io.read_json`, and any page that loads Plotly's JavaScript
renders it with `Plotly.newPlot`. The `.plotly.json` file name and the codec
type tell tools that a column holds figures, not arbitrary JSON.

## Features

- **Renderable files**: every stored figure is a standard Plotly JSON file
- **Validated**: with plotly installed, a figure is validated on insert
- **Lazy loading**: the number of traces, their types, the title, and the file
  size are known without downloading the file
- **Plotly optional**: dict figures are stored without plotly installed; plotly
  adds validation and `Figure` objects on fetch
- **Schema-addressed storage**: paths mirror the database structure
  (`{schema}/{table}/{pk}/{field}_{token}.plotly.json`)
- **Automatic registration**: the codec is available after installation

## Installation

```bash
pip install "dj-plotly-codecs[plotly]"
```

Requires Python 3.10 or later and `datajoint>=2.3.4`.

Without the `plotly` extra, the codec stores and loads dict figures, without
validation and without `Figure` objects.

## Quick Start

```python
import datajoint as dj
import plotly.graph_objects as go

schema = dj.Schema("my_schema")


@schema
class TuningPlot(dj.Manual):
    definition = """
    cell_id : int32
    ---
    figure : <plotly@>       # a figure any Plotly viewer renders
    """


fig = go.Figure(go.Scatter(x=[0, 45, 90, 135], y=[2.1, 5.3, 1.8, 0.9]))
fig.update_layout(title="Orientation tuning")
TuningPlot.insert1({"cell_id": 1, "figure": fig})

# Fetch returns a lazy reference
ref = (TuningPlot & {"cell_id": 1}).fetch1("figure")
print(ref.traces, ref.trace_types, ref.title)  # 1 ['scatter'] Orientation tuning
ref.to_figure().show()  # downloads the file; a plotly Figure
figure = ref.load()  # the figure as a dict
```

## Configuration

Configure your object storage in DataJoint:

```python
dj.config["stores"] = {
    "mystore": {
        "protocol": "s3",
        "endpoint": "s3.amazonaws.com",
        "bucket": "my-bucket",
        "location": "datajoint",
    }
}
```

## Codecs

### `<plotly@>` / `<plotly@store>`

Store Plotly figures as `.plotly.json` files with schema-addressed paths.

**Accepted values:**

| value                                | stored as                                |
| ------------------------------------ | ---------------------------------------- |
| `plotly.graph_objects.Figure`        | `plotly.io.to_json(figure)`              |
| dict with `data`, `layout`, `frames` | validated by plotly when it is installed |

A dict figure has a `data` list of traces and optional `layout` and `frames`, as
`Figure.to_plotly_json()` returns. Anything else is refused rather than stored,
and so is a figure plotly finds invalid. With plotly installed, the file is
exactly what `Figure.write_json` writes; plotly 6 and later write numpy arrays
as base64 typed arrays, which Plotly.js 2.28 and later render. Without plotly
installed, a dict figure is written as plain JSON: numpy arrays as lists, NaN
and infinity as `null`, dates and times as ISO 8601 strings.

**On fetch**, a `PlotlyRef`:

| member                                   | needs the file   |
| ---------------------------------------- | ---------------- |
| `traces`, `trace_types`, `title`, `size` | no               |
| `load()`: the figure as a dict           | yes              |
| `to_figure()`: a plotly `Figure`         | yes (and plotly) |

**Usage:**

```python
class MyTable(dj.Manual):
    definition = """
    id : int32
    ---
    figure : <plotly@>       # Default store
    summary : <plotly@s3>    # Specific store
    """
```

## Development

### Setup

```bash
git clone https://github.com/datajoint/dj-plotly-codecs.git
cd dj-plotly-codecs
pip install -e ".[plotly]"
```

### Testing

```bash
pytest
```

The database tests start MySQL in Docker through testcontainers and are skipped
when Docker is not available.

### Code Style

This project uses [Ruff](https://docs.astral.sh/ruff/) for linting and
formatting:

```bash
ruff check src tests
ruff format src tests
```

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request

## License

Apache License 2.0. Copyright 2026 DataJoint Inc. See [LICENSE](LICENSE) for
details.

## Related Projects

- [DataJoint](https://datajoint.com) - Framework for scientific data pipelines
- [dj-png-codecs](https://github.com/datajoint/dj-png-codecs) - DataJoint codecs
  for images as PNG files
- [dj-zarr-codecs](https://github.com/datajoint/dj-zarr-codecs) - DataJoint
  codecs for Zarr arrays
- [datajoint-python](https://github.com/datajoint/datajoint-python) - DataJoint
  for Python

## Documentation & Support

- [DataJoint Documentation](https://docs.datajoint.com) - Complete DataJoint
  documentation
- [GitHub Issues](https://github.com/datajoint/dj-plotly-codecs/issues) - Report
  bugs and request features
