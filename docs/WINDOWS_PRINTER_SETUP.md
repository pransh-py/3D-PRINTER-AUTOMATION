# Connect the Windows/WSL station to the actual AD5X

The current site is **http://127.0.0.1:3100/print**. Windows runs Next.js and Ubuntu WSL
runs the local station and Orca. The existing ZMOD/Moonraker adapter can send single-material
G-code and monitor the exact generated job filename. A supervised red PLA cube has now
completed successfully, including native preparation, live progress and heater shutdown.
The owner's LAN connection has now been saved and status tested (see the verification note
below). The owner's M1/Numakers PLA profile is now prepared; PETG retains its demo profile.
PLA is approved and website starts are enabled; PETG remains unapproved. The estimate rates remain INR 3/g
and INR 10/hour independently of printer activation.

The path is:

```text
Upload -> validate/configure -> Orca slice -> cost estimate
    -> operator confirms printer readiness -> G-code upload/start
    -> Moonraker live status -> completed or needs attention
```

For the previously described ZMOD installation, confirm the working Orca connection uses
**Octo/Klipper, Moonraker, printer IP:7125**, transferring G-code. ZMOD's current instructions
also say to disable "Use 3MF instead of G-code" in Orca 2.4.2 or newer. The stock FlashForge
transport is an explicit alternative, not an automatic fallback. Do not change printer
firmware or switch transport as part of an unverified connection attempt.

## 1. Identify the printer and test connectivity

Use the private IPv4 address shown by this exact printer or the owner's working Orca setup.
The computer and printer need LAN connectivity; guest Wi-Fi/client isolation can prevent it.
Do not scan a network to guess a printer. Keep its API key and access codes out of chat and
Git; the connection command prompts locally with hidden input if credentials are needed.

Stop the backend before changing its configuration. The frontend may remain running. The
backend holds a station lock while active and intentionally rejects concurrent configuration
changes. In a fresh PowerShell terminal at the repository root, open Ubuntu:

```powershell
wsl -d Ubuntu
```

Inside Ubuntu, enter the repository and define a helper for this configured runtime:

```bash
cd '/mnt/c/Users/Praanesh MB/Documents/ChatGPT/3d printer/3D-PRINTER-AUTOMATION'
runtime="$HOME/.local/share/printflow-runtime"
station() { "$runtime/venv/bin/python" tools/run_print_station.py --directory "$runtime/station" "$@"; }
station connect --transport moonraker --host PRINTER_PRIVATE_IPV4
station probe
```

Replace `PRINTER_PRIVATE_IPV4` with the actual address before running. `connect`/`probe`
only query status; they do not upload a file, heat or move the printer. An authorization or
unsupported-status error requires investigating the actual configuration. Do not disable
authentication or broaden trusted clients to bypass it. The adapter expects the Moonraker
job-queue API and an empty queue as well as Klipper status.

## 2. Replace software-test profiles with verified profiles

Export the printer owner's known-working machine, process and filament profiles from Orca,
including the working ZMOD start/end G-code. Resolve their inheritance using the installed
matching vendor resources and `tools/prepare_print_preset.py --help`. Current demo presets
are not evidence of printer calibration or of the physical plate.

Pin each prepared material manifest using absolute paths visible inside WSL:

```bash
station profile --material PLA --manifest /absolute/path/to/pla/presets.json
station profile --material PETG --manifest /absolute/path/to/petg/presets.json
station plate --help
```

Then use `station plate --type` with the actual supported plate name from that help output.
Review the 0.4 mm nozzle, temperatures, motion/start/end code and selected layer heights with
the owner. A profile, plate or slicer change revokes physical approvals.

## 3. Commission the loaded material and ZMOD start behavior

Check the actual IFS spool, filament material and the colour registered in ZMOD's COLOR menu.
Standard Moonraker status does not prove the physical spool colour. Map only values that
have been visually checked. For example, only if red PLA really occupies slot 1 with this
registered colour:

```bash
station map --material PLA --colour red --slot 1 --hex '#FF0000'
```

Review the installed ZMOD version's file scanning, automatic colour matching and silent-start
behavior. The existing commissioning command describes `SCAN_FILE_COLORS=1`,
`AUTO_ASSIGN_COLORS=30` and `SILENT=1`; it only records a review and does not change those
printer settings. Confirm the intended behavior with a known-good small Orca print under
supervision first. No purge, screen, firmware or other printer setting is changed automatically.

After profile/plate review and a supervised successful check, record the approvals locally:

```bash
station approve-profile --material PLA
station approve-zmod
```

Approve PETG separately when its physical setup has also been verified. These commands do
not themselves start a print and deliberately require typed confirmations.

## 4. Enable one supervised website print

Keep the Windows frontend running in station mode. Start the backend with:

```bash
station run --api-only --enable-printer
```

On `/print`, choose a small known model and commissioned material/colour, confirm the clear
bed, nozzle/spool and supervision, then use **Slice & print automatically**. This can heat
and move the printer. The station checks readiness again before sending, uploads the generated
single-tool G-code once and polls for its exact filename/status. Pause/cancel/stop using the
printer's screen. A lost connection or ambiguous start blocks further jobs for inspection;
the station does not automatically resend.

Each subsequent plate requires removing the completed part and a fresh readiness check.
The nine coasters are nine separate plates in our measured estimate; there is no automatic
part removal or unattended next-plate start. Keep the computer awake for slicing and monitoring.
The printer may continue a received job if the computer sleeps.

For future remote/public hosting, keep the printer connection on a local machine with outbound
job retrieval. This prototype's printer API remains loopback-only; port forwarding Moonraker
or publishing the local control endpoint is not part of this setup.

Sources checked October 20, 2026:
[ZMOD connection recommendations](https://wiki.zmod.link/Recommendations/#send-files-via-octoklipper-for-printing),
[ZMOD AD5X colour/start settings](https://github.com/ghzserg/zmod/blob/main/docs/en/AD5X.md),
[Moonraker file upload](https://moonraker.readthedocs.io/en/latest/external_api/file_manager/#file-upload),
[Moonraker job queue](https://moonraker.readthedocs.io/en/latest/external_api/job_queue/).

## Actual read-only connection verified — October 20

The owner supplied the printer's exact private LAN address. Both Windows and the Ubuntu WSL
backend received HTTP 200 JSON from Moonraker on port 7125. The adapter's complete status
sequence succeeded: Klipper ready, empty job queue, normalized print state ready, progress
zero and no reported error. The software version field was `?`; stock firmware and installed
ZMOD versions are therefore still unknown. These queries do not prove nozzle, plate or IFS
spool identity.

The regular `connect` command saved the address using the already-configured trusted LAN
access, with no API key supplied and no authentication setting changed. The backend was
restarted in slicing-only mode. The website's printer-status response now reports connected
and ready, while `enabled` remains false and both material profile approvals remain false.
No file upload to the printer, print start, heating, movement, firmware change, spool change
or physical approval was performed. The sanitized address/status evidence is kept in ignored
`.local/preview/ad5x-connected-status.json`.

The owner has since confirmed a 0.4 mm nozzle, 220 × 220 × 220 mm build volume, Textured PEI
plate, white PLA in slot 1, black PLA in slot 2 and red PLA in slot 3. A read-only query of
the installed `zmod_color` object returned matching colour registrations with exact hex
values `#FFFFFF`, `#161616`, and `#F72224`. These are the values to use when recording the
local slot mappings; preview colours alone are not the physical colour registry.

This printer exposes a ZMOD-specific status extension in addition to standard Moonraker.
Its current readings report `ifs=false`, `display=true`, and `hasFilament=false` for all
four slots. Those readings do not independently confirm the owner's physically loaded spools;
they require interpretation against the installed native-screen/IFS configuration before
physical commissioning. Slot 4 is also registered as white, so verify the intended automatic
matching behavior rather than assuming the local slot mapping forces a spool selection.
The saved global settings currently report scanning enabled, silent mode enabled and
`AUTO_ASSIGN_COLORS=2`, not the stricter reviewed matching mode described above. No macro or
printer setting was executed/changed by these read-only queries. The sanitized setup response
is saved in ignored `.local/preview/ad5x-setup-status.json`.

The owner has now supplied the Orca machine/process/PLA bundle described below. Supervised
ZMOD start/colour commissioning remains pending before enabling the first physical print.

The local station now records the three owner-confirmed PLA mappings using the exact
registered colours above, and retains the owner-confirmed Textured PEI plate selection.
The backend was restarted without `--enable-printer`; material approvals and ZMOD start
review remain false. These configuration changes do not load a spool or alter the printer.

To supply the working settings, use Orca's
[Export Preset Bundle](https://github.com/OrcaSlicer/OrcaSlicer/wiki/import_export#export-preset-bundle)
and choose **Printer config bundle**, which exports the printer with its related process and
filament presets as an `.orca_printer` file. Supply the profile settings with connection keys
removed. A working project 3MF can also preserve printer, filament and process settings;
review it before treating it as an approved station profile.

## Owner M1 bundle imported — October 20

The supplied archive contains `Flashforge AD5X 0.4 nozzle - M1`, the custom 0.20 mm process
and `Numakers PLA`. Its original SHA-256 is
`db90047bc8ae245e4dd1e7754033406f618283d5be1e965f1e2b02484b2d44ad`.
It was checked as bounded JSON data and preserved privately. No archived instructions or
machine code were executed. The named inherited profiles were resolved from the installed
official Orca 2.4.2 Flashforge resources; the export's version metadata is `2.3.2.60`.

`tools/prepare_print_preset.py` now accepts user exports that omit the profile type and
produces complete standalone profiles. For Orca CLI identity resolution, compiled User
metadata becomes system metadata after all settings have been materialized. Compatibility
retains the declared base restriction and adds only its explicitly named M1 child. Unresolved
inheritance, missing parents and unrelated incompatible printers remain rejected. The source
archive and explicit print settings, including start/end code, remain unchanged.

The private prepared PLA manifest is:

```text
/home/praanesh_mb/.local/share/printflow-runtime/profiles/owner-m1-pla-standalone/presets.json
```

Its combined profile SHA-256 is
`0f2ce5eba564ce632f72749d59432b266feced2f5a6c8c5e95e9b656914173bd`.
Use the ordinary `station profile --material PLA --manifest ...` command with that path to
pin it. This revokes physical approval; it does not enable the printer. The station's
selected Textured PEI plate and per-job options still apply. The profile's filament-cost
field does not replace the confirmed selling rates.

Isolated real-Orca tests passed at 0.20, 0.15 and 0.10 mm for a 20 mm cube, 20% infill,
one copy and supports off. The resulting owner start/end commands were preserved. The
output contains no explicit `G28` or blocking `M109`. Verify how this installed ZMOD
workflow homes and waits for nozzle temperature before physically approving this profile;
do not add guessed macros. The slot/native-screen observations above also still require
commissioning. No physical test or printer-setting change has been performed.

## Supervised cube commissioning — October 20

The owner subsequently requested the test and website activation, and explicitly confirmed
the clear installed bed, ready red PLA in slot 3 and someone beside the printer able to stop
it. A non-moving `GET_ZCOLOR SILENT=1` refresh confirmed IFS is active. The earlier false
value was cached; native-screen `hasFilament=false` values from the general object still do
not override the owner's physical confirmation or the native colour response.

Read-only inspection found the installed native-screen `_PRINT_FILE` and related macros.
The ZMOD Moonraker fork routes `/printer/print/start` and upload-with-print through that
native preparation path. The actual test log confirms `_PRINT_FILE`, native-screen start,
MD5 checking and `T0 -> 3: PLA/red`. The native sequence homes and heats before executing
the owner's file. No start/end G-code, screen mode, temperature profile or purge setting
was changed. ZMOD's own output reports USB version 1.7.3 and updated version 1.7.3-83;
Klipper's version field still reports `?`.

Only the documented `AUTO_ASSIGN_COLORS` setting was changed from 2 to 30 to abort uncertain
silent colour matches. Scanning and silent start remain 1; native screen remains on.

The one-time operator commissioning action sent the checksum-reviewed cube while ordinary
website starts stayed disabled. Its durable one-send intent is in private WSL runtime
`commissioning/red-cube-one-send-intent.json`; the script refuses an existing intent and
does not retry. The existing station journal tracks its exact filename and live progress:

```text
pf_a0a97a43abba4f148945a66b83689b6a_52ef211bdfa2.gcode
```

The G-code SHA-256 is `5a962ab0346be0986ff5ae1b5e3f3d147d35b7d41fe7a1cd76ae0ecefdc54b05`.
Settings are a 20 mm cube, PLA red, 0.20 mm, 20% infill, one copy and supports off.
The source upload remains recorded as slicing-only; the separate owner-authorized
commissioning action is explicitly recorded on that job without rewriting its options,
estimate or artifacts. Telemetry is in ignored `.local/preview/commissioning-cube-telemetry.json`.
Do not treat upload acceptance or heating alone as completed physical commissioning.

The printer subsequently reported the exact file as `printing`, increasing file position
and filament usage, with slot 3 active. The owner visually confirmed that the first layer
is red, adheres normally and moves smoothly without dragging. The cube then reached 100%
with exact matching completion status, 737.56 seconds of reported print duration and
1,334.90 mm of commanded filament use. Preparation time is additional to that duration.

The native finish sequence briefly retains the bed target while finishing, then turns off
both heaters and clears the SD filename/state. That shutdown was verified read-only; the
owner's profile was not changed and no separate heater-off command was executed. Completion
evidence was saved before the native reset, and the station's completed activity record
survives the printer returning to standby. The result is in ignored
`.local/preview/commissioning-cube-result.json`. A nonfatal `cell_tare` serial diagnostic
appeared during native preparation; probing continued and the print completed without a
reported print-state error. No firmware change was made to address that diagnostic.

After completion, the normal `approve-profile --material PLA` and `approve-zmod` commands
recorded review. The backend was restarted with:

```powershell
wsl -d Ubuntu --exec /home/praanesh_mb/.local/share/printflow-runtime/venv/bin/python -u tools/run_print_station.py --directory /home/praanesh_mb/.local/share/printflow-runtime/station run --api-only --enable-printer
```

The website now offers **Slice & print automatically** for the configured PLA colours.
PETG remains slicing-only. Remove the completed cube after the plate cools, clear the bed,
and make a fresh readiness confirmation before the next print. Existing estimates do not
start on activation. Pause/cancel on the printer's screen.

Post-activation requests through the website proxy confirmed `enabled=true`, PLA approved,
PETG unapproved and the completed test retained. A PLA print without readiness returned 422;
an unapproved PETG print returned 409. Neither created a job or sent a printer command.
Both heater targets were zero and the printer was idle. Sanitized verification is in ignored
`.local/preview/printing-enabled-verification.json`. Browser click-through verification
remains unavailable because of the saved origin permission denial; this test did not change it.
