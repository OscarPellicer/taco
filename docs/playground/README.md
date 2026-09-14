# TACO viewer

A minimal browser viewer for the public
[`asterisk-labs/taco-api-fixtures`](https://huggingface.co/datasets/asterisk-labs/taco-api-fixtures).

The page uses `@asterisk-labs/taco` to open FOLDER, ZIP, and TACOCAT fixtures.
It plots one point per sample from the EPSG:4326 centroid produced by Spatial,
ISpatial, STAC, or ISTAC metadata. Geometry and footprints remain metadata: the
map deliberately represents every sample by its centroid. A programmatically
requested fixture without one still falls forward to the next compatible case
while preserving the container topology.

The top bar also accepts any public HTTP or HTTPS TACO dataset URL. `Copy link`
creates a shareable playground URL with the dataset encoded in the `url` query
parameter; opening that link loads the same dataset automatically.

Click a point to follow its metadata from `sample.parquet` to the deepest
metadata Parquet. Payload rows expose the reader-calculated `taco:location`;
every file can copy its location or download its bytes, and Rumi assets can also
be range-read directly.

`Dataset`, next to the fixture control, opens the global collection separately.
It presents the collection summary, coverage, contract graph, payload leaves,
and each metadata schema without dumping the raw `taco:structure` or
`taco:metadata` objects into a point.

Run it from the repository root:

```bash
python -m http.server 8000
```

Then open `http://localhost:8000/_site/playground/` after running `make site`.

Sammy Carlos Romualdo
