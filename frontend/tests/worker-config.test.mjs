import { test } from "node:test";
import assert from "node:assert/strict";
import { workerConfig } from "../scripts/worker-config.mjs";

test("staging targets its own Worker, self-binding and Railway backend", () => {
  const { target, vars } = workerConfig("staging");
  assert.equal(target.name, "honey-summer-staging");
  assert.equal(target.services[0].service, target.name);
  assert.equal(vars.API_URL, "https://honeysummer-staging.up.railway.app");
  assert.equal(vars.DEPLOYMENT_ENVIRONMENT, "staging");
  assert.equal(target.preview_urls, false);
});

test("production fails closed until its backend is supplied", () => {
  assert.throws(() => workerConfig("production"), /API_URL/);
  const { target, vars } = workerConfig("production", {
    API_URL: "https://honeysummer-production.up.railway.app/",
  });
  assert.equal(target.name, "honey-summer");
  assert.equal(target.services[0].service, target.name);
  assert.equal(vars.API_URL, "https://honeysummer-production.up.railway.app");
  assert.equal(vars.NEXT_PUBLIC_SITE_URL, "https://hellohoneysummer.com");
});

test("environment selection is explicit and unrelated API_URL values cannot leak into staging", () => {
  assert.throws(() => workerConfig(undefined), /explicitly/);
  assert.throws(() => workerConfig("other"), /explicitly/);
  assert.throws(() => workerConfig("staging", { API_URL: "https://production.example.com" }), /Staging/);
  assert.throws(() => workerConfig("production", {
    API_URL: "https://honeysummer-staging.up.railway.app",
  }), /Production/);
  assert.throws(() => workerConfig("staging", {
    NEXT_PUBLIC_SITE_URL: "https://hellohoneysummer.com",
  }), /production storefront/);
});

test("origins reject insecure URLs, credentials, paths and query strings", () => {
  for (const value of ["http://localhost:8000", "https://user:pass@example.com",
    "https://example.com/api", "https://example.com?token=secret", "https://example.com#fragment",
    "not-a-url", "https://localhost"]) {
    assert.throws(() => workerConfig("production", { API_URL: value }), /HTTPS origin/);
  }
});

test("staging may use a generated Workers origin without changing production", () => {
  const { vars } = workerConfig("staging", {
    NEXT_PUBLIC_SITE_URL: "https://honey-summer-staging.example.workers.dev",
  });
  assert.equal(vars.NEXT_PUBLIC_SITE_URL, "https://honey-summer-staging.example.workers.dev");
  assert.equal(workerConfig("staging").vars.NEXT_PUBLIC_SITE_URL, "https://staging.hellohoneysummer.com");
});
