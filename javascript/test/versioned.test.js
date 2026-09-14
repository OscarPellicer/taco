import { after, before, test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import { openDataset, read, TacoError } from "../src/index.js";
import { joinManifestHref, manifestCandidate } from "../src/reader/manifest.js";
import { fixtureServer } from "./server.js";

let fixture;

before(async () => {
  fixture = await fixtureServer();
});

after(async () => {
  await fixture.close();
});

test("opens a versioned root from one manifest request", async () => {
  const start = fixture.requests.length;
  const dataset = await openDataset(`${fixture.baseUrl}/versioned/`);

  assert.equal(dataset.url, `${fixture.baseUrl}/versioned/2.0.0/`);
  assert.deepEqual(dataset.sources, [`${fixture.baseUrl}/versioned/2.0.0/`]);
  assert.equal(dataset.collection.dataset_version, "2.0.0");
  assert.equal(dataset.version, "2.0.0");
  assert.deepEqual(dataset.versions, ["1.0.0", "2.0.0"]);
  assert.equal(dataset.manifest, `${fixture.baseUrl}/versioned/taco.json`);
  assert.deepEqual(fixture.requests.slice(start).map((request) => request.path), ["/versioned/taco.json"]);
});

test("versioned read uses embedded collection and selected metadata", async () => {
  const start = fixture.requests.length;
  const rows = await read(`${fixture.baseUrl}/versioned`, {
    idx: 0,
    files: ["image.bin"],
    location: false,
  });

  assert.equal(rows.length, 1);
  assert.equal(rows[0].sample_id, 0);
  const paths = fixture.requests.slice(start).map((request) => request.path);
  assert.equal(paths[0], "/versioned/taco.json");
  assert.ok(paths.includes("/versioned/2.0.0/METADATA/sample.parquet"));
  assert.ok(!paths.includes("/versioned/2.0.0/COLLECTION.json"));
});

test("explicit semantic-version path skips discovery", async () => {
  const start = fixture.requests.length;
  const dataset = await openDataset(`${fixture.baseUrl}/versioned/1.0.0/`);

  assert.equal(dataset.version, "1.0.0");
  assert.deepEqual(dataset.versions, []);
  assert.equal(dataset.manifest, null);
  const paths = fixture.requests.slice(start).map((request) => request.path);
  assert.deepEqual(paths, ["/versioned/1.0.0/COLLECTION.json"]);
});

test("direct archives skip manifest discovery", async () => {
  const start = fixture.requests.length;
  await openDataset(`${fixture.baseUrl}/dataset.zip`);
  const paths = fixture.requests.slice(start).map((request) => request.path);
  assert.ok(!paths.some((path) => path.endsWith("/taco.json")));
});

test("only an implicit 404 falls back to a direct dataset", async () => {
  const unavailable = async () => new Response("unavailable", { status: 503, statusText: "Unavailable" });
  await assert.rejects(
    () => openDataset("https://example.test/root/", { fetch: unavailable }),
    (error) => error instanceof TacoError && error.code === "HTTP_ERROR" && /HTTP 503/.test(error.message),
  );

  const missing = async () => new Response("missing", { status: 404, statusText: "Not Found" });
  await assert.rejects(
    () => openDataset("https://example.test/root/taco.json", { fetch: missing }),
    (error) => error instanceof TacoError && error.code === "HTTP_ERROR" && /HTTP 404/.test(error.message),
  );
});

test("rejects malformed manifests before opening their target", async () => {
  const cases = [
    [{ "taco:container": "folder" }, /taco:container/],
    [{ "taco:container": "versioned", "taco:default_version": "1.0.0", "taco:versions": {} }, /at least one/],
    [
      {
        "taco:container": "versioned",
        "taco:default_version": "latest",
        "taco:versions": { latest: { href: "data/", collection: { dataset_version: "latest" } } },
      },
      /Semantic Versioning/,
    ],
  ];

  for (const [manifest, message] of cases) {
    let requests = 0;
    const fetch = async () => {
      requests += 1;
      return new Response(JSON.stringify(manifest), { status: 200 });
    };
    await assert.rejects(() => openDataset("https://example.test/root/", { fetch }), message);
    assert.equal(requests, 1);
  }
});

test("top-level read supports raw levels through the shared level option", async () => {
  const rows = await read(`${fixture.baseUrl}/dataset.zip`, { level: "sample", idx: 0 });
  assert.equal(rows.length, 1);
  assert.equal(rows[0]["internal:current_id"], 0n);
  assert.ok(!("taco:location" in rows[0]));
});

test("URL resolution follows the shared conformance cases", async () => {
  const path = new URL("../../r/inst/conformance/reader-resolution.json", import.meta.url);
  const cases = JSON.parse(await readFile(path, "utf8"));
  for (const entry of cases.manifest_candidates) {
    assert.equal(manifestCandidate(entry.source), entry.expected);
  }
  for (const entry of cases.manifest_hrefs) {
    assert.equal(joinManifestHref(entry.candidate, entry.href), entry.expected);
  }
});
