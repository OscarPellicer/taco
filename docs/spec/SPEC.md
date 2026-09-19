# The TACO Specification

**Version:** 3.0.0

**Status:** Draft

## 1. Version

This document defines version 3.0.0 of the TACO specification. The specification follows Semantic Versioning. Implementations are versioned separately and declare which version of the specification they support.

Every dataset MUST store this version in `COLLECTION.json` as `taco:version`. A reader MUST reject a version it does not support.

TACO v3 is not compatible with v2 datasets. Annex A explains the differences and how to migrate.

### 1.1. Terminology

The words "MUST", "MUST NOT", "SHOULD", "SHOULD NOT", and "MAY" have the meanings defined by RFC 2119 and RFC 8174 when written in uppercase. All other text is explanatory.

## 2. Overview

TACO stands for Transparent Access to Cloud-Optimized datasets. It defines how Earth observation data and metadata are organized, stored, and accessed as one unit.

A machine learning dataset is more than a collection of files. It contains samples, and each sample may contain several files arranged in folders. Metadata may describe the sample, a folder, or an individual file. Existing formats cover parts of this model, but not the complete dataset.

STAC provides a logical model for geospatial data based on Catalogs, Collections, Items, and Assets. It represents that model as JSON, which works well for discovery and interoperability. At training-dataset scale, however, representing every sample as an Item may produce millions of JSON documents. Efficient access then depends heavily on caching.

STAC-GeoParquet stores STAC Items as rows in GeoParquet and their Assets as structs. This enables fast columnar queries without a server, but the result is still a flat table. For example, a change detection sample may contain a `before/` folder, an `after/` folder, and a `change_map.tif` label. STAC-GeoParquet cannot represent those folders as separate entities with their own metadata. It also stores metadata separately from the data files.

TACO models a dataset as a collection of samples that share one structure and metadata schema. Each sample has an integer index, and each file has a predictable path. Metadata is stored in a small set of Parquet files that can be queried with DuckDB.

|  | STAC | STAC-GeoParquet | TACO |
| --- | --- | --- | --- |
| Data model | Collection, Catalog, Item, Asset | Collection, Item (row), Asset (struct) | Collection, Contract, Sample, Folder, Asset |
| Metadata storage | 1 JSON per Item | 1 Parquet per Collection | 1 Parquet per tree level |
| Serverless query method | Catalog traversal | Columnar query | Columnar query |
| Hierarchical samples | Yes | No (flat rows) | Yes (structural contract) |
| Data and metadata stored together | No | No | Yes |
| Shared sample contract | No | No | Yes |
| Self-contained portable unit | No | No | Yes |

## 3. Foundations

TACO combines three existing technologies. Apache Parquet stores queryable metadata. VSI paths identify data on local or remote storage. Cloud-Optimized ZIP packages data and metadata while preserving direct access to individual files.

A dataset may use a FOLDER or ZIP container. FOLDER stores the dataset as a directory. ZIP stores a dataset or partition in one archive. TACOCAT is a catalog that combines the metadata of several ZIP partitions.

### 3.1. Apache Parquet

Apache Parquet stores values by column rather than by row. This lets a query avoid data it does not need.

**Predicate pushdown** uses row-group statistics to skip groups that cannot match a filter. A query such as `WHERE "quality:cloud_cover" < 10` can therefore avoid reading most of the file.

**Projection pushdown** reads only the requested columns. Selecting two columns from a table of fifty does not require reading the other forty-eight.

TACO MUST store tabular metadata in Parquet, with one file for each level of the sample hierarchy. Each file can be queried independently.

A reader SHOULD use predicate and projection pushdown when its query engine supports them. Opening a dataset does not require loading every Parquet file or materializing all metadata.

### 3.2. VSI Path Convention

TACO uses VSI paths to locate data. A VSI path describes how to reach a file on local disk, over HTTP, in object storage, or within a byte range of another file.

```
/vsicurl/https://example.com/scene.tif     reads from HTTP
/vsis3/bucket/scene.tif                     reads from S3
/vsigs/bucket/scene.tif                     reads from Google Cloud
/vsiaz/container/scene.tif                  reads from Azure
```

TACO mainly uses `/vsisubfile/`, which identifies a byte range by its offset and size.

```
/vsisubfile/1024_4096,/data/archive.zip
```

This path reads 4096 bytes at offset 1024 from `archive.zip`. It does not extract the archive. VSI paths can also be combined to read a byte range from a remote file.

```
/vsisubfile/1024_4096,/vsicurl/https://hf.co/dataset.zip
```

A reader MUST construct VSI paths when data is accessed. For ZIP containers, it reads the offset and size from Parquet metadata. For FOLDER containers, it builds the path directly from the contract and sample index, such as `DATA/42/before/B02.tif`.

TACO defines the path convention, not the library that resolves it. GDAL supports VSI paths through tools and libraries such as rasterio, QGIS, gdalwarp, sf, terra, and ArchGDAL. Other implementations are valid if they interpret the same paths and perform the required reads.

### 3.3. Cloud-Optimized ZIP

A cloud-optimized ZIP is a valid ZIP archive that any standard ZIP tool can open. Its first entry begins at byte 0 and contains an index with direct offsets to the metadata files. A TACO reader can use this index without first reading the ZIP Central Directory at the end of the archive.

The index points to the Parquet metadata. The metadata then provides the offsets and sizes needed to access individual data files.

A TACO ZIP MUST conform to version 1.1.0 of the CoZIP specification and use profile 2. It MUST index every Parquet file in `METADATA/` and `COLLECTION.json`. Every entry MUST use STORE mode without compression. The `/vsisubfile/` convention reads raw byte ranges, so compressed entries cannot provide direct access and are invalid.

STORE mode also works well with Content-Defined Chunking on platforms such as Hugging Face. Because unchanged files keep the same raw content inside a rebuilt archive, the platform can often upload only the chunks that changed. Producers SHOULD use a CDC-aware platform when publishing frequently updated ZIP datasets.

## 4. Design Goals

TACO is guided by five design principles.

**Self-contained and portable.** Data and metadata live together in a ZIP file or directory. Using the dataset does not require a database, API server, or external catalog.

**Cloud-optimized.** Readers can filter metadata and access individual files with partial reads. They do not need to download or extract the complete archive.

**Contract-first.** The contract declares the files and metadata expected in every sample. Writers use it to reject missing files, unexpected fields, and inconsistent layouts.

**Supports FAIR datasets.** TACO provides descriptive metadata, identifiers, licensing, spatial and temporal extents, Parquet, and VSI paths. Producers remain responsible for the quality and accessibility of the information they publish.

**Language-agnostic.** One C++ core resolves datasets and generates the reader SQL. Python, R, and Julia call it through a C interface and run that SQL with their own DuckDB client.

### 4.1. Tradeoffs

TACO assumes that every sample in a dataset follows the same contract. The contract is fixed for a dataset version, although new samples may be added as long as they preserve its structure and metadata schema.

This constraint makes the dataset predictable. Readers know which files and metadata levels exist, and the writer can reject incomplete or inconsistent samples.

Changing the structure, adding metadata fields, or changing field types requires a new major dataset version. TACO is not a good fit when samples need to evolve independently within the same version.

## 5. Data Model

The contract has two parts. The structure defines the files in each sample, and the tabular metadata schema defines the fields stored at each level. The collection adds the description and global metadata shared by the complete dataset.

### 5.1. Contract

The contract combines the structure and metadata schema of a dataset. It MUST be declared before any sample is written, and every sample MUST follow it. The contract cannot change within a dataset version.

### 5.2. Structure

The structure defines which files belong to a sample and how they are arranged in folders. It is stored in `taco:structure` as a list of relative file paths. Folders are inferred from the path segments.

Every path MUST be a normalized relative POSIX path. It MUST use `/` as its separator and MUST NOT contain an empty component, `.`, `..`, a leading slash, a trailing slash, or a backslash. Every component MUST use printable ASCII so that the same contract is valid in FOLDER and ZIP containers.

Each path describes either a fixed file or a variable sequence of files.

A **fixed file** appears exactly once in every sample. Its name is written directly in the structure, such as `B02.tif`.

A **variable sequence** allows the number of files to differ between samples. It uses the form `prefix*[a,b].ext`, where `a` is the minimum number of files and `b` is the maximum. The prefix is required, `0 <= a <= b`, and `b` MUST be greater than zero.

The `*` represents a zero-based index, not a filesystem glob. If a sample contains `k` files, their names MUST run from `prefix0.ext` to `prefix{k-1}.ext` without gaps, where `a <= k <= b`. An index MUST NOT contain leading zeros.

Entries in the same folder MUST have unique identifiers. A folder uses its name, a fixed file uses its full name, and a variable sequence uses its prefix. A folder or fixed file MUST NOT have a name produced by a variable sequence, and two variable sequences MUST NOT be able to produce the same filename.

The order of `taco:structure` is significant. A folder takes the position of its first path. Fixed files and folders follow declaration order, while instances of a variable sequence follow their numeric index. Writers MUST use this order when assigning child row identifiers.

#### Examples

**Single file.** When `taco:structure` is null, each sample is one file with no internal structure.

```
{ "taco:structure": null }
```

**Fixed files.** Each CloudSEN12 sample contains the same three files.

```
{
  "taco:structure": [
    "s2_l1c.tif",
    "s2_l2a.tif",
    "target.tif"
  ]
}
```

**Folders.** Each change detection sample contains two folders and one label.

```
{
  "taco:structure": [
    "before/B02.tif",
    "before/B03.tif",
    "before/B04.tif",
    "after/B02.tif",
    "after/B03.tif",
    "after/B04.tif",
    "change_map.tif"
  ]
}
```

**Variable sequence.** Each multitemporal sample contains between 4 and 16 images.

```
{ "taco:structure": ["img*[4,16].tif"] }
```

Each sample contains 4 to 16 files named `img0.tif`, `img1.tif`, and so on, with no gaps in the sequence.

**Fixed and variable files.** The same folder may contain both forms.

```
{
  "taco:structure": [
    "before/B02.tif",
    "before/B03.tif",
    "before/B04.tif",
    "before/mask*[1,5].tif"
  ]
}
```

The identifiers inside `before/` are `B02.tif`, `B03.tif`, `B04.tif`, and `mask`. Each is unique.

If every declared sequence has a minimum of zero, a sample MAY contain no data files. Its row in `sample.parquet` still represents the sample.

### 5.3. Reserved Characters

TACO reserves three tokens so that paths, levels, and metadata fields can be mapped without ambiguity.

| Token | Purpose | Rule |
| --- | --- | --- |
| `:` | Separates a namespace from a field name | Every user field MUST contain exactly one. It MUST NOT appear in folder names, file names, or level keys. |
| `/` | Separates path and level segments | It MAY appear in complete structure paths and level keys. It MUST NOT appear inside a folder or file name. |
| `__` | Replaces `/` in Parquet filenames and wide reader columns | It MUST NOT appear in folder names, file names, namespaces, or metadata field names. |

For example, the level `children/before` is stored in `children__before.parquet`.

Folder and file names MUST NOT contain `<`, `>`, `:`, `"`, `\`, `|`, or `?`, and MUST NOT end with a space or period. The characters `*`, `[`, and `]` are reserved for variable sequence declarations.

### 5.4. Metadata

Tabular metadata describes the sample and the nodes inside it. A node is either a folder or a file. Collection metadata is global to the dataset and is defined separately in Section 5.5.

The tabular metadata schema is written to `taco:metadata`. Each level maps qualified field names to their declarations.

Every field MUST declare the following properties. Its type MUST be representable in Apache Parquet.

| Property | Type | Meaning |
| --- | --- | --- |
| `type` | string | Canonical Arrow type |
| `nullable` | boolean | Whether the stored column may contain null values |
| `description` | string | Human-readable field description; MAY be empty |

| Type family | Canonical forms |
| --- | --- |
| Scalar | `bool`, signed and unsigned integers from 8 to 64 bits, `float16`, `float`, `double`, `string`, `large_string`, `binary`, `large_binary`, `date32`, `date64` |
| Temporal | `timestamp[unit]`, `timestamp[unit, timezone]`, `time32[unit]`, `time64[unit]`, `duration[unit]` |
| Nested and fixed | `list<type>`, `large_list<type>`, `fixed_size_list<type, size>`, `fixed_size_binary[size]`, `struct<name: type, ...>`, `map<key, value>`, `decimal128(precision, scale)`, `decimal256(precision, scale)` |

Integer names are `int8`, `int16`, `int32`, `int64`, `uint8`, `uint16`, `uint32`, and `uint64`. Time units are `s`, `ms`, `us`, and `ns`.

A level identifies what each row describes.

| Level | Rows |
| --- | --- |
| `sample` | One row per sample |
| `children` | One row per direct folder or file below a sample |
| `children/<folder-path>` | One row per direct folder or file below that folder in every sample |

The text after `children/` is the complete folder path from `taco:structure`. For example, `children/before` contains one row for every file directly inside each `before/` folder. A single-file contract has only the `sample` level.

`taco:metadata` MUST include `sample` and every child level implied by the structure. A level with no user fields is stored as an empty object.

Each level becomes one Parquet table. Rows from all samples are stored together and linked to their parents with `internal:parent_id`.

Every user column MUST follow the type and nullability declared in the contract. A non-empty description MUST be stored in the Arrow field metadata under `description`.

#### Namespaces

Every user field MUST use the form `namespace:field`. Namespaces MUST match `[a-z][a-z0-9_]*`. Field names MUST be non-empty and MUST NOT contain `:`, `/`, or `__`. The qualified name MUST be unique within its level.

The same namespace MAY appear at multiple levels and MAY use a different schema at each level. The `internal`, `taco`, and `cozip` namespaces are reserved. Producers MUST NOT create fields in these namespaces.

The column names `cozip:location` and `taco:location` are owned exclusively by readers. A producer MUST NOT store either column in any Parquet file under `METADATA/`. A reader that encounters a stored value under either name MUST ignore or remove it, and MUST calculate locations at read time from the physical payload location, offset, size, and containing file.

On disk, a namespace only qualifies a column name. It does not create a nested struct or identify a Python class. Contracts are equivalent when their structure, levels, qualified fields, types, nullability, descriptions, and writer-time extension declarations are the same.

#### Spatial and temporal profiles

TACO defines five mutually exclusive metadata profiles. `Spatial` is regular spatial metadata, `ISpatial` is irregular spatial metadata, and `Temporal` is temporal metadata. `STAC` combines regular spatial and temporal metadata; `ISTAC` combines irregular spatial and temporal metadata. A metadata level MUST choose at most one profile. These are compact tabular metadata groups, not serializations of a complete STAC Item.

| Profile | Producer inputs | Writer outputs | Spatial representation |
| --- | --- | --- | --- |
| `spatial` | `crs`, `tensor_shape`, `geotransform`; optional `centroid` override | `centroid` | Regular affine grid; no footprint geometry is stored |
| `ispatial` | `crs`, `geometry`; optional `centroid` override | `centroid` | Irregular WKB footprint in the declared CRS |
| `temporal` | `time_start`; optional `time_end` | `time_middle` | None |
| `stac` | `crs`, `tensor_shape`, `geotransform`, `time_start`; optional `time_end` and `centroid` override | `centroid`, `time_middle` | Regular affine grid; no footprint geometry is stored |
| `istac` | `crs`, `geometry`, `time_start`; optional `time_end` and `centroid` override | `centroid`, `time_middle` | Irregular WKB footprint in the declared CRS |

For Spatial and STAC, `tensor_shape` is a non-empty list of positive integers with at least two dimensions; its final two values are height and width. `geotransform` is the six-value GDAL affine transform. Their extensions MUST calculate `centroid` from the complete affine transform and reproject it to EPSG:4326 unless the producer supplies an override. ISpatial and ISTAC MUST calculate `centroid` from `geometry` in its declared CRS unless the producer supplies an override. Temporal, STAC, and ISTAC MUST populate `time_middle` when `time_end` is present and no midpoint is supplied.

The built-in Python extensions MUST use their canonical namespaces, such as `spatial=taco.extensions.Spatial()` or `stac=taco.extensions.STAC()`. Their input values use the matching `taco.metadata.sample` model at sample scope or `taco.metadata.folder` model at folder scope. Spatial and STAC are for fixed or affine image chunks; ISpatial and ISTAC are for swaths, vectors, and other samples whose footprint cannot be recovered from a regular grid.

#### Writer-time extensions

A writer-time extension combines optional validated producer inputs with columns computed during `run()`. A requirement may refer to a producer input column or to the output of another extension at the same level. The writer MUST resolve this graph rather than use declaration order. Cycles, missing requirements, and duplicate output columns make the active writer contract invalid.

The dependency graph and operational configuration exist only while writing. They MUST NOT be stored in `COLLECTION.json`. Produced columns are ordinary dataset metadata and MUST appear in `taco:metadata` with their final types, nullability, and descriptions.

#### Rumi extension

The Rumi extension operates on one local `.rumi` asset per row. It MUST obtain `rumi:header` from `rumi.info(source=asset_path).header`; producers MUST NOT construct this binary value themselves. The header is stored as Parquet `binary` and enables stateless selective reads without first parsing the payload.

When statistics are enabled, the extension also stores `rumi:stats` as one list entry per band. Each entry is a struct containing nullable `minimum`, `maximum`, `mean`, and `stddev` doubles plus non-null `valid_count` and `nodata_count` integers. Cube statistics combine the time and spatial axes for each band. Non-finite values and the configured nodata sentinel are excluded.

#### Examples

**CloudSEN12.**

```
{
  "taco:metadata": {
    "sample": {
      "stac:crs": {"type": "string", "nullable": false, "description": "Coordinate reference system"},
      "stac:tensor_shape": {"type": "list<int64>", "nullable": false, "description": "Tensor dimensions ending in height and width"},
      "stac:geotransform": {"type": "list<double>", "nullable": false, "description": "Six-value GDAL affine transform"},
      "stac:time_start": {"type": "timestamp[us, UTC]", "nullable": false, "description": "Acquisition timestamp"},
      "stac:centroid": {"type": "binary", "nullable": false, "description": "Center point in EPSG:4326 (WKB)"},
      "stac:time_end": {"type": "timestamp[us, UTC]", "nullable": true, "description": "Acquisition end"},
      "stac:time_middle": {"type": "timestamp[us, UTC]", "nullable": true, "description": "Acquisition midpoint"},
      "quality:cloud_cover": {"type": "double", "nullable": true, "description": "Cloud cover percentage (0-100)"},
      "ml:split": {"type": "string", "nullable": false, "description": "Dataset split (train, val, test)"}
    },
    "children": {}
  }
}
```

`sample` contains one row per sample. `children` contains one row for each of its three files.

**Change detection.**

```
{
  "taco:metadata": {
    "sample": {
      "stac:crs": {"type": "string", "nullable": false, "description": "Coordinate reference system"},
      "stac:tensor_shape": {"type": "list<int64>", "nullable": false, "description": "Tensor dimensions ending in height and width"},
      "stac:geotransform": {"type": "list<double>", "nullable": false, "description": "Six-value GDAL affine transform"},
      "stac:centroid": {"type": "binary", "nullable": false, "description": "Sample center point (WKB)"},
      "stac:time_start": {"type": "timestamp[us, UTC]", "nullable": false, "description": "Sample acquisition timestamp"},
      "stac:time_end": {"type": "timestamp[us, UTC]", "nullable": true, "description": "Sample acquisition end"},
      "stac:time_middle": {"type": "timestamp[us, UTC]", "nullable": true, "description": "Sample acquisition midpoint"},
      "ml:split": {"type": "string", "nullable": false, "description": "Dataset split"},
      "change:ratio": {"type": "double", "nullable": false, "description": "Percentage of changed pixels"}
    },
    "children": {
      "acquisition:time_start": {"type": "timestamp[us, UTC]", "nullable": true, "description": "Acquisition timestamp"},
      "quality:cloud_cover": {"type": "double", "nullable": true, "description": "Cloud cover percentage"},
      "eo:sensor": {"type": "string", "nullable": true, "description": "Sensor name"}
    },
    "children/before": {},
    "children/after": {}
  }
}
```

`sample` contains one row per sample. `children` contains rows for `before`, `after`, and `change_map.tif`. Acquisition fields are null for `change_map.tif`. The two folder levels contain one row for each band file.

### 5.5. Collection

`COLLECTION.json` describes the dataset, stores its contract, and carries metadata that applies to the collection as a whole. Samples do not have string identifiers. Their position in a FOLDER or ZIP partition is their identity, starting at 0.

For this specification, `taco:version` MUST equal `3.0.0`. The `id` and `description` MUST be non-empty. The `licenses` and `providers` lists MUST each contain at least one entry. `tasks` MAY be omitted; when present it MUST contain at least one entry.

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `taco:version` | string | MUST | TACO specification version |
| `id` | string | MUST | Dataset identifier |
| `dataset_version` | string | MUST | Dataset version (SemVer, see Section 6) |
| `description` | string | MUST | Dataset description |
| `licenses` | list[string] | MUST | License identifiers (e.g. `CC-BY-4.0`) |
| `providers` | list[object] | MUST | Dataset providers with name and roles |
| `tasks` | list[string] | MAY | ML task types (e.g. `segmentation`, `classification`) |
| `taco:structure` | list or null | MUST | Sample structure |
| `taco:metadata` | object | MUST | Tabular metadata schema |
| `title` | string | MAY | Human-readable title |
| `curators` | list[object] | MAY | Dataset curators |
| `keywords` | list[string] | MAY | Keywords for discovery |
| `extent` | object | Spatial profiles | Writer-generated spatial and optional temporal summary |
| `taco:sources` | object | TACOCAT | Source ZIP partitions |

A provider MUST have a non-empty `name`. It MAY have `roles`, `url`, and `links`. A curator MUST have a `name` or `organization` and MAY have `email` and `role`.

An extent contains `spatial` and MAY contain `temporal`. `spatial` is `[west, south, east, north]` in EPSG:4326. A value where west is greater than east crosses the antimeridian. `temporal` is either null or `[start, end]` using ISO 8601 timestamps in UTC.

`extent` is a summary produced by the writer. When a metadata level declares built-in Spatial, ISpatial, STAC, or ISTAC metadata, the writer MUST calculate the extent from the rows at the shallowest level containing a spatial profile. The spatial interval covers that profile's EPSG:4326 `centroid` values. For STAC and ISTAC, the temporal interval starts at the earliest `time_start` and ends at the latest `time_end`, using `time_start` when an end is absent. The centroid interval is intentionally a compact index and does not claim to be the union of every footprint. If no row contains a spatial profile, the writer MUST omit `extent`.

Each ZIP partition MUST summarize only its own rows. TACOCAT stores each partition extent in `taco:sources` and uses their union as its collection extent. A FOLDER append MUST summarize both the existing and appended rows.

#### Collection metadata

Collection metadata is stored directly in `COLLECTION.json` as qualified fields. It uses the same `namespace:field` rule as tabular metadata but is not part of `taco:metadata` and does not create Parquet columns.

```
{
  "labels:classes": ["clear", "cloud", "shadow"],
  "labels:description": "Cloud mask classes",
  "optical:sensor": "Sentinel-2"
}
```

The Python writer groups these values in `CollectionMetadata`, but the serialized form remains flat and language-independent. Collection groups and sample groups are separate. A collection group MUST NOT be attached to a sample, folder, or asset.

Collection metadata values MUST be valid JSON. Non-finite numbers such as NaN and Infinity are not allowed.

Unknown unqualified fields are invalid. Unknown fields in a valid user namespace MAY be preserved. Unknown fields in the reserved `taco`, `internal`, or `cozip` namespaces MUST be rejected.

### 5.6. Properties

**Deterministic paths.** A sample index and a structure path identify every file. In FOLDER mode, they produce a path such as `DATA/42/before/B02.tif`. In ZIP mode, Parquet metadata provides the offset and size for a VSI path. The cost of locating that metadata depends on the Parquet reader and file layout.

**Safe partitioning.** Any subset of samples can use the same contract. Each partition assigns its own local sample indices.

**Predictable concatenation.** Partitions with the same contract and collection metadata can be combined. A physical merge MUST either re-index every row and parent reference or preserve the source partition as part of row identity.

## 6. Dataset Versioning

The `dataset_version` in `COLLECTION.json` MUST follow Semantic Versioning. Versions describe successive releases of the same dataset and therefore keep the same `id`.

### 6.1. Version Levels

**PATCH** such as `1.0.0` to `1.0.1` corrects existing content without changing the contract or adding samples. Examples include fixing metadata values, replacing corrupted files, or updating the description or keywords. Corrected STAC or ISTAC metadata may also produce a different extent.

**MINOR** such as `1.0.0` to `1.1.0` adds samples under the existing contract.

**MAJOR** such as `1.0.0` to `2.0.0` changes the contract or the meaning of existing fields. Examples include adding, removing, or renaming files, folders, or metadata fields, changing field types, changing field semantics, or reorganizing the sample hierarchy.

### 6.2. When to Create a New Dataset

A new `id` is required when the identity or purpose of the dataset changes, not merely because its contract changes. For example, turning a cloud segmentation dataset into a land-cover dataset creates a new dataset. Releasing the same cloud dataset with a different sample structure creates a new major version under the existing `id`.

### 6.3. Container Mode and Mutability

FOLDER containers support appending samples. New data is added under `DATA/`, new rows are added to `METADATA/`, and `COLLECTION.json` is updated. An append keeps the contract unchanged and produces a new minor dataset version.

ZIP containers are immutable and must be rebuilt after any change. They are suitable for stable releases. On CDC-aware platforms, rebuilding a ZIP may transfer only the chunks that changed.

Producers SHOULD build datasets as FOLDER containers and publish stable versions as ZIP containers. Conversion preserves the contract and logical content, but ZIP metadata adds the byte offsets and sizes required for random access.

## 7. Physical Layer

This section defines how a TACO dataset is stored.

### 7.1. Directory Structure

Every FOLDER or ZIP dataset MUST contain the logical paths `DATA/`, `METADATA/`, and `COLLECTION.json`. ZIP archives store these as entry prefixes and MUST NOT contain explicit directory entries.

```
dataset/
├── DATA/
│   ├── 0/
│   │   ├── before/
│   │   │   ├── B02.tif
│   │   │   ├── B03.tif
│   │   │   └── B04.tif
│   │   ├── after/
│   │   │   ├── B02.tif
│   │   │   ├── B03.tif
│   │   │   └── B04.tif
│   │   └── change_map.tif
│   ├── 1/
│   │   └── ...
│   └── ...
├── METADATA/
│   ├── sample.parquet
│   ├── children.parquet
│   ├── children__before.parquet
│   └── children__after.parquet
└── COLLECTION.json
```

`DATA/` contains the data files. When `taco:structure` is a list, each sample MUST use a directory named by its integer index and its contents MUST follow the contract. When `taco:structure` is null, the sample itself is the file and is stored directly as `DATA/<idx>`.

Every stored data file MUST contain at least one byte. This rule applies to both FOLDER and ZIP containers.

`METADATA/` contains one Parquet file for each key in `taco:metadata`. The filename replaces every `/` in the level name with `__`. Each Parquet schema MUST store its original level name as `taco:level` metadata.

`COLLECTION.json` contains the dataset description and contract defined in Section 5.5.

TACOCAT uses the separate layout defined in Section 7.5 and does not contain `DATA/` or `METADATA/` directories.

### 7.2. Internal Columns

TACO adds columns for row relationships and data access. Their names use the reserved `internal:` namespace, which users MUST NOT use.

| Column | Type | Nullable | Present in |
| --- | --- | --- | --- |
| `internal:current_id` | `uint64` | No | All Parquets |
| `internal:parent_id` | `uint64` | No | All except sample |
| `internal:relative_path` | `string` | No | All Parquets |
| `internal:offset` | `uint64` | Yes | ZIP and TACOCAT levels containing files |
| `internal:size` | `uint64` | Yes | ZIP and TACOCAT levels containing files |
| `internal:source_file` | `string` | No | TACOCAT only |

In FOLDER and ZIP datasets, `internal:current_id` MUST equal the zero-based row position in its Parquet file. Sample rows follow writer input order. Child rows are grouped by parent order and follow the structure order defined in Section 5.2.

`internal:parent_id` refers to `internal:current_id` in the parent level. A join between two levels therefore uses `child.internal:parent_id = parent.internal:current_id`.

`internal:relative_path` is relative to `DATA/`. A sample row uses `<idx>`. A child row uses `<idx>/<structure-path>`.

ZIP and TACOCAT metadata MUST include `internal:offset` and `internal:size` for data files. These values are null for folder rows. A structured `sample.parquet` does not need these columns because its rows represent sample roots rather than files. A single-file `sample.parquet` MUST contain them.

`internal:offset` is the payload offset measured from byte 0 of the source ZIP. `internal:size` is the payload length in bytes.

TACOCAT preserves the identifiers from each source partition. Within TACOCAT, row identity is the pair `(internal:source_file, internal:current_id)`, and parent joins MUST compare both columns.

Readers use these columns to build VSI paths. ZIP paths use the form `/vsisubfile/{offset}_{size},{zip_path}`. Structured FOLDER samples use `DATA/{idx}/{structure_path}`, while single-file samples use `DATA/{idx}`. Neither requires a Parquet lookup for the data path.

### 7.3. ZIP Container

A ZIP container packages one dataset or partition in a `.zip` archive. It MUST satisfy the complete TACO profile in Section 14 of the CoZIP 1.1.0 specification. Its CoZIP index declares profile 2 and contains offsets to `COLLECTION.json` and every Parquet file in `METADATA/`.

All priority files MUST form the final contiguous entry block before the Central Directory. Every archive entry MUST use STORE mode, and every filename MUST satisfy the CoZIP path rules.

The writer MUST use the `.zip` extension. Readers MUST identify TACO archives by profile 2 in the CoZIP index, not by the filename.

ZIP containers are immutable. Any update requires rebuilding the archive.

### 7.4. FOLDER Container

A FOLDER container is a plain directory with the logical layout from Section 7.1. It uses the same contract and data paths as ZIP, but its Parquet files do not contain ZIP offsets.

New samples can be appended without rebuilding existing data, making FOLDER suitable for incremental datasets.

The writer MUST publish an append as one completed update. If the operation fails, the previously published dataset MUST remain unchanged.

### 7.5. TACOCAT

TACOCAT makes several ZIP partitions queryable as one collection. It contains consolidated metadata and references the original ZIP files for data access.

```
.tacocat/
├── sample.parquet
├── children.parquet
├── children__before.parquet
├── children__after.parquet
└── COLLECTION.json
```

Each Parquet file combines the corresponding tables from the source ZIPs without changing their local row identifiers. The `internal:source_file` column MUST identify the source of every row. DuckDB can then query all metadata without opening the ZIP files.

A source path is resolved relative to the directory containing `.tacocat/`. When data is requested, the reader combines that path with `internal:offset` and `internal:size` to construct a VSI path.

TACOCAT consolidation MUST verify that every partition has the same `id`, `dataset_version`, contract, and collection metadata. The only fields that may differ are `extent` and `taco:sources`. The consolidated extent is the union of the partition extents.

`taco:sources` records each partition, its sample count, and its extent. Readers can use this information to skip irrelevant ZIP files.

Every source path MUST be unique and MUST match `internal:source_file` in the consolidated Parquet rows. `taco:sources` MUST appear in TACOCAT and MUST NOT appear in a FOLDER or ZIP dataset.

`samples` is the total number of samples and MUST equal the sum of the partition counts. Each entry in `partitions` MUST contain `file` and `samples`. It MUST also copy `spatial` and `temporal` when the source partition declares them.

```
{
  "taco:sources": {
    "samples": 300000,
    "partitions": [
      {"file": "europe.zip", "samples": 100000, "spatial": [-10, 30, 45, 70], "temporal": ["2023-01-01T00:00:00Z", "2023-12-31T23:59:59Z"]},
      {"file": "asia.zip", "samples": 100000, "spatial": [60, -10, 150, 55], "temporal": ["2023-01-01T00:00:00Z", "2023-12-31T23:59:59Z"]},
      {"file": "americas.zip", "samples": 100000, "spatial": [-170, -55, -35, 75], "temporal": ["2023-01-01T00:00:00Z", "2023-12-31T23:59:59Z"]}
    ]
  }
}
```

## 8. API Layer

TACO has one writing API and may have many reading APIs. Datasets MUST be written through the public API of the `taco` package. Alternative writer implementations are not permitted. Readers MAY use any interface as long as they interpret the format correctly.

### 8.1. taco (Writer)

`taco` is the only TACO writer. The public entry point is `taco.open_writer()` for both ZIP and FOLDER containers. A path ending in `.zip` selects ZIP. A path without a suffix, or whose final component equals the collection's Semantic Version, selects FOLDER. Other suffixes are rejected.

#### Data objects

TACO uses small immutable data objects. **Contract** defines the structure and tabular metadata schema. **Collection** describes the dataset. **Sample** contains one sample. **Folder** attaches metadata to a folder already declared by the contract. **Asset** points to one source file.

**MetadataSchema** contains one or more **Level** objects. Each level associates a namespace with a passive Pydantic model or an explicit writer-time extension.

**Metadata** carries values for a sample, folder, or asset. **CollectionMetadata** carries global dataset values. The two containers are distinct and cannot be used interchangeably.

#### Metadata schema

Built-in passive groups are organized by scope. Sample groups live under `taco.metadata.sample`, folder groups under `taco.metadata.folder`, asset groups under `taco.metadata.asset`, and collection groups under `taco.metadata.collection`. Active operations live under `taco.extensions`. Datasets may use these implementations or define additional Pydantic models and `taco.Extension` subclasses.

The writer rejects a built-in group used outside its declared scope.

```
import taco
from pydantic import BaseModel, Field


class ML(BaseModel):
    split: str = Field(description="Dataset split")


contract = taco.Contract(
    structure=["image.tif", "label.tif"],
    metadata=taco.MetadataSchema(
        taco.Level(
            "sample",
            stac=taco.extensions.STAC(),
            ml=ML,
            majortom=taco.extensions.MajorTOM(dist_km=100),
        ),
    ),
)
```

The keyword is the namespace. A Pydantic model defines passive fields, types, nullability, and descriptions. An extension additionally declares the fields it requires and produces. The writer stores them as qualified columns such as `spatial:geotransform`, `spatial:centroid`, and `majortom:code`. Built-in Spatial, ISpatial, Temporal, STAC, and ISTAC are restricted to their canonical namespaces.

A model assigned directly to a level is required on every row. `Model | None` allows the complete group to be absent on some rows and makes its stored columns nullable. Within a model, `value: T | None` makes one field nullable. `Field(description=...)` supplies its description. Exact Arrow types may use `Annotated`.

```
from datetime import datetime
from typing import Annotated

import pyarrow as pa

Float32 = Annotated[float, pa.float32()]
TimestampUTC = Annotated[datetime, pa.timestamp("us", tz="UTC")]
```

The serialized contract contains the resulting columns, not Python class names, import paths, defaults, or validators.

#### Collection metadata

Collection groups are passed through `CollectionMetadata`. They are written as qualified fields in `COLLECTION.json`.

```
collection_metadata = taco.CollectionMetadata(
    labels=taco.metadata.collection.Labels(
        classes=["clear", "cloud", "shadow"],
        description="Cloud mask classes",
    )
)
```

A collection group is validated once. It is never copied into every sample row. The writer adds `taco:version` automatically.

#### Collection summaries

Spatial and ISpatial produce the spatial part of `extent` from their centroids. STAC and ISTAC additionally produce its temporal part. Temporal has no spatial coverage and therefore does not synthesize a collection `extent`.

Summaries run independently for every output partition. They consume metadata in batches and retain only the values needed for the summary. They do not keep the complete metadata table in memory.

#### Sample metadata

Metadata is attached to the object it describes. `Sample.metadata` describes the sample, `Folder.metadata` describes a folder, and `Asset.metadata` describes a file. The writer assigns each object to the correct metadata level.

Assets are passed as a list. In a flat structure, the contract path is inferred when the source filename matches it, so the name is not repeated. The `path` argument is required for nested paths or when the source name differs from the contract.

```
sample = taco.Sample(
    metadata=taco.Metadata(
        stac=taco.metadata.sample.STAC(...),
        ml=ML(split="train"),
    ),
    assets=[
        taco.Asset(Path("/data/image.tif")),
        taco.Asset(Path("/data/label.tif")),
    ],
)
```

Folders are inferred from the contract and need no runtime object unless they carry metadata. When they do, the sample names them once.

```
sample = taco.Sample(
    folders=[taco.Folder("before", metadata=...)],
    assets=[...],
)
```

#### Writer-time extensions

An extension declares the columns it needs and produces. It may also declare a Pydantic input model when the producer supplies part of its metadata. Spatial receives affine-grid values and produces `spatial:centroid`; `MajorTOM(centroid="spatial:centroid")` can require that output and produce `majortom:code`. The contract is invalid when a required column is missing.

The writer computes extension outputs from batches of validated metadata during `run()`. Each context also contains the local asset associated with every row, allowing format extensions to inspect payloads without asking producers to duplicate file metadata.

`taco.extensions.Rumi(stats=True)` requires a local `.rumi` asset and produces the canonical binary `rumi:header` plus named per-band `rumi:stats`. `taco.extensions.GeoEnrich` derives selected Earth Engine variables from its configurable centroid field.

Extension dependencies and operational settings remain in the active Python contract while writing. The persisted contract contains only the resulting structure and metadata schema.

#### Writer lifecycle

`add()` and `extend()` validate and stage samples. They do not modify the final dataset.

`run()` closes the input, computes derived metadata and ZIP offsets, writes each Parquet file once, and publishes the result. If a build fails, an existing dataset MUST remain unchanged.

Leaving the context manager only removes temporary files. It does not call `run()`. Calling `run()` again after success has no effect.

FOLDER containers may use `append=True`. ZIP containers may be partitioned. The writer builds every partition and the TACOCAT before publishing them together. If publication fails, it restores the previous files.

#### Export

`taco.export()` writes selected samples of an existing dataset through the same writer. `samples` is a PyArrow-compatible table, normally selected from the `data` SQL relation. It MUST retain `sample_id`; for a TACOCAT it MUST also retain `source_file`. Every named sample MUST exist in the source or the export fails.

The output keeps the contract, identity, licenses, providers, tasks, and collection metadata of its source unless collection fields are explicitly replaced. Its samples are numbered from 0 in source order, `extent` is recalculated from the selected rows, and `taco:sources` is removed. Without `samples` every sample is copied, which converts a FOLDER to ZIP or merges a TACOCAT into one dataset. `overwrite=True` replaces an existing TACO output.

```
source = "https://data.source.coop/major-tom/core-dem/"
dataset = taco.open_dataset(source)
samples = dataset.sql("SELECT * FROM data ORDER BY sample_id LIMIT 10")
taco.export(
    source,
    "core-dem-sample.zip",
    samples=samples,
    id="core-dem-sample",
    description="Ten samples from Core-DEM",
)
```

#### Example

```
from datetime import datetime, timezone
from pathlib import Path

import taco
from pydantic import BaseModel, Field


class ML(BaseModel):
    split: str = Field(description="Dataset split")


contract = taco.Contract(
    structure=["image.tif", "label.tif"],
    metadata=taco.MetadataSchema(
        taco.Level(
            "sample",
            stac=taco.extensions.STAC(),
            ml=ML,
            majortom=taco.extensions.MajorTOM(dist_km=100),
        ),
    ),
)

collection = taco.Collection(
    contract=contract,
    id="cloud-segmentation",
    dataset_version="1.0.0",
    description="Cloud segmentation dataset",
    licenses=["CC-BY-4.0"],
    providers=[{"name": "CSIC", "roles": ["producer"]}],
    tasks=["segmentation"],
    metadata=taco.CollectionMetadata(
        labels=taco.metadata.collection.Labels(
            classes=["clear", "cloud"],
            description="Cloud mask classes",
        )
    ),
)

sample = taco.Sample(
    metadata=taco.Metadata(
        stac=taco.metadata.sample.STAC(
            crs="EPSG:4326",
            tensor_shape=(13, 256, 256),
            geotransform=(-76.55, 0.1 / 256, 0, -9.15, 0, -0.1 / 256),
            time_start=datetime(2025, 1, 1, tzinfo=timezone.utc),
        ),
        ml=ML(split="train"),
    ),
    assets=[taco.Asset(Path("/data/image.tif")), taco.Asset(Path("/data/label.tif"))],
)

with taco.open_writer(collection, "clouds.zip") as writer:
    writer.add(sample)
    writer.run()
```

### 8.2. Reader

The reference reader is the TACO core, a C++ library with a C interface. The Python, R, and Julia packages load the same library, so a read returns the same rows in every language.

The core detects ZIP, FOLDER, or TACOCAT from the path and reads `COLLECTION.json` and the metadata Parquet through Karu. It generates the SQL for the requested view, and each package runs that SQL with its own DuckDB client.

For a ZIP, the core reads the byte-0 index and fetches `COLLECTION.json` and every indexed Parquet range in one batch. For a remote FOLDER or TACOCAT, it fetches the Parquet files named by `taco:metadata`, because object stores cannot list directories reliably. This metadata is written to a local cache with one entry per concrete dataset, named `<id>-<version>-<container>-<origin>-<hash>` and laid out like a TACO FOLDER without `DATA/`. An entry is trusted once written, because an individual TACO version is immutable, so a cached concrete dataset opens without any request; `TACO_CACHE_REFRESH` rebuilds it, and a local archive is checked against its size and modification time. A versioned root is mutable: each new root resolution reads `taco.json` so newly published versions and changes to `taco:default_version` are visible. An already open `Dataset` remains a snapshot of the version it resolved. Missing or inaccessible root manifests are not cached. The cache keeps at most `TACO_CACHE_SIZE` bytes, 10 GiB by default, dropping the least recently opened entries. A local FOLDER or TACOCAT is read in place. The cache lives in the user cache directory, and `TACO_CACHE_DIR` overrides it.

The native reader reports remote download progress in interactive terminals and stays silent otherwise. Python exports also report sample-copy progress. Python writers report their build phases when `progress=True`.

#### Python read(source, files)

`read` materializes every sample as a wide PyArrow table. It accepts only the
source and an optional file selection. Row filtering and raw metadata access
belong to `Dataset.sql()`.

**source** is required. It accepts a local path or a remote location supported by Karu, including HTTP, S3, Google Cloud Storage, Azure, Hugging Face, and Source Cooperative. `taco.read(source, files=...)` is the convenience wrapper for `taco.open_dataset(source).read(files=...)`.

```
taco.read("/data/cloudsen12.zip")
taco.read("https://example.com/cloudsen12.zip")
taco.read("s3://bucket/cloudsen12.zip")
taco.read("hf://datasets/tacofoundation/cloudsen12/cloudsen12.zip")
taco.read("source://taco/cloudsen12/cloudsen12.zip")
```

Remote file locations use the VSI prefix of their storage, such as `/vsicurl/`, `/vsis3/`, `/vsigs/`, `/vsiaz/`, `/vsihf/`, or `/vsisource/`.

**files** limits which structure declarations appear in the result. A fixed file is selected by its full contract path. A variable sequence is selected by its declaration, such as `img*[4,16].tif`. By default every declared file is returned.

The result includes `sample_id`. TACOCAT also includes `source_file`, and the pair identifies a sample. Every selected file has a `{file}::location` column with its reader-calculated location; neither `taco:location` nor `cozip:location` is stored in metadata. A Rumi asset cannot be read from its location alone, so when the metadata level of a file declares `rumi:header`, the result also has a `{file}::header` column with that header. Both columns are computed when the dataset is read and never change it.

Collection metadata is not repeated in every result row. It is available through `Dataset.collection`.

```
taco.read("cloudsen12.zip")
# sample_id | ml:split | quality:cloud_cover | s2_l1c.tif::location | s2_l2a.tif::location | target.tif::location
# 0         | train    | 23.5                | /vsisubfile/...     | /vsisubfile/...     | /vsisubfile/...

# Two selected files
taco.read("change_detection.zip", files=["before/B02.tif", "after/B02.tif"])
# sample_id | ml:split | before__B02.tif::location | after__B02.tif::location

# Rumi assets carry their header
taco.read("multisensor.zip")
# sample_id | optical.rumi::location | optical.rumi::header | radar.rumi::location | radar.rumi::header
# 0         | /vsisubfile/...       | b"LOVE..."          | /vsisubfile/...     | b"LOVE..."
```

A `/` in a structure path becomes `__` in its wide column name, followed by `::location` or `::header`. This mapping is reversible because `__` and `:` are forbidden inside path components. The double `::` also distinguishes generated columns from metadata fields, which contain exactly one `:`. A variable sequence uses the path to its prefix: `before/img*[0,16].tif` becomes the `LIST(VARCHAR)` column `before__img::location`, and a Rumi sequence also has the `LIST(BLOB)` column `before__img::header` in the same order.

```
taco.read("multitemporal_s2.zip")
# sample_id | ml:split | img::location
# 0         | train    | [/vsisubfile/..., /vsisubfile/..., ...]
# 1         | val      | [/vsisubfile/..., /vsisubfile/..., ...]
```

The list is ordered by the numeric sequence index. A sequence with no files returns an empty list.

When `taco:structure` is null, `read()` contains one reader-calculated `taco:location` column for the sample file. A `rumi:header` declared at the sample level is already part of the same row. The `files` relation also contains a nullable `path`, whose value is `NULL` because the sample file has no structural path.

Python `read()` orders rows by `sample_id`, preceded by `source_file` when present. SQL results have no implicit order unless the query contains `ORDER BY`.

#### Python Dataset.sql(query)

`Dataset.sql()` accepts one SQL query and returns a PyArrow table. It exposes these relations:

- `data`: one row per sample with sample metadata, but no structural file columns.
- `files`: one row per file with `sample_id`, `path`, reader-calculated `taco:location`, and effective metadata. When a field is declared at more than one level, the nearest declaration wins.
- one raw relation per metadata level. `/` becomes `__`, so the levels `sample`, `children`, and `children/before` are named `sample`, `children`, and `children__before`.

Raw level relations keep their internal identity columns. Repeated field names remain unambiguous because SQL aliases identify the relation:

```sql
SELECT s."quality:score", c."quality:score"
FROM sample AS s
JOIN children AS c
  ON c."internal:parent_id" = s."internal:current_id"
```

Partial reads use SQL:

```python
dataset = taco.open_dataset("cloudsen12.zip")
rows = dataset.sql("SELECT * FROM data WHERE sample_id < 100")
assets = dataset.sql("SELECT * FROM files WHERE path = 'target.tif'")
```

`Dataset.read()` and `Dataset.sql()` execute through the same DuckDB context. `read()` is the convenience operation that returns the complete wide view.

#### R and Julia read

R and Julia expose the native reader controls directly while their dataset-level SQL APIs are developed:

```
# R
read(source, layout = "wide", idx = NULL, level = NULL,
     files = NULL, location = TRUE)

# Julia
Taco.read(source; layout="wide", idx=nothing, level=nothing,
          files=nothing, location=true)
```

`layout` selects the wide or long native view. `idx` selects one sample or a half-open range independently in every source. `level` returns one raw metadata level. `files` selects contract leaves, and `location` controls calculated locations. These controls are also available when `source` is an open R or Julia dataset.

#### Inspection

`taco.reader.inspect` reads the contract without reading samples. `contract` returns the structure and levels as `kind` and `value` rows. `structure`, `levels`, `collection`, and `profile` return them directly. `native_sql` exposes the low-level SQL generated by the shared core for debugging; it is not the Python `Dataset.sql()` API.

### 8.3. Dataset API

`open_dataset()` returns a `Dataset` that holds the sources, collection, and shared contract. In Python, `Dataset.read()` materializes the complete wide view and `Dataset.sql()` provides partial access.

```
import taco

dataset = taco.open_dataset("cloudsen12.zip")

dataset.collection
dataset.contract
dataset.read()
dataset.read(files=["s2_l1c.tif", "target.tif"])
dataset.sql("SELECT * FROM data WHERE sample_id = 10")
```

The same API accepts every TACO container and a list of compatible partitions.

```
parts = taco.open_dataset(["cloudsen12_0.zip", "cloudsen12_1.zip"])
folder = taco.open_dataset("cloudsen12/")
catalog = taco.open_dataset("cloudsen12/.tacocat")
```

A source list is checked with one query. The reader verifies that every source belongs to the same collection, then streams the tables through `UNION ALL BY NAME`. It does not materialize one table per source. Partition extents may differ and are merged by `Dataset`. A TACOCAT is already consolidated and must be opened as one path.

Rows from a source list include `source_file`. As with TACOCAT, the pair `(source_file, sample_id)` identifies a sample. SQL selections that use `sample_id` alone therefore apply independently to every source.


<figure class="dataset-figure">
<div class="dataset-map">
<div class="dm-head">
<div>
<div><span class="dm-class">taco.Dataset</span><span class="dm-title">CloudSEN12</span></div>
<div class="dm-description">Sentinel-2 image patches and cloud masks</div>
<div class="dm-facts"><span class="dm-fact">ZIP</span><span class="dm-fact">3 leaves</span><span class="dm-fact">2 levels</span><span class="dm-fact">8 fields</span></div>
</div>
<svg aria-label="TACO ZIP storage" class="dm-store" role="img" viewbox="0 0 160 125">
<defs><lineargradient id="spec-cylinder" x1="0" x2="1"><stop offset="0" stop-color="#FAEEDA"></stop><stop offset=".55" stop-color="#FAC775"></stop><stop offset="1" stop-color="#EF9F27"></stop></lineargradient></defs>
<path d="M25 28v66c0 11 25 20 55 20s55-9 55-20V28" fill="url(#spec-cylinder)" stroke="#854F0B" stroke-width="1.4"></path>
<ellipse cx="80" cy="28" fill="#FAEEDA" rx="55" ry="19" stroke="#854F0B" stroke-width="1.4"></ellipse>
<path d="M25 61c0 11 25 20 55 20s55-9 55-20M25 85c0 11 25 20 55 20s55-9 55-20" fill="none" opacity=".45" stroke="#854F0B" stroke-width=".7"></path>
<text fill="#633806" font-size="12" font-weight="700" text-anchor="middle" x="80" y="67">ZIP</text>
</svg>
</div>
<div class="dm-section">
<div class="dm-summary"><span class="dm-arrow">v</span><span class="dm-name">Structure</span><span class="dm-count">3 leaves</span></div>
<div class="dm-content dm-graph">
<svg aria-label="Sample structure" height="170" role="img" viewbox="0 0 360 170" width="360">
<path class="dm-edge" d="M 180 56 V 85 H 52 V 114"></path><path class="dm-edge" d="M 180 56 V 85 H 180 V 114"></path><path class="dm-edge" d="M 180 56 V 85 H 308 V 114"></path>
<g class="dm-node dm-root"><rect height="40" rx="7" width="84" x="138" y="16"></rect><text class="dm-label" text-anchor="middle" x="180" y="33">sample</text><text class="dm-kind" text-anchor="middle" x="180" y="47">root</text></g>
<g class="dm-node dm-file"><rect height="40" rx="7" width="88" x="8" y="114"></rect><text class="dm-label" text-anchor="middle" x="52" y="131">s2_l1c.tif</text><text class="dm-kind" text-anchor="middle" x="52" y="145">file</text></g>
<g class="dm-node dm-file"><rect height="40" rx="7" width="88" x="136" y="114"></rect><text class="dm-label" text-anchor="middle" x="180" y="131">s2_l2a.tif</text><text class="dm-kind" text-anchor="middle" x="180" y="145">file</text></g>
<g class="dm-node dm-file"><rect height="40" rx="7" width="88" x="264" y="114"></rect><text class="dm-label" text-anchor="middle" x="308" y="131">target.tif</text><text class="dm-kind" text-anchor="middle" x="308" y="145">file</text></g>
</svg>
</div>
</div>
<div class="dm-section dm-folded"><div class="dm-summary"><span class="dm-arrow">&gt;</span><span class="dm-name">Metadata</span><span class="dm-count">8 fields</span></div></div>
<div class="dm-section dm-folded"><div class="dm-summary"><span class="dm-arrow">&gt;</span><span class="dm-name">Collection</span><span class="dm-count">cloudsen12</span></div></div>
<div class="dm-section dm-folded"><div class="dm-summary"><span class="dm-arrow">&gt;</span><span class="dm-name">Sources</span><span class="dm-count">1 source</span></div></div>
</div>
<figcaption><b>Figure 4.</b> Notebook representation of a Dataset. The contract is visible without reading the sample table.</figcaption>
</figure>


The default `wide` layout returns one row per sample with sample metadata and one path column per declared file. The `long` layout returns one row per file and includes metadata inherited from its sample and folders. Collection metadata remains on `dataset.collection` and is never repeated in result rows.

`Dataset` is not a dataframe. It owns dataset semantics and leaves tabular operations to Arrow, DuckDB, Pandas, or Polars. Calling `read()` returns `pyarrow.Table`. `taco.reader.inspect` remains available for direct access to the contract and low-level native SQL.

Notebook environments use the Dataset HTML representation to show the collection identity, structure, and metadata levels without materializing the sample table.

## Annex A: Migration from v2

TACO v3 is not compatible with v2 datasets. Existing datasets MUST be rebuilt to work with v3 tools. This annex summarizes the differences.

### A.1. Summary of Changes

| Aspect | v2 | v3 |
| --- | --- | --- |
| Contract definition | Inferred from first sample at runtime (PIT) | Declared explicitly before any data is written |
| Core abstractions | SAMPLE, TORTILLA, TACO | Contract, Collection, Sample, Folder, Asset |
| Sample identity | String IDs (`id` field) | Local integer indices; source plus index in TACOCAT |
| Sample types | FILE or FOLDER discriminator | No type field. The contract defines the structure. |
| Irregular structures | Padding with `__TACOPAD__` placeholders | Variable sequences (`prefix*[a,b].ext`) |
| Metadata storage | Dual system (consolidated `levelX.parquet` + local `__meta__` per folder) | Consolidated only (one Parquet per contract level, no local metadata) |
| Parquet naming | By depth (`level0.parquet`, `level1.parquet`, ...) | By row level (`sample.parquet`, `children.parquet`, `children__before.parquet`, ...) |
| Extension system | Formal `extend_with()` interface with SampleExtension, TortillaExtension, TacoExtension classes | Scoped Pydantic groups for sample, folder, asset, and collection metadata |
| Structural constraint | Position-Invariant Tree inferred at runtime | Structure and metadata declared in a contract |
| Library dependency | GDAL required | VSI path convention. GDAL is one implementation. |
| Reader implementation | TacoReader (Python classes with lazy query, DuckDB internally) | One C++ core that generates the reader SQL, thin wrappers in Python/R/Julia that run it with DuckDB |
| Writer implementation | TacoToolbox (Sample, Tortilla, Taco classes) | `taco.open_writer()` |
| ZIP extension | `.tacozip` | `.zip`, with the CoZIP profile byte as the only type signal |
| TACOCAT format | Binary file with 128-byte header, fixed 7-entry index table | Directory with merged Parquets and COLLECTION.json |
| TACOLLECTION | Separate `TACOLLECTION.json` file | Merged into TACOCAT COLLECTION.json via `taco:sources` field |
| Dataset versioning | `dataset_version` field, no formal scheme | SemVer with defined semantics (PATCH/MINOR/MAJOR, see Section 6) |
| Spec versioning | SemVer (`2.0.0`) | SemVer (`3.0.0`) |
| Hierarchical navigation | `read()` method traversing `__meta__` files | `read()` with the `level` parameter |
| Filtering | `filter_bbox()`, `filter_datetime()` with cascading JOINs | SQL `WHERE` clauses on Parquet columns |
| Concatenation | `concat()` with column modes | SQL `UNION` or TACOCAT consolidation |

### A.2. Contract vs PIT

The main change in v3 is that the dataset structure is explicit.

In v2, the writer inferred the structure from the first sample. PIT then required later samples to have the same children, in the same positions, with the same types. Missing positions were filled with `__TACOPAD__` placeholders.

In v3, the contract declares the file layout and metadata schema before writing begins. Every sample is checked against it. Nothing is inferred and no padding is needed.

The contract also determines the Parquet files in advance. Their names describe the rows they contain, such as `children__before.parquet`, instead of using a depth such as `level1.parquet`. Variable sequences replace padding when the number of files differs between samples.

### A.3. Metadata System

v2 stored metadata twice. Consolidated `levelX.parquet` files supported queries across the dataset, while local `__meta__` files supported navigation inside each folder.

v3 stores sample, folder, and asset metadata in the Parquet files under `METADATA/`. Collection metadata is stored once in `COLLECTION.json`. Relationships between tabular levels use `internal:parent_id` and SQL joins. Local `__meta__` files are no longer needed because the contract already describes every level.

### A.4. Reader Architecture

v2 used a Python reader with separate backends for ZIP, FOLDER, and TACOCAT. DuckDB was hidden behind TACO-specific dataset and dataframe classes.

v3 moves reading into one C++ core shared by the Python, R, and Julia packages. The core detects the container, reads the metadata through Karu, builds the file locations, and generates the SQL that each package runs with its own DuckDB client.

### A.5. Extension System

v2 extensions combined schema definitions with metadata computation through base classes and `extend_with()`.

v3 uses namespaced Pydantic models for passive metadata and a generic `Extension` abstraction for writer-time operations. The namespace determines the stored field prefix. Extensions combine optional validated inputs, declared outputs, local asset access, and explicit dependencies.

`taco` includes STAC and ISTAC extensions that restore the automatic centroid behavior of v2, a Rumi extension for canonical headers and per-band statistics, and composable operations such as MajorTOM. The writer resolves their dependency graph during `run()`. Datasets can define additional models or extension subclasses without modifying the writer core.

### A.6. TACOCAT and TACOLLECTION

v2 stored TACOCAT in a binary file with a fixed header. It used a separate TACOLLECTION JSON document for dataset metadata.

v3 stores TACOCAT as a `.tacocat/` directory containing merged Parquet files and one `COLLECTION.json`. The `taco:sources` field replaces TACOLLECTION.

### A.7. Migration Path

There is no automatic migration tool. The two versions differ in structure discovery, sample identity, metadata layout, and Parquet naming.

To migrate, producers MUST define a v3 contract and rebuild the dataset with `taco`. The GeoTIFF, NetCDF, and other data files can remain unchanged. Only their packaging and metadata must be rewritten.

## Annex B: History

TACO began in Valencia, Spain, at the Image and Signal Processing group of the Universitat de València. Early discussions brought together Julio Contreras, Oscar Pellicer, Simon Donike, Chen Ma from HIT, David Montero from the University of Leipzig, and Cesar Aybar.

During that period, after spending more than a month harmonizing cloud detection datasets, we sketched a general solution. We wanted something simple for our own work and the datasets produced at ISP. That idea became TACO v1, which combined a custom binary layout with Parquet metadata and built its tooling around GDAL and dataframes.

The first format had many flaws, but its central idea held up. Conversations at ESA Living Planet 2025 shaped TACO v2. Jérémy Anger from Kayrros and Université Paris-Saclay suggested replacing the custom binary format with ZIP. Discussions with Mikolaj Czerkawski at Asterisk about MajorTOM influenced the lazy loading design. Nils Lehmann and Adam Stewart from the University of Munich and TorchGeo brought years of experience with machine learning datasets to the API design.

OceanTACO, built with Nils Lehmann at TUM, tested v2 on ocean remote sensing data and exposed limitations that later shaped the v3 contract. Nate Mankovich at ISP helped define the Position-Invariant Tree that underpinned v2. Luis Gómez-Chova and Gustau Camps-Valls at ISP have helped question and refine TACO from the beginning.

TACO v2 worked. We published datasets, people used them, and the tools held up for small and medium collections. Asterisk Labs then used TACO to build datasets at production scale. Each dataset revealed another limit of v2.

TACO v3 is smaller than v2. The contract replaces PIT, the extension hierarchy, and padding. One reader core replaces three Python reader backends. Local `__meta__` files and the binary TACOCAT header are gone.

The goal is unchanged: keep data and metadata together so researchers can query, filter, and load a dataset without handling its packaging.


<div class="logos">
<img alt="ISP Logo" src="assets/isp_logo.png"/>
<img alt="University of Leipzig Logo" src="assets/leipzig_logo.png"/>
<img alt="TUM Logo" src="assets/tum_logo.png"/>
<img alt="Asterisk Labs Logo" src="assets/asterisk_logo.svg"/>
</div>
