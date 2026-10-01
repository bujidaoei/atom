import assert from "node:assert/strict";
import test from "node:test";
import { accessQuery, accessScope, handoffDestination } from "../src/lib/content-access.ts";

const binding = "a".repeat(32);
const challenge = "b".repeat(64);
const contentOrigin = `https://r-${binding}.content.example.org`;
const metadata = { binding, projectId: "project", projectTitle: "<script>title</script>", releaseId: "release",
  revisionId: "revision", audience: "owner", isCurrentRelease: false,
  publicationGeneration: 1, releaseCreatedAt: 1, expiresAt: Math.floor(Date.now() / 1000) + 60, contentOrigin };

test("query accepts exact scope and rejects ambiguous or oversized input", () => {
  const query = `?binding=${binding}&challenge=${challenge}`;
  assert.deepEqual(accessQuery(query), { binding, challenge });
  for (const invalid of [query + "&binding=" + binding, query + "&next=https://evil.example", "?binding=" + binding,
    query.replace(challenge, challenge.toUpperCase()), "?" + "a".repeat(257)]) assert.equal(accessQuery(invalid), null);
});

test("scope preserves literal display text and historical status while rejecting unbound origins", () => {
  assert.deepEqual(accessScope(metadata, binding), metadata);
  for (const patch of [{ binding: "c".repeat(32) }, { contentOrigin: "http://r-" + binding + ".example.org" },
    { contentOrigin: "https://evil.example.org" }, { contentOrigin: contentOrigin + "/" },
    { publicationGeneration: 0 }, { expiresAt: Infinity }, { audience: "team" }]) {
    assert.throws(() => accessScope({ ...metadata, ...patch }, binding));
  }
});

test("handoff accepts only the approved origin, fixed endpoint and fresh fragment credential", () => {
  const scope = accessScope(metadata, binding);
  const url = `${contentOrigin}/_atom/exchange#${challenge}`;
  assert.equal(handoffDestination({ url, expiresAt: metadata.expiresAt }, scope), url);
  for (const invalid of [url.replace(contentOrigin, "https://evil.example.org"),
    url.replace("/_atom/exchange", "/other"), url.replace("#", "?next=x#"),
    url.replace("https://", "https://user:pass@"), url.slice(0, -1)]) {
    assert.throws(() => handoffDestination({ url: invalid, expiresAt: metadata.expiresAt }, scope));
  }
  assert.throws(() => handoffDestination({ url, expiresAt: 1 }, scope));
});
