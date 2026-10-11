import { test } from "node:test";
import assert from "node:assert/strict";
import { checkStagingAccess, validateAccessDenial } from "../staging-access-lib.mjs";
import { smokePaths, stagingOrigin } from "../staging-smoke-lib.mjs";

const access = { clientId: "synthetic.access", clientSecret: "synthetic-secret" };

test("denial requires Access redirect or explicit denial, never a public page or upstream failure", () => {
  for (const status of [401, 403]) validateAccessDenial(new Response(null, { status }));
  validateAccessDenial(new Response(null, { status: 302, headers: {
    Location: "https://cool-thunder-025c.cloudflareaccess.com/cdn-cgi/access/login/staging.example",
  } }));
  for (const status of [200, 404, 500, 502]) {
    assert.throws(() => validateAccessDenial(new Response(null, { status })));
  }
  for (const Location of ["/admin/login", "https://wrong.example/login", "https://cool-thunder-025c.cloudflareaccess.com/other"]) {
    assert.throws(() => validateAccessDenial(new Response(null, { status: 302, headers: { Location } })));
  }
});

test("read-only checks deny anonymous/invalid tokens then verify valid token without following redirects", async () => {
  let calls = 0;
  await checkStagingAccess(async (url, options) => {
    calls++;
    assert.equal(new URL(url).origin, stagingOrigin);
    assert.equal(options.redirect, "manual");
    assert.ok(options.signal);
    if (calls <= 4) {
      assert.notEqual(options.headers["CF-Access-Client-Secret"], access.clientSecret);
      return new Response(null, { status: 403 });
    }
    assert.equal(options.headers["CF-Access-Client-Secret"], access.clientSecret);
    if (url.endsWith("/admin/")) return new Response(null, { status: 302,
      headers: { Location: "/admin/login", "Cache-Control": "no-store" } });
    if (url.endsWith("/api/health/")) return new Response('{"status":"ok","service":"honey-summer-api"}',
      { headers: { "Content-Type": "application/json" } });
    if (url.endsWith("/api/retail/flowers/")) return new Response("[]", { headers: { "Content-Type": "application/json" } });
    const headers = new Headers({ "Content-Type": "text/html" });
    for (const name of ["honeysummer_csrf", "honeysummer_security_csrf"]) {
      headers.append("Set-Cookie", `${name}=synthetic; Secure; HttpOnly; SameSite=Lax`);
    }
    return new Response('<title>Honey Summer</title><meta name="robots" content="noindex"><input type="password"><input name="csrf_token">', { headers });
  }, access);
  assert.equal(calls, 4 + smokePaths.length);
});

test("an open staging site fails immediately; missing credentials make no network calls", async () => {
  let calls = 0;
  const publicSite = async () => { calls++; return new Response("Public site"); };
  await assert.rejects(checkStagingAccess(publicSite, {}));
  assert.equal(calls, 0);
  await assert.rejects(checkStagingAccess(publicSite, access));
  assert.equal(calls, 1);
});
