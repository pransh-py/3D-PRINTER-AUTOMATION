# PrintFlow — local 3D print station

Current priority: **upload → configure → slice → automatically start one AD5X print**.
No account, cart, payment, Docker, PostgreSQL or Redis is needed for this local path.
The existing business site is preserved separately; it is not the printer-control UI.

On the configured Windows computer, the site and WSL backend use
**http://127.0.0.1:3100/print**. See [Windows local testing](docs/WINDOWS_LOCAL_TESTING.md)
for restart commands, profile details and verified upload/slicing results.
The local page now calculates estimates from actual slicing at the confirmed rates of
**INR 3/g filament + INR 10/hour printing**, with a separate material/time breakdown.

On this configured Mac, start:

```sh
.venv313/bin/python tools/run_print_station.py run
```

Open [the print station](http://127.0.0.1:3102/print). This defaults to **slicing only**.
STL/OBJ, real previews, mm/inches, X/Y rotation, 0.1/0.15/0.2 mm layers, PLA/PETG colours,
infill, supports and 1–10 copies on one plate are supported. Time and grams come from Orca.
The local configuration, models, journal and artifacts live privately in `.local/print-station`.

Physical starts require the printer's actual connection, reviewed profiles, build plate,
spool mapping and a per-job bed-clear/supervision confirmation. The friend's AD5X has ZMOD;
Moonraker/G-code is the prepared primary integration. **Actual printer operation is not yet
verified.** The station runs on Mac/Linux; it can talk directly to the printer on the same LAN,
so the Windows computer does not need a new service. See [the visit steps](docs/VISIT_PREFLIGHT.md).

For a fresh setup, `tools/run_print_station.py --help` lists configuration commands. Prepare
standalone profiles using `tools/prepare_print_preset.py`; initialize with `init --slicer
/absolute/OrcaSlicer --version VERSION --pla-manifest /absolute/presets.json`, then explicitly
select the actual build plate with `plate --type`. Do not enable physical printing from demo profiles.

## Preserved business workflow (not required for local printing)

The earlier public ordering and operations platform is retained for future business work.

The repository is under active MVP development. Product and safety contracts live in
[`docs/`](docs/), the public web application lives in [`apps/web`](apps/web), and the API lives
in [`services/api`](services/api).

For the implemented local quotation-to-fulfilment workflow, isolated browser lab and remaining
launch gates, see [`docs/LOCAL_WORKFLOW.md`](docs/LOCAL_WORKFLOW.md). Razorpay and automatic
AD5X business-queue dispatch are disabled; lab prices and payment evidence are fictional.

## Prerequisites

- Node.js 24 or newer
- npm 11 or newer
- Python 3.13
- Docker with Compose for PostgreSQL, Redis, MinIO, and Mailpit

## Install

```sh
npm --prefix apps/web install
python3.13 -m venv .venv313
.venv313/bin/pip install -e 'services/api[dev]' -e 'services/worker[dev]'
```

## Today's private local setup

This starts the real API, Redis worker, PostgreSQL, local SMTP and frontend, not the seeded
browser fixture. It uses dedicated Docker volumes and private files under ignored `.local/service`.
Existing databases and volumes are not replaced. Run from the repository root:

```sh
.venv313/bin/python tools/local_service.py init
.venv313/bin/python tools/local_service.py migrate
.venv313/bin/python tools/local_service.py owner --email YOUR_EMAIL --name "Business Owner"
.venv313/bin/python tools/local_service.py run all
```

The owner command requests a password interactively. Complete normal sign-in and MFA setup.
Open **http://127.0.0.1:3100**; local verification/reset emails appear at
**http://127.0.0.1:58025**. API readiness is on port 8011. Stop the launcher with Ctrl+C;
its own processes stop, while your database/files remain. `tools/local_service.py check` reports
configuration without exposing secrets. Never publish the private configuration or access files.

The form offers only priced, pinned slicer presets. Configure your actual reviewed profiles
and activate your approved rate card before taking orders; a new installation deliberately has
no invented catalogue or selling prices. See [the visit checklist](docs/VISIT_PREFLIGHT.md).
STL/OBJ models have an interactive browser preview; measured slicing drives automatic estimates.
The owner still issues the final quotation. Razorpay code is ready for test credentials but is
disabled until configured. AD5X handoff is manual and supervised, not automatic printer control.

This filesystem backend is intentionally single-machine/loopback-only, never staging or production.

## S3-based development alternative

Start the available pinned development dependencies:

```sh
docker compose up -d postgres redis mailpit
```

This starts PostgreSQL, Redis and Mailpit. **The older S3 setup remains blocked:**
the pinned MinIO image no longer pulls from Docker Hub; the same official Quay tag returns
401. The [community repository](https://github.com/minio/minio) is archived and unmaintained.
An owner-approved, trusted local image or maintained S3-compatible replacement is required.
Do not silently use an unofficial mirror, accept a new licence, or replace existing storage
data. The S3 adapter remains unchanged; real S3 integration is not verified. The explicitly
approved private local-folder adapter above is the available single-machine alternative.

When an approved storage service is available, the existing configuration expects its S3 API
at `http://127.0.0.1:9000` and its console at `http://127.0.0.1:9001`; Mailpit is at
`http://127.0.0.1:8025`. The initialization container creates a non-public, versioned
`xxx-private-models` bucket with development-only browser CORS. Never reuse the committed
development credentials in staging or production.

API:

```sh
.venv313/bin/uvicorn xxx_api.main:app --app-dir services/api/src --reload --host 127.0.0.1 --port 8000
```

Web, in a separate terminal:

```sh
npm --prefix apps/web run dev
```

Analysis worker, in another terminal after migrations and the development services are ready:

```sh
.venv313/bin/xxx-worker
```

The development worker independently hashes and validates uploaded STL, 3MF, OBJ, and STEP
sources. It stops at `awaiting_profile` until the owner supplies reviewed AD5X machine, process,
and filament profiles; it does not fabricate print time, filament use, or price. Development uses
the credential-scrubbed subprocess mode. Production configuration must select the Bubblewrap
sandbox with absolute reviewed executable paths to add OS-level network and process isolation.

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

## Pricing configuration

The owner account page can create immutable draft INR rate cards and activate one version after
recent MFA. The repository does not seed prices, material rates, contingency, tax, or minimum
charges. Do not activate a production rate card until the owner has supplied and approved those
values. Estimate creation also remains blocked until a successful AD5X-profile-backed slice has
produced integer filament and duration metrics.

Money is stored and calculated in integer paise; browser forms accept rupees only as an input
convenience. See `docs/adr/0006-versioned-pricing-and-estimates.md` for the exact formula and
snapshot contract.

## Payment plan

Razorpay Standard Checkout is the approved primary path. Its disabled-by-default adapter creates
provider orders from accepted-quote amounts, validates signed callbacks/webhooks, reconciles the
captured payment, and creates the print-queue effect exactly once. Browser success state and
`payment.authorized` are not paid-order authority.

Manual UPI is a planned, unimplemented owner-issued fallback. Real verification/activation is
blocked until the owner supplies an onboarded Razorpay merchant account, approved test/live
credentials and webhook settings, capture/settlement ownership, and refund/cancellation policy.
See [`docs/adr/0007-razorpay-primary-payments.md`](docs/adr/0007-razorpay-primary-payments.md).

Workflow email has private delivery records, fenced retries and an owner Notifications view;
it is disabled by default. Setup, local proof, remaining software and release gates are in
[`docs/LOCAL_WORKFLOW.md`](docs/LOCAL_WORKFLOW.md). Fictional payments, comment-only G-code and
loopback SMTP acceptance are not production acceptance.

## Verify

```sh
.venv313/bin/ruff check services/api services/worker
.venv313/bin/mypy services/api/src services/worker/src
.venv313/bin/pytest services/api/tests services/worker/tests
npm --prefix apps/web run lint
npm --prefix apps/web run test
npm --prefix apps/web run typecheck
npm --prefix apps/web run build
```

## Development services

Authentication requires Redis for distributed rate limits and Mailpit for local
verification/reset email. Private model intake requires an approved private S3-compatible service.
The MinIO image in the current Compose definition is unavailable; see the storage gate above.
The root `compose.yaml` is the
single local-development definition and binds service ports to loopback only. Its credentials
must never be reused in production.

Mailpit's local inbox is available at `http://localhost:8025`. Production requires a real HTTPS
web URL, sender address, SMTP provider, private storage, and non-development credentials; the API
rejects development defaults in production mode.
