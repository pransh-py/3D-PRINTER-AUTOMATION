# PrintFlow — local 3D print station

Upload a model, configure the plate, slice it with OrcaSlicer, review the cost estimate,
and optionally start one supervised FlashForge AD5X print from the website.
The local print station requires no account, cart, payment service, Docker, PostgreSQL or Redis.

## What works

- STL/OBJ uploads with a 3D preview, millimetres/inches and X/Y rotation.
- PLA/PETG selections, 0.1/0.15/0.2 mm layers, infill, supports and 1–10 copies on one plate.
- Real OrcaSlicer filament/time measurements and downloadable G-code and sliced 3MF files.
- Estimates at the owner's confirmed **INR 3/g filament + INR 10/hour printing**, shown
  separately and saved with the rates used. These exclude additional services, tax and delivery.
- Persistent job activity, one active job at a time, and explicit readiness confirmation
  before each physical print. A downloaded or sliced file does not start printing by itself.
- Optional access from other trusted devices on the same LAN.

## Current Windows installation

Next.js runs on Windows. FastAPI and **OrcaSlicer 2.4.2** run inside Ubuntu WSL.
The backend stays on `127.0.0.1:8123`; the website proxies `/api/printer/*` to it.

| Access | Print workspace |
| --- | --- |
| On the host PC | [http://127.0.0.1:3100/print](http://127.0.0.1:3100/print) |
| On the same Wi-Fi/LAN | [http://192.168.100.5:3100/print](http://192.168.100.5:3100/print) |

Keep the host PC awake and both services running. The LAN address is specific to this
installation and can change with DHCP. LAN access shares the operator controls and job
history with trusted devices; there are no separate LAN user accounts. Internet hosting
and router port forwarding are not configured.

The commissioned printer has a **0.4 mm nozzle, 220 × 220 × 220 mm build volume and
Textured PEI plate**. PLA white/black/red map to IFS slots 1/2/3. One supervised red PLA
cube completed successfully through the ZMOD/Moonraker integration. PLA website printing
is enabled on the configured installation; PETG remains slicing-only pending profile review.
The active PLA profiles were resolved from the owner's Orca M1 bundle. New clones do not
include private printer credentials, profile exports, uploaded models or the job journal.

**Known issue:** a native ZMOD `Printer is Busy` rejection can leave activity at
`awaiting_start`, because Moonraker may acknowledge the upload before the native start
fails. Upload acceptance is not proof that the printer started. Inspect the printer before
any retry; see [the observed failure](docs/WINDOWS_LOCAL_TESTING.md#known-native-busy-response--october-20).

## Run on the LAN

These commands use the already-configured Windows/WSL runtime. For a new installation,
follow the setup links below first. Use existing services if they are running; stop a
station only when no job is active. Run from the repository root in separate PowerShell terminals.

Backend, allowing this PC's exact private LAN address:

```powershell
wsl.exe -d Ubuntu --exec bash -lc 'exec "$HOME/.local/share/printflow-runtime/venv/bin/python" -u tools/run_print_station.py --directory "$HOME/.local/share/printflow-runtime/station" run --api-only --lan-host 192.168.100.5 --enable-printer'
```

Omit `--enable-printer` for slicing only. Physical printing requires reviewed profiles,
the actual plate and spool mapping, and fresh bed-clear/supervision confirmation in the UI.

LAN frontend (stop its process before rebuilding):

```powershell
$env:PRINTFLOW_PRINT_STATION = '1'
$env:PRINTFLOW_LAN_WEB = '1'
npm --prefix apps/web run build
npm --prefix apps/web run start -- --hostname 192.168.100.5 --port 3100
```

The LAN frontend uses `.next-lan`, keeping the existing localhost build separate.
Both services must use the same web port and LAN address. Replace `192.168.100.5` in both
commands if the PC's address changes. Allow Node.js through the firewall only for the
trusted LAN. No printer command is sent merely by starting these services.

## Setup and operation

The station requires Node.js 24+, npm 11+, Python 3.13 and a compatible OrcaSlicer CLI.
The backend uses Unix process/file protections; run it under Linux or Ubuntu WSL on Windows.

- [Windows runtime, localhost/LAN restart commands and verification](docs/WINDOWS_LOCAL_TESTING.md)
- [Printer connection, owner profile import and commissioning](docs/WINDOWS_PRINTER_SETUP.md)
- [Architecture](docs/ARCHITECTURE.md) and [security boundaries](docs/SECURITY.md)

`tools/run_print_station.py --help` lists configuration commands. Prepare standalone
profiles with `tools/prepare_print_preset.py`, initialize with `init --slicer
/absolute/OrcaSlicer --version VERSION --pla-manifest /absolute/presets.json`, and select
the actual build plate with `plate --type`. Starts default to disabled. Do not commission
demo profiles for physical printing. No repository skill package is required to run the app.

On a configured Linux installation, `.venv313/bin/python tools/run_print_station.py run`
starts the local slicing-only station at [http://127.0.0.1:3102/print](http://127.0.0.1:3102/print)
by default. Configuration and job files default to ignored `.local/print-station`; the
Windows runtime instead keeps its private state in the WSL filesystem as documented above.

## Preserved business workflow (not required for local printing)

The earlier public ordering and operations platform is retained for future business work.

The repository is under active MVP development. Product and safety contracts live in
[`docs/`](docs/), the public web application lives in [`apps/web`](apps/web), and the API lives
in [`services/api`](services/api).

For the implemented local quotation-to-fulfilment workflow, isolated browser lab and remaining
launch gates, see [`docs/LOCAL_WORKFLOW.md`](docs/LOCAL_WORKFLOW.md). Razorpay and automatic
AD5X business-queue dispatch are disabled; lab prices and payment evidence are fictional.

## Business workflow prerequisites

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

## Private business workflow setup

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
