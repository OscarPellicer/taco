import test from "node:test";
import assert from "node:assert/strict";

import { extendRandomRowIndexes, populationRows, randomRowIndexes } from "../../docs/playground/sampling.js";
import { datasetView, identityColumn, normalizeQuery, selectSampleRows } from "../../docs/playground/sql.js";

test("selects a sorted random sample without replacement", () => {
  let seed = 123456789;
  const random = () => {
    seed = (1664525 * seed + 1013904223) >>> 0;
    return seed / 2 ** 32;
  };
  const rows = randomRowIndexes(1_000, 100, random);
  assert.equal(rows.length, 100);
  assert.equal(new Set(rows).size, 100);
  assert.ok(rows.every((row, index) => row >= 0 && row < 1_000 && (index === 0 || row > rows[index - 1])));
});

test("reads every row when the dataset fits the display limit", () => {
  assert.equal(randomRowIndexes(100, 100), null);
  assert.equal(randomRowIndexes(0, 100), null);
});

test("rejects invalid sampling bounds", () => {
  assert.throws(() => randomRowIndexes(-1, 100), /row count/);
  assert.throws(() => randomRowIndexes(100, 0), /display limit/);
});

test("extends a random sample without replacing existing rows", () => {
  let seed = 987654321;
  const random = () => {
    seed = (1664525 * seed + 1013904223) >>> 0;
    return seed / 2 ** 32;
  };
  const current = randomRowIndexes(1_000, 100, random);
  const extended = extendRandomRowIndexes(1_000, current, 250, random);
  assert.deepEqual(extended.slice(0, current.length), current);
  assert.equal(extended.length, 250);
  assert.equal(new Set(extended).size, 250);
  assert.ok(extended.every((row) => row >= 0 && row < 1_000));
});

test("caps extensions at the complete dataset", () => {
  const values = [0, .4, .8];
  assert.deepEqual(extendRandomRowIndexes(5, [1, 3], 10, () => values.shift()), [1, 3, 0, 2, 4]);
});

test("rejects invalid sample extensions", () => {
  assert.throws(() => extendRandomRowIndexes(10, [1, 1], 5), /unique/);
  assert.throws(() => extendRandomRowIndexes(10, [11], 5), /current row/);
  assert.throws(() => extendRandomRowIndexes(10, [1, 2], 1), /cannot shrink/);
});

test("maps sampled positions onto the rows a SQL filter kept", () => {
  assert.deepEqual(populationRows([0, 5], null), [0, 5]);
  assert.equal(populationRows(null, null), null);
  assert.deepEqual(populationRows(null, [3, 8, 13]), [3, 8, 13]);
  assert.deepEqual(populationRows([2, 0], [3, 8, 13]), [13, 3]);
  assert.deepEqual(populationRows(null, []), []);
});

test("normalizes a SQL filter query", () => {
  assert.equal(normalizeQuery("  SELECT * FROM dataset ;; "), "SELECT * FROM dataset");
  assert.equal(normalizeQuery("SELECT * FROM dataset -- all\n"), "SELECT * FROM dataset -- all");
  assert.throws(() => normalizeQuery(" ; "), /Write a query/);
  assert.throws(() => normalizeQuery(undefined), /Write a query/);
});

test("a SQL filter needs the sample identity", () => {
  assert.equal(identityColumn(["id", "taco:sample_index"]), "taco:sample_index");
  assert.equal(identityColumn(["internal:current_id", "id"]), "internal:current_id");
  assert.throws(() => identityColumn(["id", "ml:split"]), /must return taco:sample_index/);
});

test("the dataset view hides reader columns like the Python reader", () => {
  assert.equal(
    datasetView(["internal:current_id", "internal:relative_path", "id", "ml:split", "taco:location"]),
    'SELECT "internal:current_id" AS "taco:sample_index", "id", "ml:split" FROM "sample"',
  );
  assert.equal(
    datasetView(["internal:current_id", "internal:source_file", "id", 'odd"name:x']),
    'SELECT "internal:source_file" AS source_file, "internal:current_id" AS "taco:sample_index", "id", "odd""name:x" FROM "sample"',
  );
});

test("a SQL filter needs the cached sample.parquet bytes", async () => {
  await assert.rejects(() => selectSampleRows(undefined, "SELECT * FROM dataset"), /Reload the page/);
});
