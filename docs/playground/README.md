# TACO viewer

Browser viewer for TACO datasets, built on `@asterisk-labs/taco`. It opens the
[`taco-api-fixtures`](https://huggingface.co/datasets/asterisk-labs/taco-api-fixtures)
or any public dataset URL (`?url=` works too), plots sample centroids, and shows
the metadata of a sample down to its files.

```bash
make site
python -m http.server 8000
```

Open `http://localhost:8000/_site/playground/`.
