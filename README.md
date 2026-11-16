# FleetPulse

Telemetry service for a simulated drone fleet, built to show the full path
**commit → test → scan → multi-arch image → server release → deploy to AWS Graviton (ARM64) → monitor**,
with an AI agent that explains CI failures.

## Pipeline

```
dev[git push / PR] --> test[Lint · pytest · Terraform validate · kubeconform]
test --> ver[SemVer from Conventional Commits]
ver --> scan1[Build amd64 · Trivy scan · smoke test]
scan1 --> img[Buildx amd64+arm64 · SBOM · provenance → GHCR]
img --> rel[Git tag + GitHub Release]
rel --> dep[Docker → AWS SSM → EC2 tag Graviton]
test -.-> |on failure| doc[CI Doctor: Claude diagnoses logs → PR comment]
dep --> mon[Prometheus alerts · Grafana]
```

## What's in it

| Area | Where | What it shows |
| --- | --- | --- |
| Service | `src/fleetpulse/` | FastAPI API: ingest telemetry, per-drone status, low-battery flag, Prometheus `/metrics` |
| Tests | `tests/` | pytest (coverage gate 85%), flake8, shell tests for the versioning script |
| Container | `Dockerfile` | Multi-stage build, non-root user, healthcheck, OCI labels, BuildKit pip cache |
| CI/CD | `.github/workflows/ci.yml` | Multi-arch Buildx + QEMU, Trivy gate, SBOM + provenance, GHCR, auto SemVer release, keyless deploy |
| Versioning | `scripts/next_version.sh` | Conventional Commits → major.minor.patch |
| AI | `ci_doctor/`, `.github/workflows/ci-doctor.yml` | On a failed CI run, Claude reads the failed-step logs and posts root cause, evidence and fix |
| IaC | `infra/terraform/` | Graviton EC2, IMDSv2, encrypted disk, no SSH (SSM only), GitHub OIDC role scoped to one instance |
| Kubernetes | `k8s/` | Kustomize, probes, resource limits, read-only root FS, dropped capabilities |
| Observability | `monitoring/`, `docker-compose.yml` | Prometheus scrape + alert rules, Grafana, simulator generating live traffic |

## Run it locally

```bash
docker compose up --build
# API        http://localhost:8000/docs
# Prometheus http://localhost:9090 (Alerts tab: DroneLowBattery fires as simulated batteries drain)
# Grafana    http://localhost:3000 (Explore → fleetpulse_drone_battery_pct)
```

The simulator starts six drones at roughly 80–95% battery and drains them about
0.7% per frame, so `DroneLowBattery` goes pending within a couple of minutes and
firing shortly after. Grafana is pre-provisioned: dashboard **FleetPulse**.

Without Docker:

```bash
pip install -r requirements-dev.txt
PYTHONPATH=src uvicorn fleetpulse.main:app --reload
python simulator/simulate.py            # in a second shell
```

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/v1/telemetry` | Ingest one frame (201) |
| `GET` | `/v1/drones` | Latest status of every drone |
| `GET` | `/v1/drones/{id}` | One drone |
| `GET` | `/v1/drones/{id}/history?limit=20` | Recent frames, oldest first |
| `DELETE` | `/v1/drones/{id}` | Forget a drone (204) |
| `GET` | `/v1/fleet/summary` | Rollup: drones, frames, low-battery list, mean battery |
| `GET` | `/healthz`, `/readyz` | Liveness, readiness |
| `GET` | `/metrics` | Prometheus exposition |

Metrics: `fleetpulse_telemetry_total`, `fleetpulse_low_battery_total`,
`fleetpulse_drones_tracked`, `fleetpulse_drone_battery_pct{drone_id}`,
`fleetpulse_ingest_seconds`, `fleetpulse_http_requests_total`,
`fleetpulse_http_request_duration_seconds`.

## Tests

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt -r ci_doctor/requirements.txt
flake8 src tests simulator ci_doctor && pytest
bash tests/test_next_version.sh        # 20 assertions on the SemVer script
```

`pytest` enforces the 85% coverage gate from `pyproject.toml` and also runs the
bash suite through `tests/test_version_script.py`, so one command covers
everything. Current: 74 tests, 98% coverage of `src/fleetpulse`.

## Put it on GitHub

1. Create a public repo `fleetpulse`, replace `OWNER` in `Dockerfile` and `k8s/*.yaml` with your GitHub username, push.
2. Commit with Conventional Commits (`feat:`, `fix:`). The first `feat:` on `main` releases `v0.1.0`.
3. After the first push, open the `fleetpulse` package on GitHub → Package settings → make it **public** (so EC2 can pull it without credentials).
4. **CI Doctor:** add repo secret `ANTHROPIC_API_KEY`. Break a test in a PR to see the comment it posts.

## Deploy to AWS (optional; costs money)

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # fill in image, your IP/32, owner/repo
terraform init && terraform apply
```

Then in the GitHub repo set **variables**: `AWS_DEPLOY_ROLE_ARN`, `EC2_INSTANCE_ID` (from the outputs) and `AWS_REGION`, and create an environment named `production`.
Every release on `main` then rolls out automatically. `terraform destroy` when done.

## Design notes

- **Why Graviton:** the image is built for amd64 and arm64. CI tests on amd64 and production runs on arm64, the same cloud-to-edge split as Jetson boards.
- **Why SSM instead of SSH:** no open port 22, no keys to rotate, every deploy is logged in AWS.
- **Why OIDC:** GitHub gets short-lived AWS credentials only for `main`. No AWS keys are stored in GitHub.
- **CI Doctor** uses `claude-opus-5-5` with server-side refusal fallbacks. It sends only the last 400 lines of the failed step. If the API call fails, it posts a note and exits 0, so it never hides the real failure.

### Configuration

| Variable | Used by | Default |
| --- | --- | --- |
| `LOW_BATTERY_PCT` | service | `20` |
| `MAX_DRONES` / `HISTORY_SIZE` | service | `500` / `50` |
| `CLAUDE_MODEL` | CI Doctor | `claude-opus-5-5` |
| `CLAUDE_FALLBACK_MODELS` | CI Doctor | empty (comma-separated) |

`CLAUDE_MODEL` is deliberately a repository variable, not a hard-coded string:
model ids change, and the doctor should not need a code change to follow them.

## Repository layout

```
src/fleetpulse/     config.py  models.py  store.py  metrics.py  main.py
tests/              pytest suites + test_next_version.sh
ci_doctor/          client.py (GitHub + Anthropic), cli.py (comment building)
scripts/            next_version.sh
infra/terraform/    main.tf  iam.tf  variables.tf  outputs.tf  templates/user_data.sh.tftpl
k8s/                base/ + overlays/local + overlays/production
monitoring/         prometheus.yml, rules/fleetpulse.yml, grafana provisioning + dashboard
simulator/          simulate.py (drains batteries so the alert fires)
```

## Licence

MIT.
