import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { runInNewContext } from "node:vm";

const template = readFileSync(new URL("../../backend/templates/admin/edit.html", import.meta.url), "utf8");
const script = template.match(/<script>([\s\S]*?)<\/script>/)[1];

function setup(currentSrc = "") {
  const events = {};
  const revoked = [];
  const input = {
    files: [], value: "", form: { addEventListener: (name, fn) => { events[name] = fn; } },
    addEventListener: (name, fn) => { events[name] = fn; }, focus() {},
  };
  const image = { dataset: { currentSrc }, removeAttribute(name) { delete this[name]; } };
  const preview = { hidden: !currentSrc, querySelector: () => image };
  const status = { textContent: "Initial status" };
  const clear = { hidden: true, addEventListener: (name, fn) => { events.clear = fn; } };
  const upload = { querySelector: (selector) => ({ input, figure: preview, '[role="status"]': status, '[data-clear-image]': clear })[selector] };
  runInNewContext(script, {
    document: { querySelectorAll: () => [upload] },
    window: { addEventListener: (name, fn) => { events[name] = fn; } },
    URL: { createObjectURL: (file) => `blob:${file.name}`, revokeObjectURL: (url) => revoked.push(url) },
    setTimeout: (fn) => fn(),
  });
  const select = (name, type = "image/png") => {
    input.files = [{ name, type, size: 1048576 }];
    events.change();
  };
  return { events, revoked, input, image, preview, status, clear, select };
}

test("admin preview replaces selections and releases temporary image URLs", () => {
  const ui = setup("/media/saved.webp");
  ui.select("first.png");
  assert.equal(ui.image.src, "blob:first.png");
  assert.equal(ui.preview.hidden, false);
  assert.equal(ui.clear.hidden, false);
  assert.match(ui.status.textContent, /first.png · 1.00 MB · Selected, not yet saved/);
  ui.select("second.png");
  assert.deepEqual(ui.revoked, ["blob:first.png"]);
  ui.input.files = [];
  ui.events.clear();
  assert.equal(ui.image.src, "/media/saved.webp");
  assert.equal(ui.preview.hidden, false);
  assert.equal(ui.clear.hidden, true);
  assert.equal(ui.status.textContent, "Initial status");
  assert.deepEqual(ui.revoked, ["blob:first.png", "blob:second.png"]);
});

test("empty, invalid and unreadable previews can be cleared without submitting", () => {
  const ui = setup();
  ui.select("notes.txt", "text/plain");
  assert.equal(ui.preview.hidden, true);
  assert.match(ui.status.textContent, /choose an image/);
  ui.select("broken.png");
  ui.image.onerror();
  assert.equal(ui.preview.hidden, true);
  assert.deepEqual(ui.revoked, ["blob:broken.png"]);
  ui.input.files = [];
  ui.events.reset();
  assert.equal(ui.preview.hidden, true);
  assert.equal(ui.image.src, undefined);
  ui.select("final.png");
  ui.events.pagehide();
  assert.deepEqual(ui.revoked, ["blob:broken.png", "blob:final.png"]);
});
