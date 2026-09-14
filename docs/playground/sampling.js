/**
 * Select a uniform random sample of physical Parquet row indexes.
 * Returns null when every row should be displayed.
 *
 * @param {number} totalRows
 * @param {number} limit
 * @param {() => number} [random]
 * @returns {number[] | null}
 */
export function randomRowIndexes(totalRows, limit, random = Math.random) {
  if (!Number.isSafeInteger(totalRows) || totalRows < 0) {
    throw new RangeError("The sample row count is invalid.");
  }
  if (!Number.isSafeInteger(limit) || limit <= 0) {
    throw new RangeError("The point display limit must be positive.");
  }
  if (totalRows <= limit) return null;

  const selected = new Set();
  for (let row = totalRows - limit; row < totalRows; row += 1) {
    const candidate = Math.floor(random() * (row + 1));
    selected.add(selected.has(candidate) ? row : candidate);
  }
  return [...selected].sort((left, right) => left - right);
}

/**
 * Add uniformly selected physical row indexes without replacing the current
 * sample. Existing indexes keep their order so rendered points stay stable.
 *
 * @param {number} totalRows
 * @param {number[]} current
 * @param {number} targetSize
 * @param {() => number} [random]
 * @returns {number[]}
 */
export function extendRandomRowIndexes(totalRows, current, targetSize, random = Math.random) {
  if (!Number.isSafeInteger(totalRows) || totalRows < 0) {
    throw new RangeError("The sample row count is invalid.");
  }
  if (!Number.isSafeInteger(targetSize) || targetSize <= 0) {
    throw new RangeError("The point display limit must be positive.");
  }
  if (!Array.isArray(current) || current.some((row) => !Number.isSafeInteger(row) || row < 0 || row >= totalRows)) {
    throw new RangeError("The current row indexes are invalid.");
  }
  const selected = new Set(current);
  if (selected.size !== current.length) throw new RangeError("The current row indexes must be unique.");
  const target = Math.min(totalRows, targetSize);
  if (target < current.length) throw new RangeError("The target size cannot shrink the current sample.");

  const additions = [];
  while (selected.size < target) {
    const candidate = Math.floor(random() * totalRows);
    if (selected.has(candidate)) continue;
    selected.add(candidate);
    additions.push(candidate);
  }
  return [...current, ...additions];
}
