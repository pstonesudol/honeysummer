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

  // A separate, disposable target for the staging restore rehearsal. Its private
  // hostname includes "restore" so the restore guard can reject live databases.
  const RestorePostgres = postgres("staging-restore-postgres", { region: "iad" });
  const restorePostgresVolume = volume("staging-restore-postgres-volume", {
    alerts: { usage: { "100": {}, "80": {}, "95": {} } },
    allowOnlineResize: true,
    region: "iad",
    // Railway provisioned the template's 5 GB default; do not request an
    // unsupported/dangerous in-place shrink for this disposable target.
    sizeMB: 5000,
  });

  const backend = service("honeysummer", {
    // Preserve the existing GitHub repository association and root while leaving
    // its disconnected deploy triggers and default restart policy untouched.
    source: { type: "github", rootDirectory: "/backend" },
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
      restartPolicyMaxRetries: 3,
    },
  });

  const resources = [Postgres, postgresVolume, backend];
  if (ctx.environment === "staging") {
    // Staging-only backup and restore runners. Secret values are never managed
    // by IaC; target and permission details are documented in the runbook.
    resources.push(
      RestorePostgres,
      restorePostgresVolume,
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
      service("honeysummer-staging-restore-runner", {
        source: {
          ...empty(),
          rootDirectory: "/backend",
        },
        build: {
          builder: "DOCKERFILE",
          dockerfilePath: "backup.Dockerfile",
        },
        // A manual workflow deploys this one-off runner only after the operator
        // supplies a snapshot key and exact isolated-target confirmation.
        start: 'sh -c \'printf "%s\\n" "$RESTORE_CONFIRMATION" | uv run --no-sync python -m app.restore_backup "$RESTORE_MANIFEST_KEY"\'',
        deploy: {
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
