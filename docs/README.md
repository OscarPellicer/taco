# TACO website

This directory contains the public website sources. `make site` writes the
generated site to `_site/`; edit the sources here rather than that output.

```text
docs/
├── _build/       site compiler and its Python dependency
├── api/          API cookbook
│   ├── write/    writer documentation
│   └── read/     reader documentation
├── css/          landing-page styles
├── images/       shared website images
├── js/           landing-page behavior
├── onepager/     printable project summary
├── playground/   interactive dataset viewer
├── shared/       components shared by multiple pages
├── spec/         Markdown specification, styles, and figures
└── index.html    landing page
```

Build and validate it from the repository root:

```bash
make site
```

The compiler copies the documentation tree, compiles `spec/SPEC.md` into HTML,
adds the JavaScript reader required by the playground, and validates required
files and local links.
