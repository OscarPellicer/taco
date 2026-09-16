# TACO viewer

A minimal browser viewer for the public
[`asterisk-labs/taco-api-fixtures`](https://huggingface.co/datasets/asterisk-labs/taco-api-fixtures).

The page uses `@asterisk-labs/taco` to open FOLDER, ZIP, and TACOCAT fixtures.
It plots the EPSG:4326 centroid produced by Spatial, ISpatial, STAC, or ISTAC
metadata. Full geometries remain available in the metadata. If a selected
fixture has no centroid, the viewer opens the next compatible fixture.

The top bar also accepts any public HTTP or HTTPS TACO dataset URL. `Copy link`
creates a shareable playground URL with the dataset encoded in the `url` query
parameter; opening that link loads the same dataset automatically.

Click a point to inspect its metadata from `sample.parquet` down to its deepest
metadata level. Payload rows expose the calculated `taco:location`; files can
copy that location or download their bytes, and Rumi assets support direct
range reads.

`Dataset`, next to the fixture control, shows the collection summary, coverage,
contract graph, payload leaves, and metadata schemas.

Run it from the repository root:

```bash
python -m http.server 8000
```

Then open `http://localhost:8000/_site/playground/` after running `make site`.
