# taco

Read and write TACO datasets in Python.

```bash
pip install taco-eo
python examples/minimal.py
```

```python
import taco

samples = taco.read("dataset.zip")
parts = taco.read(["part-0.zip", "part-1.zip"])
```

Versioned dataset roots select their declared default release without listing
remote storage. Use a release URL to open an immutable version directly.

```python
dataset = taco.open_dataset("https://data.source.coop/major-tom/core-dem/")
print(dataset.version)
print(dataset.versions)

previous = taco.open_dataset("https://data.source.coop/major-tom/core-dem/1.0.0/")
```

## Examples

Every example is self-contained, uses synthetic data, and writes its output in
the current directory.

Spatial and temporal metadata use separate profiles: `Spatial` for regular
spatial grids, `ISpatial` for irregular footprints, and `Temporal` for time
alone. `STAC` combines regular spatial + temporal metadata; `ISTAC` combines
irregular spatial + temporal metadata.

| Example | What it demonstrates |
| --- | --- |
| [`minimal.py`](examples/minimal.py) | Smallest possible single-file dataset |
| [`numpy_minimal.py`](examples/numpy_minimal.py) | NumPy image and mask assets with a train/test split |
| [`change_detection.py`](examples/change_detection.py) | Metadata on `before/` and `after/` folders |
| [`sequence.py`](examples/sequence.py) | Variable-length asset sequences |
| [`time_series.py`](examples/time_series.py) | Per-observation time and cloud metadata |
| [`geospatial.py`](examples/geospatial.py) | Compact STAC metadata and derived MajorTOM cells |
| [`stac_segmentation.py`](examples/stac_segmentation.py) | STAC extensions for regular raster chips, labels, bands, and scaling |
| [`oceantaco_istac.py`](examples/oceantaco_istac.py) | OceanTACO-inspired ISTAC metadata for irregular SWOT swaths and Argo collocations |
| [`partitioned.py`](examples/partitioned.py) | ZIP partitions and their TACOCAT catalog |
