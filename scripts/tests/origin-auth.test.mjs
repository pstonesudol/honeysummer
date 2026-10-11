import { test } from "node:test";
import assert from "node:assert/strict";
import { releaseOriginHeaders } from "../origin-auth.mjs";

test("direct release probes require a staging credential and never send it to production", () => {
  const secret = "synthetic_" + "a".repeat(43);
  assert.equal(releaseOriginHeaders("staging", secret)["X-HoneySummer-Origin-Secret"], secret);
  assert.deepEqual(releaseOriginHeaders("production", secret), { "Cache-Control": "no-cache" });
  for (const invalid of [undefined, "", "short", "CF-Access-Client-Secret: synthetic", "a".repeat(129)]) {
    assert.throws(() => releaseOriginHeaders("staging", invalid));
  }
});
