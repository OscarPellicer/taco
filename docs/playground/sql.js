const DUCKDB_URL = "https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@1.32.0/+esm";
export const DEFAULT_QUERY = "SELECT * FROM dataset";
const SAMPLE_INDEX = "taco:sample_index";
const CURRENT_ID = "internal:current_id";
const SOURCE_FILE = "internal:source_file";
const HIDDEN = new Set(["id", "taco:location", "cozip:location"]);

let engine = null;
let engineReady = false;
let registered = null;
let sqlQueue = Promise.resolve();

export async function prepareSql(parquet) {
  const opened = await open();
  engineReady = true;
  if (!(parquet instanceof ArrayBuffer)) return;
  return enqueue(async () => {
    if (registered?.parquet !== parquet) await register(opened.db, opened.connection, parquet);
  });
}

/**
 * @param {ArrayBuffer} parquet
 * @param {string} query
 * @param {(label: string) => void} [onStatus]
 * @returns {Promise<number[]>}
 */
export async function selectSampleRows(parquet, query, onStatus = () => {}) {
  if (!(parquet instanceof ArrayBuffer)) throw new Error("Reload the page to update the TACO reader.");
  const statement = normalizeQuery(query);
  if (!engineReady) onStatus("Loading SQL engine");
  const opened = await open();
  engineReady = true;
  return enqueue(async () => {
    const { db, connection } = opened;
    if (registered?.parquet !== parquet) await register(db, connection, parquet);
    onStatus("Running");
    const selection = `SELECT * FROM (\n${statement}\n) AS taco_query`;
    const columns = (await connection.query(`${selection} LIMIT 0`)).schema.fields.map((field) => field.name);
    const keys = identityColumns(columns, registered?.sourceFile ?? false);
    const rows = await connection.query(selectedRowsSql(selection, keys));
    return Array.from(rows.getChild("file_row_number").toArray(), Number);
  });
}

/** @param {unknown} query @returns {string} */
export function normalizeQuery(query) {
  let statement = String(query ?? "").trim();
  while (statement.endsWith(";")) statement = statement.slice(0, -1).trimEnd();
  return statement || DEFAULT_QUERY;
}

/** @param {string[]} columns @param {boolean} sourceFile @returns {string[]} */
export function identityColumns(columns, sourceFile = false) {
  if (columns.includes(SAMPLE_INDEX)) return [SAMPLE_INDEX];
  if (!columns.includes(CURRENT_ID)) {
    throw new Error(`The query must return ${SAMPLE_INDEX}; use SELECT * or include it.`);
  }
  if (!sourceFile) return [CURRENT_ID];
  if (!columns.includes(SOURCE_FILE)) {
    throw new Error(`A catalog query over sample must also return ${SOURCE_FILE}.`);
  }
  return [CURRENT_ID, SOURCE_FILE];
}

/** @param {string[]} names @returns {string} */
export function datasetView(names) {
  const columns = [];
  if (names.includes(SOURCE_FILE)) columns.push(`${quote(SOURCE_FILE)} AS source_file`);
  columns.push(`file_row_number AS ${quote(SAMPLE_INDEX)}`);
  if (names.includes("id")) columns.push(quote("id"));
  columns.push(...names.filter((name) => !name.startsWith("internal:") && !HIDDEN.has(name)).map(quote));
  return `SELECT ${columns.join(", ")} FROM taco_rows`;
}

function open() {
  engine ??= start().catch((error) => {
    engine = null;
    engineReady = false;
    throw error;
  });
  return engine;
}

function enqueue(task) {
  const result = sqlQueue.then(task);
  sqlQueue = result.catch(() => {});
  return result;
}

function selectedRowsSql(selection, keys) {
  if (keys[0] === SAMPLE_INDEX) {
    return `SELECT file_row_number FROM taco_rows WHERE file_row_number IN ` +
      `(SELECT ${quote(SAMPLE_INDEX)} FROM (${selection}) AS taco_selected) ORDER BY file_row_number`;
  }
  if (keys.length === 1) {
    return `SELECT file_row_number FROM taco_rows WHERE ${quote(CURRENT_ID)} IN ` +
      `(SELECT ${quote(CURRENT_ID)} FROM (${selection}) AS taco_selected) ORDER BY file_row_number`;
  }
  return `SELECT taco_source.file_row_number FROM taco_rows AS taco_source WHERE EXISTS (` +
    `SELECT 1 FROM (${selection}) AS taco_selected WHERE ` +
    `taco_selected.${quote(CURRENT_ID)} = taco_source.${quote(CURRENT_ID)} AND ` +
    `taco_selected.${quote(SOURCE_FILE)} = taco_source.${quote(SOURCE_FILE)}` +
    `) ORDER BY taco_source.file_row_number`;
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
  registered = { parquet, file, sourceFile: names.includes(SOURCE_FILE) };
}

/** @param {string} name */
function quote(name) {
  return `"${name.replaceAll('"', '""')}"`;
}

/** @param {string} value */
function literal(value) {
  return `'${value.replaceAll("'", "''")}'`;
}
