import test from "node:test";
import assert from "node:assert/strict";

import { extendRandomRowIndexes, randomRowIndexes } from "../../docs/playground/sampling.js";

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
