# xxx

Public 3D-printing ordering and operations platform for a Chennai business using a FlashForge AD5X.

The repository is in the foundation phase. Product and safety contracts live in [`docs/`](docs/), the public web application lives in [`apps/web`](apps/web), and the API lives in [`services/api`](services/api).

## Prerequisites

- Node.js 24 or newer
- npm 11 or newer
- Python 3.13
- Docker with Compose for PostgreSQL, Redis, MinIO, and Mailpit (optional until persistence work begins)

## Install

```sh
npm --prefix apps/web install
python3.13 -m venv .venv313
.venv313/bin/pip install -e 'services/api[dev]'
```

## Run locally

API:

```sh
.venv313/bin/uvicorn xxx_api.main:app --app-dir services/api/src --reload --host 127.0.0.1 --port 8000
```

Web, in a separate terminal:

```sh
npm --prefix apps/web run dev
```

The web application is available at `http://localhost:3000`. Next.js proxies browser
requests under `/api/v1` to `http://127.0.0.1:8000` by default so session cookies stay
same-origin. Set `API_INTERNAL_URL` for a different private API address. API health
endpoints are at `http://localhost:8000/health/live` and `/health/ready`.

## Database migrations

The API defaults to a local SQLite database for development. Apply reviewed migrations from the repository root with:

```sh
.venv313/bin/alembic -c services/api/alembic.ini upgrade head
```

Set `XXX_DATABASE_URL` to the deployment PostgreSQL URL before running the same command outside local development.

## Owner provisioning and MFA recovery

After migrations, provision the one business owner from a trusted deployment shell. The
password is requested interactively and is never accepted as a command-line option:

```sh
.venv313/bin/xxx-api provision-owner --email owner@example.com --display-name "Business Owner"
```

If the owner loses both the authenticator and every recovery code, use the deployment-only
recovery command. It verifies the current password, removes MFA, and revokes every owner
session before re-enrollment:

```sh
.venv313/bin/xxx-api reset-owner-mfa --email owner@example.com
```

Production also requires a distinct random `XXX_MFA_ENCRYPTION_SECRET` of at least 32 bytes.
It must not equal the JWT signing or token-hash secret.

## Verify

```sh
.venv313/bin/ruff check services/api
.venv313/bin/mypy services/api/src
.venv313/bin/pytest services/api/tests
npm --prefix apps/web run lint
npm --prefix apps/web run test
npm --prefix apps/web run typecheck
npm --prefix apps/web run build
```

## Development services

Authentication requires Redis for distributed rate limits and Mailpit for local verification/reset email. After Docker is installed:

```sh
docker compose -f infra/compose.yaml up -d
```

The compose file is for local development only. Its credentials must never be reused in production.

Mailpit's local inbox is available at `http://localhost:8025`. Production requires a real HTTPS web URL, sender address, and SMTP provider configuration; the API rejects the development defaults in production mode.
