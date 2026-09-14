import { parquetMetadataAsync, parquetQuery, parquetScan, parquetSchema } from "hyparquet";
import { compressors } from "hyparquet-compressors";
import { fail } from "../errors.js";
import { filterColumns } from "../reader/filter.js";

export const PROTECTED_LOCATION_COLUMNS = new Set(["cozip:location", "taco:location"]);

export class TacoParquet {
  /**
   * @param {{ byteLength: number, slice(start: number, end?: number): Promise<ArrayBuffer>, readAll?(onProgress?: (progress: {loaded: number, total: number}) => void): Promise<ArrayBuffer> }} file
   * @param {string} level
   */
  constructor(file, level) {
    this.file = file;
    this.level = level;
    this.metadataPromise = this.readMetadata();
    this.cachePromise = null;
  }

  /** @param {(progress: {loaded: number, total: number}) => void} [onProgress] */
  async cache(onProgress) {
    if (!this.cachePromise) {
      const download = this.file.readAll
        ? this.file.readAll(onProgress)
        : this.file.slice(0, this.file.byteLength);
      this.cachePromise = download.then((buffer) => {
        /** @type {{byteLength: number, slice(start: number, end?: number): Promise<ArrayBuffer>}} */
        const cachedFile = {
          byteLength: buffer.byteLength,
          slice: async (start, end = buffer.byteLength) => buffer.slice(start, end),
        };
        this.file = cachedFile;
      });
    }
    await this.cachePromise;
    onProgress?.({ loaded: this.file.byteLength, total: this.file.byteLength });
  }

  /** Return the number of rows without decoding the Parquet body. */
  async rowCount() {
    const rows = (await this.metadataPromise).num_rows;
    if (rows < 0n || rows > BigInt(Number.MAX_SAFE_INTEGER)) {
      fail("UNSAFE_INTEGER", `${this.level} row count exceeds JavaScript's safe integer range`);
    }
    return Number(rows);
  }

  async readMetadata() {
    const metadata = await parquetMetadataAsync(this.file);
    const storedLevel = metadata.key_value_metadata?.find((item) => item.key === "taco:level")?.value;
    if (storedLevel !== this.level) {
      fail(
        "INVALID_PARQUET_LEVEL",
        `${this.level} metadata stores taco:level=${JSON.stringify(storedLevel)}`,
      );
    }
    return metadata;
  }

  /**
   * @param {{
   *   columns?: string[],
   *   filter?: Record<string, any>,
   *   rowStart?: number,
   *   rowEnd?: number,
   *   rowIndexes?: number[],
   * }} [options]
   */
  async read(options = {}) {
    validateRows(options.rowStart, options.rowEnd);
    validateRowIndexes(options.rowIndexes, options);
    if (
      options.columns !== undefined &&
      (!Array.isArray(options.columns) ||
        options.columns.some((name) => typeof name !== "string" || name.length === 0))
    ) {
      throw new TypeError("taco: columns must be an array of non-empty strings");
    }
    const protectedFilter = filterColumns(options.filter).filter((name) =>
      PROTECTED_LOCATION_COLUMNS.has(name),
    );
    if (protectedFilter.length) {
      fail(
        "PROTECTED_COLUMN",
        `stored reader-owned columns cannot be filtered: ${protectedFilter.join(", ")}`,
      );
    }

    const requested = options.columns ? [...new Set(options.columns)] : undefined;
    let columns = requested?.filter((name) => !PROTECTED_LOCATION_COLUMNS.has(name));
    let sentinel = false;
    if (columns && columns.length === 0) {
      columns = ["internal:current_id"];
      sentinel = true;
    }
    const metadata = await this.metadataPromise;
    /** @type {Record<string, any>[]} */
    const rows = options.rowIndexes
      ? await readRowIndexes(this.file, metadata, columns, options.rowIndexes)
      : await parquetQuery({
          file: this.file,
          metadata,
          compressors,
          columns,
          filter: options.filter,
          rowStart: options.rowStart,
          rowEnd: options.rowEnd,
          useOffsetIndex: true,
          utf8: false,
        });
    for (const row of rows) {
      for (const name of PROTECTED_LOCATION_COLUMNS) delete row[name];
      if (sentinel) delete row["internal:current_id"];
    }
    return rows;
  }
}

/**
 * @param {{byteLength: number, slice(start: number, end?: number): Promise<ArrayBuffer>}} file
 * @param {import("hyparquet").FileMetaData} metadata
 * @param {string[] | undefined} columns
 * @param {number[]} rowIndexes
 */
async function readRowIndexes(file, metadata, columns, rowIndexes) {
  const totalRows = Number(metadata.num_rows);
  if (rowIndexes.some((index) => index >= totalRows)) {
    throw new RangeError(`taco: rowIndexes must be smaller than ${totalRows}`);
  }
  const selectedColumns = columns ?? parquetSchema(metadata).children.map((child) => child.element.name);
  const requests = rowIndexes
    .map((row, output) => ({ row, output }))
    .sort((left, right) => left.row - right.row);
  /** @type {Record<string, any>[]} */
  const rows = Array.from({ length: rowIndexes.length }, () => ({}));
  const scan = await parquetScan({
    file,
    metadata,
    compressors,
    columns: selectedColumns,
    utf8: false,
  });

  for (const range of scan.ranges) {
    const first = lowerBound(requests, range.rowStart);
    const last = lowerBound(requests, range.rowEnd);
    if (first === last) continue;
    const selected = requests.slice(first, last);
    for (const column of selectedColumns) {
      const values = await scan.readColumn({
        column,
        rowStart: range.rowStart,
        rowEnd: range.rowEnd,
      });
      for (const request of selected) {
        rows[request.output][column] = values[request.row - range.rowStart];
      }
    }
  }
  return rows;
}

/** @param {{row: number}[]} rows @param {number} target */
function lowerBound(rows, target) {
  let low = 0;
  let high = rows.length;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (rows[middle].row < target) low = middle + 1;
    else high = middle;
  }
  return low;
}

/** @param {number[] | undefined} rowIndexes @param {Record<string, any>} options */
function validateRowIndexes(rowIndexes, options) {
  if (rowIndexes === undefined) return;
  if (!Array.isArray(rowIndexes) || rowIndexes.some((index) => !Number.isSafeInteger(index) || index < 0)) {
    throw new RangeError("taco: rowIndexes must be an array of non-negative integers");
  }
  if (options.rowStart !== undefined || options.rowEnd !== undefined || options.filter !== undefined) {
    throw new TypeError("taco: rowIndexes cannot be combined with rowStart, rowEnd, or filter");
  }
}

/** @param {number | undefined} start @param {number | undefined} end */
function validateRows(start, end) {
  if (start !== undefined && (!Number.isSafeInteger(start) || start < 0)) {
    throw new RangeError("taco: rowStart must be a non-negative integer");
  }
  if (end !== undefined && (!Number.isSafeInteger(end) || end < 0)) {
    throw new RangeError("taco: rowEnd must be a non-negative integer");
  }
  if (start !== undefined && end !== undefined && start > end) {
    throw new RangeError("taco: rowStart must not exceed rowEnd");
  }
}
