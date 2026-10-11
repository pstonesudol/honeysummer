import { test } from "node:test";
import assert from "node:assert/strict";
import { checkStaging, smokePaths, stagingOrigin, stagingAccessHeaders, validateStagingResponse } from "../staging-smoke-lib.mjs";

const access = { clientId: "synthetic.access", clientSecret: "synthetic-secret" };

const page = '<title>Honey Summer</title><meta content="noindex, nofollow" name="robots">';
const login = '<title>Sign in · Honey Summer admin</title><input type="password"><input name="csrf_token">';
function response(body, type = "text/html", status = 200, cookies = []) {
  const headers = new Headers({ "Content-Type": type });
  for (const cookie of cookies) headers.append("Set-Cookie", cookie);
  return new Response(body, { status, headers });
}
const cookies = ["honeysummer_csrf", "honeysummer_security_csrf"]
  .map(name => `${name}=synthetic; Secure; HttpOnly; SameSite=Lax`);

test("storefront fails closed for redirects, error pages and missing noindex", () => {
  validateStagingResponse("/", response(page), page);
  for (const [body, type, status] of [[page, "text/html", 302], [page, "text/html", 500],
    [page, "application/json", 200], ["<title>Honey Summer</title>", "text/html", 200],
    ["<title>Wrong service</title>", "text/html", 200]]) {
    assert.throws(() => validateStagingResponse("/", response(body, type, status), body));
  }
});

test("admin entry requires the form and both secure CSRF cookies", () => {
  validateStagingResponse("/admin/login", response(login, "text/html", 200, cookies), login);
  assert.throws(() => validateStagingResponse("/admin/login", response(login), login));
  for (const attribute of ["Secure", "HttpOnly", "SameSite=Lax"]) {
    const unsafe = cookies.map(cookie => cookie.replace(`; ${attribute}`, ""));
    assert.throws(() => validateStagingResponse("/admin/login", response(login, "text/html", 200, unsafe), login));
  }
  assert.throws(() => validateStagingResponse("/admin/login", response(page, "text/html", 200, cookies), page));
});

test("proxy responses must be real health and DB-backed catalogue JSON", () => {
  const health = JSON.stringify({ status: "ok", service: "honey-summer-api" });
  validateStagingResponse("/api/health/", response(health, "application/json"), health);
  validateStagingResponse("/api/retail/flowers/", response("[]", "application/json"), "[]");
  assert.throws(() => validateStagingResponse("/api/health/", response(page), page));
  assert.throws(() => validateStagingResponse("/api/health/", response("{}", "application/json"), "{}"));
  assert.throws(() => validateStagingResponse("/api/retail/flowers/", response("{}", "application/json"), "{}"));
});

test("anonymous admin redirect is not followed inside the Worker", () => {
  validateStagingResponse("/admin/", new Response(null, { status: 302,
    headers: { Location: "/admin/login", "Cache-Control": "no-store" } }), "");
  assert.throws(() => validateStagingResponse("/admin/", response(login), login));
  assert.throws(() => validateStagingResponse("/admin/", new Response(null, { status: 302,
    headers: { Location: "https://wrong.example/admin/login" } }), ""));
});

test("only fixed staging URLs are fetched with redirects disabled; failure blocks completion", async () => {
  const urls = [];
  const fetcher = async (url, options) => {
    urls.push(url);
    assert.equal(options.redirect, "manual");
    assert.equal(options.headers["CF-Access-Client-Id"], access.clientId);
    assert.equal(options.headers["CF-Access-Client-Secret"], access.clientSecret);
    assert.ok(options.signal);
    if (url.endsWith("/api/health/")) return response('{"status":"ok","service":"honey-summer-api"}', "application/json");
    if (url.endsWith("/api/retail/flowers/")) return response("[]", "application/json");
    if (url.endsWith("/admin/login")) return response(login, "text/html", 200, cookies);
    if (url.endsWith("/admin/")) return new Response(null, { status: 302,
      headers: { Location: "/admin/login", "Cache-Control": "no-store" } });
    return response(page);
  };
  assert.deepEqual(await checkStaging(fetcher, access), smokePaths);
  assert.deepEqual(urls, smokePaths.map(path => stagingOrigin + path));
  await assert.rejects(checkStaging(async () => response("unavailable", "text/html", 503), access));
});

test("Access credentials reject missing, partial or pasted header values without echoing secrets", () => {
  assert.equal(stagingAccessHeaders(access)["CF-Access-Client-Secret"], access.clientSecret);
  for (const invalid of [undefined, {}, { clientId: access.clientId }, { clientSecret: access.clientSecret },
    { ...access, clientSecret: "CF-Access-Client-Secret: synthetic-secret" },
    { ...access, clientId: " synthetic.access" }, { ...access, clientSecret: "secret\r\nInjected: value" }]) {
    assert.throws(() => stagingAccessHeaders(invalid), error => {
      assert.ok(!error.message.includes("synthetic"));
      return true;
    });
  }
});

test("an Access login redirect or denied token fails rather than following with credentials", async () => {
  for (const status of [302, 401, 403]) {
    let calls = 0;
    await assert.rejects(checkStaging(async (_url, options) => {
      calls++;
      assert.equal(options.redirect, "manual");
      return new Response("Denied", { status, headers: { Location: "https://access.example/login" } });
    }, access));
    assert.equal(calls, 1);
  }
});
