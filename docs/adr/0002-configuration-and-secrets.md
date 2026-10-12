# ADR-0002 — Configuration and secrets across environments

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-10-11 |
| **Related** | R9.1 (config), R10.1 (no secrets in images), R10.4 (ConfigMap/Secret), R10.11 (pod security), ADR-0001 |

## Context

The same code runs in four places: a developer laptop, CI, a local kind cluster, and (optionally, R10.15) a managed cloud cluster. Each needs different values (hosts, replica counts, credentials), and some of those values are secrets. We need one approach that is safe and the same everywhere.

## Decision

### Principle 1 — The application reads environment variables, and nothing else decides
`runtime.config.Settings` (pydantic-settings) is the **only** place configuration enters the code. It reads environment variables, validates them at startup and **fails fast** with a clear error if a required value is missing or invalid. The application never knows *how* the variables were delivered: that is the job of each environment ([twelve-factor config](https://12factor.net/config)).

### Principle 2 — Build once, configure per environment
Images contain **no configuration and no secrets** (R10.1). The *same* image, identified by git SHA, moves from CI to kind to cloud. Only the injected environment differs. That way what you tested is exactly what you deploy.

### Principle 3 — Configuration and secrets travel separately
| Kind | Examples | Where it lives | Reviewable in git? |
|---|---|---|---|
| **Configuration** | hosts, ports, timeouts, replica bounds, model names | Code defaults → `.env.example` → Helm `values-<env>.yaml` → ConfigMap | Yes |
| **Secret** | `POSTGRES_PASSWORD`, `OPENAI_API_KEY` | A secret store, injected at runtime only | **Never** |

### How each environment delivers them

| Environment | Configuration | Secrets | Who creates the secret |
|---|---|---|---|
| **Laptop** | `.env` (copied from the committed `.env.example`) | Same `.env`, git-ignored | You |
| **CI (GitHub Actions)** | `env:` in the workflow | Ephemeral, throw-away values for service containers (not secrets). Real ones (registry push, cloud deploy) come from **GitHub Environment secrets**, and cloud access uses **OIDC** instead of stored keys | GitHub / cloud IAM |
| **kind (local K8s)** | ConfigMap rendered from Helm values | K8s Secret created by `make k8s-secrets` from your local `.env`, never in Helm values or git (R10.4) | You, via make |
| **Cloud (R10.15)** | ConfigMap from `values-cloud.yaml` | **External Secrets Operator** syncs from the cloud secret manager (AWS Secrets Manager / Azure Key Vault / GCP Secret Manager) into a K8s Secret | Platform / cloud IAM |

```
                 ┌─────────────────────────────── same image (git SHA) ──────────────────────────────┐
 laptop:  .env ──► uv run --env-file / compose --env-file ──► env vars ──► Settings (validate, fail fast)
 CI:      workflow env + GitHub secrets (OIDC to cloud) ────► env vars ──► Settings
 k8s:     ConfigMap + Secret ──► envFrom ───────────────────► env vars ──► Settings
 cloud:   values-cloud + secret manager ─(External Secrets)─► K8s Secret ──► envFrom ──► Settings
```

### Rules
1. **No secret in git, images, Helm values, CLI arguments or logs.** Secrets are typed `SecretStr`, so they print as `**********`.
2. **`.env` is for local development only.** It is git-ignored; `.env.example` is committed with placeholders and documents every variable.
3. **Real environment variables beat `.env`.** `uv --env-file` and Compose only fill in variables that aren't already set, so CI or a shell export always wins over a stray file.
4. **Load `.env` with real dotenv parsers, not `make include`.** `make` would treat `.env` as Makefile syntax, so a password containing `$` or `#` would be silently mangled, and it would export every secret to every command make runs. We use `uv run --env-file` and `docker compose --env-file`.
5. **Short-lived credentials over long-lived ones.** CI authenticates to clouds and registries with OIDC or `GITHUB_TOKEN`, never a stored personal token or cloud key.
6. **Least privilege per environment.** Each GitHub Environment (e.g. `staging`, `production`) has its own secrets and protection rules (required reviewers for production). Pods get only the Secret keys they use.
7. **Scan for leaks automatically.** `gitleaks` runs as a pre-commit hook (blocks a secret before it's committed) and in CI (catches anything that got past it).
8. **Rotation is a redeploy, not a rebuild.** Changing a secret updates the K8s Secret; a checksum annotation on the pod template rolls the pods (R10.4).

## Alternatives considered

- **Secrets as mounted files instead of environment variables** (e.g. `/run/secrets/postgres_password`). Harder to leak than env vars: they don't show up in `docker inspect`, `/proc/<pid>/environ` or child processes. pydantic-settings supports this through `secrets_dir`. The spec (R10.4) asks for `envFrom`, so we use env vars and **revisit this in phase 12** as a hardening step.
- **Sealed Secrets / SOPS.** Encrypted secrets committed to git, decrypted in the cluster. Good for GitOps (Argo CD is out of scope for v1.0). External Secrets is the more common choice when a cloud secret manager exists.
- **direnv** to auto-load `.env` into the shell. Convenient, but it puts every secret into every shell process. `make` plus `uv --env-file` scopes them to the command that needs them.

## Consequences

- The Makefile no longer uses `include .env` / `export`. Backend commands use `uv run --env-file ../.env`; Compose uses `--env-file .env`.
- Unit tests run **without** `.env`, which proves they don't depend on local configuration.
- New: `.pre-commit-config.yaml` (gitleaks, ruff and basic file hygiene), `make hooks` to install it, and a `secrets` job in CI.
- Phase 12 adds `make k8s-secrets` and the ConfigMap/Secret split; R10.15 adds External Secrets.
