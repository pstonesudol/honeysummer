import { test } from "node:test";
import assert from "node:assert/strict";
import { types, validatePullRequestTitle } from "../pr-title-lib.mjs";

test("accepts conventional titles and splits out their parts", () => {
  assert.deepEqual(validatePullRequestTitle("feat: gate backend releases on staging and production approval"), {
    type: "feat", scope: null, breaking: false, description: "gate backend releases on staging and production approval",
  });
  assert.deepEqual(validatePullRequestTitle("fix(api): reject expired staging tokens"), {
    type: "fix", scope: "api", breaking: false, description: "reject expired staging tokens",
  });
  assert.deepEqual(validatePullRequestTitle("refactor(inventory)!: drop the legacy stock column"), {
    type: "refactor", scope: "inventory", breaking: true, description: "drop the legacy stock column",
  });
  assert.deepEqual(validatePullRequestTitle("chore!: require Node 22"), {
    type: "chore", scope: null, breaking: true, description: "require Node 22",
  });
  for (const type of types) assert.equal(validatePullRequestTitle(`${type}: short summary`).type, type);
});

test("rejects titles without a known lowercase type", () => {
  for (const title of [
    "Add staging release approval",
    "feature: add staging release approval",
    "Feat: add staging release approval",
    "fixup: add staging release approval",
    "wip: add staging release approval",
  ]) {
    assert.throws(() => validatePullRequestTitle(title));
  }
});

test("rejects malformed separators, empty parts and stray whitespace", () => {
  for (const title of [
    "feat add staging release approval",
    "feat : add staging release approval",
    "feat:add staging release approval",
    "feat:",
    "feat: ",
    "feat(): add staging release approval",
    "feat(a b): add staging release approval",
    "feat(api): ",
    " feat: add staging release approval",
    "feat: add staging release approval ",
    "feat: add staging release approval\n\nBody text",
  ]) {
    assert.throws(() => validatePullRequestTitle(title));
  }
  for (const title of [undefined, null, ""]) assert.throws(() => validatePullRequestTitle(title));
});

test("the failure message names the type options and shows an example", () => {
  assert.throws(() => validatePullRequestTitle("Nope"), /docs, feat, fix/);
  assert.throws(() => validatePullRequestTitle("nope: x"), /"nope" is not an allowed type/);
});
