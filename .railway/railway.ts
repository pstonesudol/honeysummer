import { defineRailway, empty, postgres, project, service, volume } from "railway/iac";

export default defineRailway((ctx) => {
  if (ctx.projectName !== "Honey Summer" || !["staging", "production"].includes(ctx.environment)) {
    throw new Error("Select the Honey Summer project and its staging or production environment.");
  }

  // Resource names match the imported staging resources. Each environment has
  // its own database and volume; this does not copy data between environments.
  const Postgres = postgres("Postgres", { region: "iad" });
  Postgres.networking = { privateNetworkEndpoint: "postgres" };
  const postgresVolume = volume("postgres-volume", {
    alerts: { usage: { "100": {}, "80": {}, "95": {} } },
    allowOnlineResize: true,
    region: "iad",
    sizeMB: 500,
  });

  const backend = service("honeysummer", {
    // GitHub Actions owns deployment order and uploads the approved commit.
    // No GitHub source/branch: Railway webhooks must not bypass staging/approval.
    source: {
      ...empty(),
      rootDirectory: "/backend",
    },
    build: {
      builder: "RAILPACK",
      buildCommand: "uv sync --locked --no-dev",
    },
    // Run migrations once per release, not on every process restart.
    preDeploy: "uv run --no-sync alembic upgrade head",
    start: 'sh -c \'exec uv run --no-sync sanic app.server:app --host 0.0.0.0 --port "$PORT"\'',
    healthcheck: "/api/health/",
    healthcheckTimeout: 120,
    replicas: { iad: 1 },
    deploy: {
      restartPolicyType: "ON_FAILURE",
      restartPolicyMaxRetries: 3,
    },
  });

  const resources = [Postgres, postgresVolume, backend];
  if (ctx.environment === "staging") {
    // Proposed staging-only logical backup runner. Secrets and bucket names are
    // intentionally not managed here; configure only after separate approval.
    resources.push(
      service("honeysummer-staging-backup", {
        source: {
          ...empty(),
          rootDirectory: "/backend",
        },
        build: {
          builder: "DOCKERFILE",
          dockerfilePath: "backup.Dockerfile",
        },
        start: "uv run --no-sync python -m app.backup",
        deploy: {
          cronSchedule: "30 3 * * *",
          restartPolicyType: "NEVER",
        },
      }),
    );
  }

  return project("Honey Summer", {
    // Railway CLI variable ownership policy: never import or overwrite secrets.
    // Set DATABASE_URL and security/provider variables in the dashboard.
    variables: { managed: false },
    resources,
  });
});
