// Pull request titles are squashed into the commit subject on `main`, so this
// gate keeps that history conventional and machine-readable. Only the title
// (subject line) is validated; commit bodies and footers are out of scope.
//
// Grammar: <type>(<scope>)!: <description>

export const types = [
  "build", "chore", "ci", "docs", "feat", "fix",
  "perf", "refactor", "revert", "style", "test",
];

// A lowercase type, an optional `(scope)`, an optional `!` for breaking
// changes, then `: ` and a single-line description with no edge whitespace.
const subject = /^([a-z]+)(?:\(([^()\s]+)\))?(!)?: (\S(?:.*\S)?)$/;

const guidance = [
  "Pull request titles must use Conventional Commits:",
  "",
  "  <type>(<scope>)!: <description>",
  "",
  `  <type>     one of: ${types.join(", ")}`,
  "  <scope>    optional, e.g. feat(api):",
  "  !          optional, marks a breaking change",
  "",
  "Examples:",
  "  feat: gate backend releases on staging and production approval",
  "  fix(api): reject expired staging tokens",
  "  docs: document the production backup runbook",
].join("\n");

export function validatePullRequestTitle(title) {
  if (typeof title !== "string" || !title) {
    throw new Error(`A pull request title is required.\n\n${guidance}`);
  }
  if (title !== title.trim() || /[\r\n]/.test(title)) {
    throw new Error(`The title must be a single line without surrounding whitespace.\n\n${guidance}`);
  }
  const match = subject.exec(title);
  if (!match) {
    throw new Error(`"${title}" is not a valid Conventional Commits title.\n\n${guidance}`);
  }
  const [, type, scope, breaking, description] = match;
  if (!types.includes(type)) {
    throw new Error(`"${type}" is not an allowed type.\n\n${guidance}`);
  }
  return { type, scope: scope ?? null, breaking: Boolean(breaking), description };
}
