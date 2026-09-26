// DuckDB-WASM runs the SQL filter. Like the map and proj4 it comes from
// jsdelivr, and only when the first query runs, so opening a dataset never
// waits for it.
const DUCKDB_URL = "https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@1.32.0/+esm";
const SAMPLE_INDEX = "taco:sample_index";
const CURRENT_ID = "internal:current_id";
const SOURCE_FILE = "internal:source_file";
// Reader-owned columns the dataset view hides, as the Python reader does.
const HIDDEN = new Set(["id", "taco:location", "cozip:location"]);

let engine = null;
let registered = null;

/**
 * Return the physical rows of sample.parquet that a query selects. The query
 * reads `dataset`, one row per sample like Dataset.sql in Python without the
 * file columns, or the raw `sample` level.
 *
 * @param {ArrayBuffer} parquet The cached sample.parquet bytes.
 * @param {string} query
 * @param {(label: string) => void} [onStatus]
 * @returns {Promise<number[]>} Sorted physical row indexes.
 */
export async function selectSampleRows(parquet, query, onStatus = () => {}) {
  // A stale cached reader returns nothing from cacheLevel.
  if (!(parquet instanceof ArrayBuffer)) throw new Error("Reload the page to update the TACO reader.");
  const statement = normalizeQuery(query);
  if (!engine) onStatus("Loading DuckDB");
  const { db, connection } = await open();
  if (registered?.parquet !== parquet) await register(db, connection, parquet);
  onStatus("Running");
  const selection = `SELECT * FROM (\n${statement}\n) AS taco_query`;
  const columns = (await connection.query(`${selection} LIMIT 0`)).schema.fields.map((field) => field.name);
  const key = identityColumn(columns);
  const rows = await connection.query(
    `SELECT file_row_number FROM taco_rows WHERE ${quote(CURRENT_ID)} IN ` +
      `(SELECT ${quote(key)} FROM (${selection}) AS taco_selected) ORDER BY file_row_number`,
  );
  return Array.from(rows.getChild("file_row_number").toArray(), Number);
}

/** @param {unknown} query @returns {string} */
export function normalizeQuery(query) {
  let statement = String(query ?? "").trim();
  while (statement.endsWith(";")) statement = statement.slice(0, -1).trimEnd();
  if (!statement) throw new Error("Write a query, such as SELECT * FROM dataset.");
  return statement;
}

/** @param {string[]} columns @returns {string} */
export function identityColumn(columns) {
  if (columns.includes(SAMPLE_INDEX)) return SAMPLE_INDEX;
  if (columns.includes(CURRENT_ID)) return CURRENT_ID;
  throw new Error(`The query must return ${SAMPLE_INDEX}; use SELECT * or include it.`);
}

/**
 * The dataset view over the columns of sample.parquet.
 *
 * @param {string[]} names
 * @returns {string}
 */
export function datasetView(names) {
  const columns = [];
  if (names.includes(SOURCE_FILE)) columns.push(`${quote(SOURCE_FILE)} AS source_file`);
  columns.push(`${quote(CURRENT_ID)} AS ${quote(SAMPLE_INDEX)}`);
  if (names.includes("id")) columns.push(quote("id"));
  columns.push(...names.filter((name) => !name.startsWith("internal:") && !HIDDEN.has(name)).map(quote));
  return `SELECT ${columns.join(", ")} FROM "sample"`;
}

function open() {
  engine ??= start().catch((error) => {
    engine = null;
    throw error;
  });
  return engine;
}

async function start() {
  const duckdb = await import(DUCKDB_URL);
  const bundle = await duckdb.selectBundle(duckdb.getJsDelivrBundles());
  // A worker cannot start from a cross-origin script, so a local one imports it.
  const workerUrl = URL.createObjectURL(new Blob([`importScripts("${bundle.mainWorker}");`], { type: "text/javascript" }));
  try {
    const db = new duckdb.AsyncDuckDB(new duckdb.VoidLogger(), new Worker(workerUrl));
    await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
    return { db, connection: await db.connect() };
  } finally {
    URL.revokeObjectURL(workerUrl);
  }
}

async function register(db, connection, parquet) {
  const file = `sample-${Date.now()}.parquet`;
  // The worker takes ownership of the bytes it receives, so it gets a copy of the reader's cache.
  await db.registerFileBuffer(file, new Uint8Array(parquet.slice(0)));
  await connection.query(
    `CREATE OR REPLACE VIEW taco_rows AS SELECT * FROM read_parquet(${literal(file)}, file_row_number = true)`,
  );
  await connection.query('CREATE OR REPLACE VIEW "sample" AS SELECT * EXCLUDE (file_row_number) FROM taco_rows');
  const names = (await connection.query('SELECT * FROM "sample" LIMIT 0')).schema.fields.map((field) => field.name);
  await connection.query(`CREATE OR REPLACE VIEW dataset AS ${datasetView(names)}`);
  if (registered) await db.dropFile(registered.file);
  registered = { parquet, file };
}

/** @param {string} name */
function quote(name) {
  return `"${name.replaceAll('"', '""')}"`;
}

/** @param {string} value */
function literal(value) {
  return `'${value.replaceAll("'", "''")}'`;
}
