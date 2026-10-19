# Printer integration visit

For the current **Windows + Ubuntu WSL setup on port 3100**, use
[Windows printer setup](WINDOWS_PRINTER_SETUP.md). The Mac commands below describe the
earlier machine; the commissioning sequence remains applicable. Current hardware status
must be verified on the actual printer.

## Current task: simple local automation, not the business workflow

Use **http://127.0.0.1:3102/print**, launched by:

```sh
.venv313/bin/python tools/run_print_station.py run
```

This Mac runs the web page, bounded model validation, real Orca and a private SQLite job
journal. It sends directly to the printer on the same LAN. No Windows service, public tunnel,
cloud account, checkout, PostgreSQL or Redis is required. The first release accepts STL/OBJ
only, one material/tool T0, 0.4 mm nozzle and at most one build plate; it never auto-queues the
next plate. Copies are arranged together on that plate. The owner must remove completed prints.

Your friend confirmed the AD5X has **ZMOD**, and Orca already sends and starts prints.
The supplied "2.3.2" is apparently the slicer version; record printer firmware and ZMOD version
separately. Do not upgrade firmware or change screen, purge or safety settings for this demo.

### At the printer, in order

1. Put this Mac and the AD5X on the same trusted LAN. Get its exact private IPv4 address;
   do not scan a network. In the friend's working Orca printer connection, inspect host type,
   port and printer agent. ZMOD recommends **Octo/Klipper → Moonraker, port 7125**, sending
   **G-code**, not 3MF. The built-in stock FlashForge transport is a separate explicit option,
   never an automatic fallback. Confirm the actual mode before choosing it.
2. Export the friend's known-working machine/process/filament profiles. Resolve inheritance
   with `tools/prepare_print_preset.py --help` against the correct installed vendor resources;
   preserve the ZMOD start/end code. Pin each prepared material using:

   ```sh
   .venv313/bin/python tools/run_print_station.py profile --material PLA --manifest /absolute/pla/presets.json
   .venv313/bin/python tools/run_print_station.py profile --material PETG --manifest /absolute/petg/presets.json
   .venv313/bin/python tools/run_print_station.py plate --type 'ACTUAL SUPPORTED PLATE TYPE'
   ```

   Choose one of the plate names shown by `plate --help`; do not paste the placeholder.
   Local tests used **Textured PEI Plate**, not a claim about the installed plate. Check nozzle,
   plate temperatures, speeds, walls, support behaviour and allowed layer heights against the
   friend's successful slicer setup. Changing a pinned profile, slicer or plate revokes approval.
3. Save credentials locally with hidden input, then run the read-only probe:

   ```sh
   .venv313/bin/python tools/run_print_station.py connect --transport moonraker --host PRIVATE_IP
   .venv313/bin/python tools/run_print_station.py probe
   ```

   Use an existing Moonraker API key if its access configuration requires it; do not disable
   authentication or broaden its trusted clients to work around a denial. No credentials in chat,
   screenshots, Git or URLs. No router port forwarding. The probe checks Klipper status and an
   empty Moonraker queue. An unsupported/missing API fails closed for on-site investigation.
4. In the ZMOD COLOR screen, visually match one loaded spool and its exact colour hex to an
   offered option. Standard Moonraker does **not** prove IFS colour/slot identity. For example,
   after verifying actual slot and hex (replace the sample values):

   ```sh
   .venv313/bin/python tools/run_print_station.py map --material PLA --colour red --slot 1 --hex '#FF0000'
   ```

   The stock transport can additionally check live IFS material/colour. ZMOD relies on reviewed
   automatic colour matching and fresh operator confirmation; it does not remotely force a spool.
5. Review ZMOD's existing single-material start behaviour with the owner. Its documentation
   describes `SCAN_FILE_COLORS=1`, `AUTO_ASSIGN_COLORS=30` (abort on problematic matching),
   and `SILENT=1` to avoid the colour dialog. These are **not automatically changed** by our
   code. Confirm against the installed version, preferably with the friend's known-good small
   Orca print first. Our exported G-code adds ZMOD colour metadata and an MD5 compatibility
   header; the station records SHA-256 separately. It does not rewrite heating/motion macros.
6. Only after actual profile/plate/spool review and supervised validation, record the approvals:

   ```sh
   .venv313/bin/python tools/run_print_station.py approve-profile --material PLA
   .venv313/bin/python tools/run_print_station.py approve-zmod
   .venv313/bin/python tools/run_print_station.py run --enable-printer
   ```

   Configuration commands do not print. Stop the station before editing configuration; restart
   afterwards. Open `/print`, upload a small known model and confirm the clear bed, correct
   nozzle/spool/mapping and supervision for this job. The **Slice & print automatically**
   button performs the sequence. Use the printer's screen to pause, cancel or stop.
7. Watch for the exact generated filename in live status. An upload acknowledgment is not
   printing, and progress alone is not completion. Record heating/printing/completed, correct
   material and colour, and the actual result. A timeout/disconnect or restart after sending
   becomes **needs attention**, blocks another job and is never automatically resent. Inspect
   and resolve at the printer, clear any queued jobs and the bed, then acknowledge locally.

The laptop is the current station: closing/sleeping it interrupts slicing/monitoring. A printer
may continue a job it already received. Keep the laptop awake and the physical test supervised.
Mac/Linux operation is verified; the resource-limited launcher is not Windows-compatible.

Protocol sources: [ZMOD recommendations](https://wiki.zmod.link/Recommendations/),
[ZMOD AD5X](https://github.com/ghzserg/zmod/blob/main/docs/en/AD5X.md),
[ZMOD preprocessor](https://github.com/ghzserg/zmod_preprocess/blob/main/zmod-preprocess.py),
[Moonraker upload](https://moonraker.readthedocs.io/en/latest/external_api/file_manager/#file-upload),
[Moonraker queue](https://moonraker.readthedocs.io/en/latest/external_api/job_queue/),
[Orca 2.4.2 stock uploader](https://github.com/OrcaSlicer/OrcaSlicer/blob/v2.4.2/src/slic3r/Utils/Flashforge.cpp).

## Earlier business workflow — reference only, not required for today's print

The website can automate intake, slicing, pricing, quotation, payment verification and queueing.
The installed bridge currently downloads approved artifacts for an owner-operated print. It
does not send, start, pause or stop a printer. Do not present those actions as implemented.

## Bring and confirm

The printer is confirmed as FlashForge AD5X. Record its firmware, Windows version and installed
Orca-Flashforge version. Robu.in is only the ordering reference, not a printer driver. Keep serial numbers,
printer IDs, access codes and gateway secrets out of screenshots, Git and chat.

The owner must provide available material/colour combinations, approved slicing profiles and
rates. Nozzle size, layer height, infill, support and wall settings are taken from those profiles.
Colour remains a physical spool-loading check, not automatic IFS mapping. Do not offer arbitrary
material/quality combinations or copy Robu's material stock into this business.

## Configure the software

1. Use a fresh local database or back up the intended business database before migrating. Never
   remove volumes or replace existing customer data. The current migration is `0012_model_review_audit`.
2. Configure a private storage backend and verify that a real uploaded model is stored privately.
   The previous browser fixture is not an upload integration test.
3. Install the reviewed slicer on the Mac/Linux worker. The current resource-limited launcher is
   Unix-specific; do not assume the Windows handoff client also runs the analysis worker.
4. Export complete standalone `machine.json`, `process.json` and `filament.json` profiles. If an
   export contains `inherits`, resolve it against the exact installed vendor profile version
   before approval. Do not remove `inherits` without supplying the inherited settings.
5. Put the preset manifest outside Git and set its absolute path as `XXX_ANALYSIS_PRESET_MANIFEST`.
   Every entry contains `code`, `label`, `materialCode`, `colours`, `profileDirectory` and
   `profileSha256`. Hash each filename followed by a NUL byte and its exact contents, in this
   order: machine.json, process.json, filament.json. The worker and API share this rule.
6. Configure `XXX_ANALYSIS_SLICER_COMMAND`, `XXX_ANALYSIS_SLICER_VERSION` and
   `XXX_ANALYSIS_SLICER_SHA256`. Set an analysis lease long enough for validation plus every
   configured per-model slicing timeout. The owner activates an explicit rate card through MFA.
7. Restart the API and worker. `/api/v1/print-presets` should return only configured, priced
   offerings with no filesystem paths. Confirm the form shows those exact settings.

For today's dedicated local setup, use the commands in the README. An inheritance-resolution
utility is available; select the exact vendor resource folder and the three intended profiles:

```sh
.venv313/bin/python tools/prepare_print_preset.py --help
.venv313/bin/python tools/local_service.py profiles \
  --manifest /absolute/reviewed-preset/presets.json \
  --slicer /absolute/OrcaSlicer --version VERIFIED_VERSION
.venv313/bin/python tools/local_service.py check
```

The preparation utility creates a new directory and never changes vendor profiles. Review its
resolved settings before using them. These files can contain machine-specific information;
keep them private. A preset's material code must match an active rate-card material code.
The website collects preset-bound nozzle, quality, infill/support/wall assumptions rather than
offering arbitrary combinations the printer has never been calibrated to use.

## Prove one order

Upload a small, non-sensitive known model as a buyer. Check its measured dimensions, browser
preview, grams and time. A sliced PNG is optional and is not emitted by every Orca profile.
The worker calculates the first estimate automatically. The owner issues a quotation, the buyer checks the print specification
and accepts it. Without real Razorpay test keys, stop at payment pending; never invent a paid flag.

In Operations, inspect the private validated source before approval. STL/OBJ up to 16 MiB can be
viewed in-browser; other validated formats can be downloaded to the reviewed local CAD/slicer tool.
The browser preview is a view, not a printable-artifact approval or geometry-repair service.

For test checkout, configure a `rzp_test_` Key ID, Key Secret, distinct webhook secret and Checkout
name locally, and enable test mode. Use Razorpay's test flow only. The verified browser callback
does not itself mark an order paid: server-side reconciliation must confirm captured payment.
Localhost can use reconciliation without exposing a webhook publicly. A public tunnel is a
separate security/exposure decision. No live funds are authorized by this procedure.

Once payment is confirmed, verify exactly one queued job. Pair the Windows bridge from the owner
workspace, download the authorized artifact, and compare it with the same model/settings exported
by the print station:

```sh
.venv313/bin/python tools/compare_slice.py /absolute/worker.gcode /absolute/station.gcode
```

Do not substitute a newly sliced file for the authorized artifact and claim the hashes still
match. Confirm whether the printer accepts that artifact through the official manual send/USB
flow. After a clear bed, loaded filament, nozzle, safe area and artifact review, the owner starts
one supervised print. Record actual completion, QA and pickup/delivery separately.

## Direct automation acceptance gate

First observe the verified tool's read-only identity/status response on this exact firmware.
Then inspect its supported upload/start contract and artifact format. Only after that should an
adapter be implemented and tested locally with owner authorization. Verify no duplicate start
after retries/restarts, no start while busy or errored, correct colour/slot selection, and an
unambiguous result after a connection loss. Keep the manual handoff available. A heartbeat alone
does not prove the printer is idle or ready. Do not open the printer's LAN ports to the internet.

Today's API is bound to loopback. Do not weaken the bridge's HTTPS requirement to reach it from
Windows. Use an owner-approved authenticated SSH port forward to the Mac, or a properly secured
HTTPS deployment, before pairing a remote station. Neither SSH access nor a public tunnel is
enabled by these scripts. If neither is available, use the authenticated owner artifact download
and transfer it manually; this is not unattended automation.

Never queue a new job automatically after completion: someone must remove the part and prepare
the bed. Test checkout, local software operation, physical printing and public launch are four
different acceptance results.
