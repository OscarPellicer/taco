// Band and time indexes use the same spelling as variable file indexes: zero,
// or a decimal number without leading zeros.
const RUMI_STATISTIC = /^(minimum|maximum|mean|stddev|p2|p98)(_(b(0|[1-9][0-9]*)|t(0|[1-9][0-9]*)(_b(0|[1-9][0-9]*))?))?$/;

/**
 * The suffix of a valid Rumi field, or null.
 *
 * @param {string} field
 * @returns {string | null}
 */
export function rumiFileField(field) {
  if (!field.startsWith("rumi:")) return null;
  const name = field.slice("rumi:".length);
  return name === "header" || RUMI_STATISTIC.test(name) ? name : null;
}
