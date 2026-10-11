import { test } from "node:test";
import assert from "node:assert/strict";
import { isBackendPath, maxProxyBodyBytes, proxyBackend } from "../scripts/backend-proxy.mjs";

const site = "https://staging.hellohoneysummer.com";
const backend = "https://honeysummer-staging.up.railway.app";

test("only API/admin/media boundaries are proxied", () => {
  for (const path of ["/api", "/api/health/", "/admin", "/admin/", "/admin/login", "/media/photo.jpg"]) {
    assert.equal(isBackendPath(path), true);
  }
  for (const path of ["/", "/administrator", "/apiary", "/order-flowers", "/_next/image"]) {
    assert.equal(isBackendPath(path), false);
  }
});

test("login returns the redirect and all session cookies instead of following it", async () => {
  let calls = 0;
  const cookies = [
    "honeysummer_admin=synthetic; Path=/; Secure; HttpOnly; SameSite=Lax",
    "honeysummer_csrf=synthetic; Path=/; Secure; HttpOnly; SameSite=Lax",
  ];
  const request = new Request(`${site}/admin/login`, {
    method: "POST", headers: { Origin: site, Cookie: "honeysummer_csrf=synthetic",
      "Content-Type": "application/x-www-form-urlencoded" },
    body: "email=synthetic%40example.com&password=synthetic&csrf_token=synthetic",
  });
  const response = await proxyBackend(request, backend, async forwarded => {
    calls++;
    assert.equal(forwarded.url, `${backend}/admin/login`);
    assert.equal(forwarded.redirect, "manual");
    assert.equal(forwarded.method, "POST");
    assert.equal(forwarded.headers.get("origin"), site);
    assert.equal(forwarded.headers.get("cookie"), "honeysummer_csrf=synthetic");
    assert.match(await forwarded.text(), /csrf_token=synthetic/);
    const headers = new Headers({ Location: "/admin/" });
    for (const cookie of cookies) headers.append("Set-Cookie", cookie);
    return new Response(null, { status: 302, headers });
  });
  assert.equal(calls, 1);
  assert.equal(response.status, 302);
  assert.equal(response.headers.get("location"), "/admin/");
  assert.deepEqual(response.headers.getSetCookie(), cookies);
  assert.equal(response.headers.get("cache-control"), "no-store");
});

test("logout preserves session deletion and backend absolute redirects stay same-origin", async () => {
  const cookie = "honeysummer_admin=; Max-Age=0; Path=/; Secure; HttpOnly; SameSite=Lax";
  const response = await proxyBackend(new Request(`${site}/admin/logout`, { method: "POST" }), backend,
    async () => new Response(null, { status: 302,
      headers: { Location: `${backend}/admin/login?loggedout=1`, "Set-Cookie": cookie } }));
  assert.equal(response.headers.get("location"), "/admin/login?loggedout=1");
  assert.deepEqual(response.headers.getSetCookie(), [cookie]);
});

test("external payment redirects are not followed or rewritten", async () => {
  const location = "https://checkout.stripe.com/synthetic";
  const response = await proxyBackend(new Request(`${site}/api/checkout/`), backend,
    async request => {
      assert.equal(request.redirect, "manual");
      return new Response(null, { status: 303, headers: { Location: location } });
    });
  assert.equal(response.status, 303);
  assert.equal(response.headers.get("location"), location);
});

test("GET/query, errors, private media and auth headers pass through without swallowing failures", async () => {
  const response = await proxyBackend(new Request(`${site}/media/private/photo?download=1`, {
    headers: { Cookie: "honeysummer_admin=synthetic", Authorization: "Bearer synthetic" },
  }), backend, async request => {
    assert.equal(request.url, `${backend}/media/private/photo?download=1`);
    assert.equal(request.headers.get("cookie"), "honeysummer_admin=synthetic");
    assert.equal(request.headers.get("authorization"), "Bearer synthetic");
    return new Response("Forbidden", { status: 403 });
  });
  assert.equal(response.status, 403);
  assert.equal(await response.text(), "Forbidden");
});

test("invalid origins and non-backend paths cannot become arbitrary upstream requests", async () => {
  const fail = async () => { throw new Error("Must not fetch"); };
  for (const api of ["http://localhost:8000", `${backend}/path`, "https://user:secret@example.com", `${backend}?x=1`]) {
    await assert.rejects(proxyBackend(new Request(`${site}/admin/login`), api, fail), /HTTPS origin/);
  }
  await assert.rejects(proxyBackend(new Request(`${site}/order-flowers`), backend, fail), /Not a backend route/);
});

test("12 MiB upload limit remains enforced for declared and streaming bodies", async () => {
  const declared = await proxyBackend(new Request(`${site}/admin/upload`, {
    method: "POST", headers: { "Content-Length": String(maxProxyBodyBytes + 1) }, body: "synthetic",
  }), backend, async () => { throw new Error("Oversized request must not be sent"); });
  assert.equal(declared.status, 413);

  const stream = new ReadableStream({ start(controller) {
    controller.enqueue(new Uint8Array(maxProxyBodyBytes));
    controller.enqueue(new Uint8Array(1));
    controller.close();
  } });
  const streaming = await proxyBackend(new Request(`${site}/admin/upload`, {
    method: "POST", body: stream, duplex: "half",
  }), backend, async request => {
    await request.arrayBuffer();
    return new Response("Unexpected success");
  });
  assert.equal(streaming.status, 413);
});
