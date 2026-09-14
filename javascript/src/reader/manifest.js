import { directoryUrl, httpUrl } from "../container/http.js";
import { parseCollection } from "../contract/collection.js";
import { fail } from "../errors.js";

const SEMVER = /^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$/;

/** @param {unknown} value @param {string} context */
function object(value, context) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    fail("INVALID_MANIFEST", `${context} must be an object`);
  }
  return /** @type {Record<string, any>} */ (value);
}

/** @param {string} source */
function sourceName(source) {
  const pathname = new URL(source).pathname.replace(/\/+$/, "");
  return pathname.slice(pathname.lastIndexOf("/") + 1);
}

/** @param {string} source */
function directSource(source) {
  const name = sourceName(source);
  return name === ".tacocat" || name.toLowerCase().endsWith(".zip") || SEMVER.test(name);
}

/**
 * Normalize one JavaScript reader source.
 *
 * @param {unknown} source
 */
export function normalizeSources(source) {
  return [httpUrl(source)];
}

/**
 * Return the manifest URL to probe, or null for an unambiguous container.
 *
 * @param {string} source
 */
export function manifestCandidate(source) {
  if (sourceName(source) === "taco.json") return source;
  if (directSource(source)) return null;
  return new URL("taco.json", directoryUrl(source)).href;
}

/**
 * Read and validate a version manifest.
 *
 * @param {import("../container/http.js").HttpClient} client
 * @param {string} candidate
 * @param {boolean} required
 */
export async function readManifest(client, candidate, required = true) {
  const bytes = required ? await client.get(candidate) : await client.getOptional(candidate);
  if (bytes === null) return null;
  let value;
  try {
    value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } catch (error) {
    fail("INVALID_MANIFEST", `versioned manifest is not valid JSON: ${candidate}`);
  }
  const manifest = object(value, "versioned manifest");
  if (manifest["taco:container"] !== "versioned") {
    fail("INVALID_MANIFEST", "taco:container must be 'versioned'");
  }
  return manifest;
}

/** @param {string} candidate @param {string} href */
export function joinManifestHref(candidate, href) {
  return new URL(href, candidate).href;
}

/**
 * Resolve a versioned collection root to its default version.
 *
 * @param {unknown} source
 * @param {import("../container/http.js").HttpClient} client
 */
export async function resolveDataset(source, client) {
  const sources = normalizeSources(source);
  const original = sources[0];
  const explicit = sourceName(original) === "taco.json";
  const candidate = manifestCandidate(original);
  if (candidate === null) return directResolution(original);

  const manifest = await readManifest(client, candidate, explicit);
  if (manifest === null) return directResolution(original);
  const versions = object(manifest["taco:versions"], "taco:versions");
  const versionNames = Object.keys(versions);
  if (versionNames.length === 0) {
    fail("INVALID_MANIFEST", "taco:versions must contain at least one version");
  }
  const selected = manifest["taco:default_version"];
  if (typeof selected !== "string" || selected.length === 0) {
    fail("INVALID_MANIFEST", "taco:default_version must be a non-empty string");
  }
  if (!(selected in versions)) {
    fail("INVALID_MANIFEST", `taco:default_version ${JSON.stringify(selected)} is not present in taco:versions`);
  }

  /** @type {Map<string, {href: string, collection: Record<string, any>}>} */
  const entries = new Map();
  for (const version of versionNames) {
    if (!SEMVER.test(version)) {
      fail("INVALID_MANIFEST", `taco:versions key ${JSON.stringify(version)} must follow Semantic Versioning`);
    }
    const entry = object(versions[version], `version ${JSON.stringify(version)}`);
    const href = entry.href;
    if (typeof href !== "string" || href.length === 0) {
      fail("INVALID_MANIFEST", `version ${JSON.stringify(version)} needs a non-empty href`);
    }
    const collection = object(entry.collection, `version ${JSON.stringify(version)} collection`);
    if (collection.dataset_version !== version) {
      fail(
        "INVALID_MANIFEST",
        `version ${JSON.stringify(version)} embeds collection dataset_version ${JSON.stringify(collection.dataset_version)}`,
      );
    }
    entries.set(version, { href, collection });
  }

  const entry = entries.get(selected);
  if (!entry) throw new Error("taco: selected manifest entry disappeared");
  let parsed;
  try {
    parsed = parseCollection(entry.collection);
  } catch (error) {
    if (error instanceof Error) {
      error.message = `taco: version ${JSON.stringify(selected)} embeds an invalid collection: ${error.message}`;
    }
    throw error;
  }
  return {
    sources: [joinManifestHref(candidate, entry.href)],
    collection: parsed,
    version: selected,
    versions: versionNames,
    manifest: candidate,
  };
}

/** @param {string} source */
function directResolution(source) {
  return {
    sources: [source],
    collection: null,
    version: null,
    versions: [],
    manifest: null,
  };
}
