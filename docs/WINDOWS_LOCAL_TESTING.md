# Local upload and slicing on Windows

The configured test page is **http://127.0.0.1:3100/print**. Next.js runs on Windows;
the FastAPI print station and real OrcaSlicer run in the existing Ubuntu WSL distribution.
No Docker, Redis, PostgreSQL, cloud deployment or physical printer is needed for this path.
For actual printer commissioning, follow [Windows printer setup](WINDOWS_PRINTER_SETUP.md).

After successful physical commissioning and recorded profile/start review, the backend
restart command may include `--enable-printer` to offer website printing. The command below
continues to be the slicing-only restart; restarting without that flag disables new website
starts. Enabling the service never prints an existing estimate by itself. Each new print
still requires the page's bed/nozzle/filament/supervision confirmation.

## Restart the configured services

Run these commands from the repository root in two PowerShell terminals, keeping both open.
If the services are already running, use the existing page instead of starting duplicates.

Backend:

```powershell
wsl -d Ubuntu --exec bash -lc 'exec "$HOME/.local/share/printflow-runtime/venv/bin/python" -u tools/run_print_station.py --directory "$HOME/.local/share/printflow-runtime/station" run --api-only'
```

Frontend:

```powershell
$env:PRINTFLOW_PRINT_STATION = '1'
npm --prefix apps/web run start -- --hostname 127.0.0.1 --port 3100
```

After frontend source changes, stop its process and rebuild before starting it again:

```powershell
$env:PRINTFLOW_PRINT_STATION = '1'
npm --prefix apps/web run build
```

The station-mode build enables the `/api/printer/*` proxy to loopback port 8123.
The private station configuration selects UI port 3100; the default for other installations
remains 3102. Host, exact origin and per-process submission-token checks remain enforced.
The `--directory` launcher argument keeps WSL state on the Linux filesystem, where its
0700 directories and 0600 configuration permissions are enforced.

## Installed runtime

Everything specific to the Linux runtime lives under
`~/.local/share/printflow-runtime` inside Ubuntu:

- Python 3.13.16 in `venv`, with the API/worker editable dependencies installed.
- [Official OrcaSlicer 2.4.2](https://github.com/OrcaSlicer/OrcaSlicer/releases/tag/v2.4.2),
  extracted from the Ubuntu 24.04 x86_64 AppImage into `orca-2.4.2`.
- Original resolved vendor AD5X 0.4 mm test profiles in `profiles/pla` and `profiles/petg`.
- Active owner M1/Numakers PLA profile in `profiles/owner-m1-pla-standalone` (see below).
- Private configuration, SQLite journal, original models and generated artifacts in `station`.

The AppImage SHA-256 was verified against the official release asset digest:
`d12fb8c8eac1aecd2dfb6377acd48f994f8fa439ed5292fa532dd82880f029fd`.
The station pins the actual `bin/orca-slicer` executable, not just its shell wrapper.
Ubuntu host libraries installed for Orca were `libopengl0`, `libglu1-mesa`,
`libwebkit2gtk-4.1-0`, `libmspack0`, `libwayland-server0`, `libsecret-1-0` and their dependencies.
The existing Unix CPU/file-size/process timeout limits and credential-free child environment
remain in use; this is a private local station, not a public hostile-file sandbox.

The initial demo profiles used Flashforge PLA Basic and PETG Pro, the vendor AD5X 0.20 mm
process, and Textured PEI as a software test selection. The owner subsequently confirmed
the physical plate and supplied the PLA profile below. The LAN printer is now configured
and status-tested. PLA was subsequently physically commissioned and approved, and the current
service runs with `--enable-printer`. PETG remains unapproved. The initial software-only
verification tables below describe the earlier state; current commissioning results follow.

## Verification, October 20

Requests were sent through the same Next.js `/api/printer` proxy used by the page. The real
validator and Orca produced 3MF/G-code downloads whose SHA-256 values matched the journal:

| Model/settings | Result | Orca filament estimate | Orca time estimate |
| --- | --- | --- | --- |
| 20 mm cube, PLA, 0.20 mm, 20% infill, one copy | Sliced | 4.00 g | 15m 26s |
| 20 mm cube, PETG, 0.15 mm, 20% infill, two copies | Sliced | 8.27 g | 32m 05s |
| One extracted coaster, PLA, 0.20 mm, 20% infill | Sliced | 30.85 g | 1h 27m 33s |

The supplied `minimal-cup-coasters.stl` was structurally valid but spanned
729.400 × 746.780 × 4.003 mm. Exact shared-vertex connectivity identified nine disconnected
coasters, each approximately 115 × 132 × 4 mm, spread across that layout. The complete layout
exceeds the AD5X's 220 × 220 × 220 mm envelope. Nine individual STL files and a ZIP were
written to ignored `.local/print-tests`; the original upload and all coordinates/scale were
preserved. `coaster-01.stl` passed the real upload/validate/slice/download flow after splitting.
The service does not automatically resize or create multiple plates.

Oversize failures now include measured dimensions and corrective guidance. The page warns
when preview dimensions exceed the build volume and blocks submission of that known-oversize
preview; server validation remains authoritative when a preview is unavailable. Old history
entries containing the raw build-volume error receive a readable explanation in the UI.

Focused station, validator-process, slicing and transform checks passed **31 tests**, with
one opt-in real-Orca-to-simulated-printer test skipped. TypeScript, ESLint with errors-only
output, configured Python lint/format checks and the station-mode production build passed.
No physical printer command was sent. Browser automation still cannot inspect this origin:
the browser tool reports a saved permission denial for `http://127.0.0.1:3100`. Click-through
and visual acceptance therefore remain unverified; the API flow above was actually executed.

## Slicing-based cost request, October 20

The owner requested an estimate from actual slicing. All nine extracted coasters were
sliced separately through the local website proxy using PLA, 0.20 mm layers, 20% infill,
one copy per plate and supports off. Combined Orca estimates are **251.46 g** and
**37,492 seconds (10h 24m 52s)** across nine plates. Every 3MF/G-code download was checked
against the journal SHA-256. Individual artifacts remain in ignored `.local/print-tests`.

Initially no owner rates had been supplied. An explicitly illustrative calculation using
INR 1,000/kg and INR 50/hour totaled INR 772.22 when each part's
components are rounded upward to paise with the existing pricing-v1 function. It excludes
setup/labour, failure allowance, finishing, tax and shipping. It does not establish or activate
an owner rate card. The historical example and assumptions remain in ignored
`.local/print-tests/slicing-and-example-cost.csv` and `.json`.

## Confirmed automatic estimates

The owner subsequently supplied **INR 3/g filament and INR 10/hour printing**. These rates
are configured for the local station and now produce material/time estimates after slicing.
Time is charged proportionally to seconds. The UI shows the rate and amount for each
component, the estimated total and the exclusion of additional services, tax and delivery.
No extra minimum or tax policy has been inferred.

Rates are set locally while the station is stopped:

```powershell
wsl -d Ubuntu --exec bash -lc '"$HOME/.local/share/printflow-runtime/venv/bin/python" tools/run_print_station.py --directory "$HOME/.local/share/printflow-runtime/station" rates --filament-per-gram 3 --printing-per-hour 10 --include-existing'
```

The optional `--include-existing` flag prices slices with measured metrics and no previous
estimate. It was used to estimate the eleven existing successful slices. Previous estimate
snapshots are preserved on rate changes. Every new successful slice stores its exact rates,
measured plate metrics, pricing-v1 calculation version, timestamp and component values in
the private journal. Quantity is already included in the slicer metrics and is not applied
again. The HTTP upload schema rejects client-supplied rates or estimates.

The nine-coaster collection now totals **INR 754.38 filament + INR 104.18 time = INR 858.56**,
summing the nine separately rounded estimates. The confirmed per-part report is
`.local/print-tests/slicing-cost-confirmed.csv` and `.json`. A new real upload of `coaster-01.stl`
independently produced 30.85 g, 5,253 seconds and **INR 107.15** (92.55 + 14.60), with both
artifact hashes verified. Printer activation remains disabled.

Focused station/pricing/slicing tests passed **39 cases**, with the opt-in real-Orca-to-simulated-
printer case skipped. Configured Python lint/format, TypeScript, ESLint errors-only checks and
the optimized station build passed. Browser visual/click-through acceptance remains blocked
by the previously documented saved origin permission.

One proxy edge case remains: a deliberately invalid options header accompanied by an already
streaming large body can surface as a Next.js `ECONNABORTED`/500 when FastAPI rejects it
before consuming the body. Invalid-header requests with no body return 422, and a real valid
936,884-byte upload completed normally. The invalid price override did not create a job or
change rates. This early-response proxy behavior was not changed by the pricing work.

## Owner M1 profile verification — October 20

The supplied Orca printer bundle is resolved and pinned for new PLA jobs. Source provenance,
profile identity handling and the outstanding physical commissioning checks are documented
in [Windows printer setup](WINDOWS_PRINTER_SETUP.md#owner-m1-bundle-imported--october-20).
The owner start/end G-code is preserved. Inherited values come from the installed official
Orca 2.4.2 resources; the original export metadata says `2.3.2.60`.

Story checked: selecting PLA on `/print` uploads a model to the local API, validates and
slices it with the owner profile, persists the measured price, and returns artifacts and
estimate data for the activity card. Isolated real-Orca results for a 20 mm cube, 20% infill,
one copy, supports off and Textured PEI are:

| Layer height | Filament | Duration | Filament cost | Time cost | Estimate |
| --- | --- | --- | --- | --- | --- |
| 0.20 mm | 4.00 g | 13m 04s | INR 12.00 | INR 2.18 | INR 14.18 |
| 0.15 mm | 4.06 g | 16m 59s | INR 12.18 | INR 2.84 | INR 15.02 |
| 0.10 mm | 4.07 g | 24m 27s | INR 12.21 | INR 4.08 | INR 16.29 |

| Boundary | Evidence |
| --- | --- |
| Browser interaction/rendering | Unverified: saved origin permission denial remains; no workaround attempted. |
| Client request contract | Source uses `/api/printer/jobs`, the matching options header and station token; no frontend change needed for this import. |
| Website proxy to API | Actual HTTP upload returned 202 and reached `sliced` through port 3100. |
| Validator, Orca and journal | Live cube produced 4,000 mg, 784 seconds and a persisted INR 14.18 estimate. |
| Artifact response | Downloaded 3MF and G-code SHA-256 values matched the journal; owner start/end code, M1/Numakers names and registered `#F72224` red metadata were present. |
| Previous history | Prior estimates and G-code hashes remained unchanged. |
| Physical printer | Read-only status is ready; starts disabled, material approvals false and ZMOD review false. No print was sent. |

The live red job's derived profile hash differs from isolated preview-only tests because
it uses the printer's registered red colour. It was independently checked against the
hash-pinned owner base plus the selected job settings. The final live result is saved in
ignored `.local/preview/owner-m1-live-verification.json`, with a reviewable local G-code at
`.local/preview/owner-profile-cube.gcode`. Isolated results and source audit are alongside it.

Profile preparation, profile validation, station and slicing tests passed **48 cases**, with
one opt-in real-Orca-to-simulated-printer case skipped. Focused Python lint/format checks
passed. Physical start behavior remains a separate supervised commissioning step.

## Physical test completed and website printing enabled — October 20

One supervised 20 mm red PLA cube completed at 100%, with exact filename matching and no
resend. The owner confirmed the red first layer and normal adhesion/motion. Native preparation
handled homing, warm-up and slot 3 selection. Reported file-print duration was 737.56 seconds;
startup preparation is additional. The native finish sequence then shut down both heaters
and cleared the selected SD file. The original start/end profile remains unchanged.

PLA profile review and ZMOD review were recorded using the regular CLI, then the backend
was restarted with `run --api-only --enable-printer`. PLA red/white/black mappings are now
offered for printing; only red slot 3 was physically tested. PETG remains slicing-only.
The ordinary restart command at the top intentionally omits `--enable-printer`; use the
enabled restart documented in [Windows printer setup](WINDOWS_PRINTER_SETUP.md) after review.

The proxy reports the completed test, enabled starts, PLA approval and an idle printer.
Non-printing boundary checks rejected missing readiness (422) and unapproved PETG (409)
without creating jobs or changing printer state. Both heater targets were zero. Result
and activation evidence are in ignored `.local/preview/commissioning-cube-result.json` and
`.local/preview/printing-enabled-verification.json`; full read-only telemetry is alongside.
No second physical print was sent. A fresh bed-clear confirmation is required for the next.

## Known native busy response — October 20

A subsequent owner-authorized coaster submission reached the ordinary website API, sliced
successfully and uploaded once. The native printer rejected its start as `Printer is Busy`.
Moonraker still returned upload/start acceptance because the ZMOD macro reported that native
error through console output. The current adapter does not parse this diagnostic; a matching
selected filename in standby can therefore leave the activity at `awaiting_start`.

Read-only checks confirmed zero file progress, zero filament use, inactive SD execution and
an empty queue. The explicitly rejected activity was marked failed locally to unblock the
form. No retry or second physical print was sent. Native-start error detection remains an
open integration issue; upload acceptance alone must not be treated as proof of printing.
The owner then requested that further print submissions be made personally through the UI.

## Trusted LAN website — October 20

The current PC's Wi-Fi address is `192.168.100.5`. Devices on the same trusted LAN can
open **http://192.168.100.5:3100/print** while this PC and both services are running.
The existing localhost website stays available. The LAN process binds only that Wi-Fi
address; the WSL backend still listens on `127.0.0.1:8123`. Existing enabled Node.js
Windows firewall rules permit inbound traffic. No router port forwarding was added.
If DHCP changes the PC address, restart both services with its new private IPv4 address.

To reproduce this setup, stop the station backend only when it has no active job.
From the repository root in a dedicated PowerShell terminal:

```powershell
wsl.exe -d Ubuntu --exec bash -lc 'exec "$HOME/.local/share/printflow-runtime/venv/bin/python" -u tools/run_print_station.py --directory "$HOME/.local/share/printflow-runtime/station" run --api-only --enable-printer --lan-host 192.168.100.5'
```

For the separate LAN frontend, use another terminal. Build before starting it; stop a
running LAN frontend before rebuilding its directory. The separate `.next-lan` output
keeps the existing localhost build intact:

```powershell
Set-Location apps/web
$env:PRINTFLOW_PRINT_STATION = '1'
$env:PRINTFLOW_LAN_WEB = '1'
npm run build
npm run start -- --hostname 192.168.100.5 --port 3100
```

`--lan-host` is an explicit runtime allowlist option, not a change to profile, printer
or rate configuration. Omit `--enable-printer` for slicing only. On a Linux installation,
the launcher can also start the frontend itself; optimized LAN mode needs a build made
with both frontend variables above. LAN access shares the existing operator controls
and job history with trusted devices; this station has no separate LAN user accounts.

The upload client uses native Web Crypto where available and a pinned SHA-256 fallback
for plain HTTP LAN origins. Upload IDs use secure random UUIDs in either case. Verification
passed 46 frontend tests, 40 focused station tests (one real-Orca test skipped), TypeScript,
targeted ESLint, configured Ruff checks and the optimized LAN build. HTTP GET checks on
both the LAN and localhost addresses returned 200 for `/print` and the proxied printer
status, with starts enabled, PLA approved, the printer ready and no active station jobs.
The same private journal remains in use. Evidence is in ignored
`.local/preview/lan-host-verification.json`. No print was submitted for these checks.
An independent-device network check and browser interaction remain unverified; the
previously saved browser-origin denial was respected.

## Customer-style live printer demonstration

The inline bed/nozzle/filament checkbox has been removed from the customer form.
In Review & print, `Get estimate` uploads and slices the chosen model without dispatch.
The estimated total appears in that same panel, followed by `Print for INR …` for
commissioned materials. That action asks for operator confirmation of the file,
price, material, colour and quantity. Cancel sends no start request. Changing the
model, units, rotation, material/colour, quality, infill, supports or quantity invalidates
the selected estimate. Starting uses its original prepared artifacts and saved price.

For the demonstration, refresh `/print`, upload your own STL/OBJ, choose settings, open
the review step and select `Get estimate`. Review the displayed total, then choose
`Print for INR …`. The operator confirms in the dialog. Follow activity through starting
and printing, and verify motion
at the printer. A completed estimate or accepted upload alone is not evidence of printing.

The refreshed LAN and localhost builds passed TypeScript, targeted ESLint and production
compilation. Both websites and the proxied status API respond, with PLA approved, the
printer ready and no active job. An isolated run of the current station pipeline against
the installed Orca and configured PLA profile produced a 20 mm cube at 4 g, 784 seconds
and INR 14.18. Its 3MF/G-code hashes matched, with all printer-driver access disabled.
Downloads of an existing cube's files through the LAN proxy also returned 200 and matched
the stored hashes. Evidence is in ignored `.local/preview/customer-demo-*.json`.
These checks submitted no job to the live website or printer. Browser click-through and
a new physical print are left to the owner's website test; the saved browser denial
was respected. The known native busy response above remains an integration limitation.

The estimate-first update passed 53 station tests, including checks for mismatched
prices, changed files/profiles/plate/mapping, disabled or unapproved printing, active-job
conflicts and duplicate/ambiguous starts. The opt-in test also passed with real Orca
and a loopback printer simulator: two 0.10 mm cubes produced 8.10 g and 1,898 seconds.
No upload occurred before price acceptance; exactly one G-code upload followed, preserving
the quoted file hashes and estimate. This used a disposable journal and simulated driver,
never the physical printer or live website's submission API.
