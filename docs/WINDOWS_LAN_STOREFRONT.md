# Buyer/owner storefront on the Windows LAN

## Free presentation queue

The presentation now uses `XXX_PRESENTATION_MODE=true` for API/worker and
`PRINTFLOW_PRESENTATION_MODE=1` for the web build and server. The web output is
`.next-presentation`. There is no checkout or paid-order transition in this mode;
commercial order/payment routes are not mounted and the worker skips payment
reconciliation and paid-order enqueueing. Existing commercial records are retained.

After slicing, buyers see reference cost and print duration and choose **Submit to
waiting list**. Submission also works from a previously sliced request after a page
refresh. Owners admit models at `/operations`; `/orders` shows the buyer's own queue.
An admission is not a physical start. A paired outbound service checks readiness,
then consumes a five-minute, single-use owner plate clearance for the FIFO head.
Each completed part must be removed before clearing the next job. Operator clearance
uses the existing recent-owner-MFA gate in Account & security.

The new `tools/run_presentation_station.py` shares the original exclusive station lock
and uses its reviewed AD5X machine/filament profiles, allowing only the existing layer,
infill and support variants. It verifies source artifact and profile hashes, rewrites
only the single-tool colour comment for the commissioned slot, and recomputes the ZMOD
checksum. Native start still explicitly maps T0 to white/black/red slots 4/2/3.
The service persists intent before sending, never retries an ambiguous physical start,
and reports printer telemetry back to the queue. Offline devices leave work queued.

For the current demo, the website is on `10.31.68.160:3100`, while the saved printer is
`192.168.100.200`. Connection must be established before actual printing; no simulated
completion or printer-readiness state is displayed as real hardware telemetry.

## Original storefront setup

The October 21 checkout is based on main `a022d9d`. The full storefront is separate
from the commissioned direct-print station. Its entry is `/`, with `/orders` for
buyers and `/operations` for the owner. In storefront mode, `/print` redirects to
`/get-a-quote`, and the native `/api/printer` proxy is absent.

This installation uses Windows Next.js and Ubuntu WSL for the real API, PostgreSQL,
Redis, private local model storage, and the Orca worker. Runtime secrets and state
are under `/home/praanesh_mb/.local/share/printflow-runtime/commerce-lan`, outside
the repository. The original station configuration, journal and approvals remain
unchanged. The storefront uses a dedicated `printflow_lan` database and Redis
database 6 with its own stream/group. Migrations through `0013_phone_identity`
were applied to this new database. No existing business database was migrated.

The current Wi-Fi address is `10.31.68.160`; it can change after reconnecting.
Private local storage remains disabled for public/staging/production origins.
The optional `storage_local_lan_origin` setting explicitly allows this one exact
RFC1918 HTTP origin alongside loopback. API, database, Redis, SMTP and WhatsApp
sender ports remain loopback-only. Keep session/Origin/CSRF validation enabled.
The existing secure UUID/hash helpers also support the storefront on LAN HTTP.

Build and start the web application from PowerShell at the repository root:

```powershell
$env:PRINTFLOW_LAN_WEB = '1'
$env:API_INTERNAL_URL = 'http://127.0.0.1:8011'
Remove-Item Env:PRINTFLOW_PRINT_STATION -ErrorAction SilentlyContinue
npm --prefix apps/web run build
npm --prefix apps/web run start -- --hostname 10.31.68.160 --port 3100
```

Both build and start use the same API target. This build uses `.next-lan`.
Do not rebuild its directory while the web process is running. Stop the web
process before changing the bound LAN address; update the private API origin
allowlist and `storage_local_lan_origin` to that same exact origin as well.
Only permit web-port access from the intended LAN. No router forwarding is needed.

The ignored helper `.local/preview/lan_storefront.py` supports `api`, `worker` and
`sender` for this configured WSL installation, using its private configuration.
It is a deployment artifact, not a portable installation command. The helper's
`configure` operation preserves an existing configuration; never reinitialize
state to change a network address. The ignored `start-lan-storefront.ps1` is the
prepared Windows web launcher. Keep the host awake and processes running.

The owner account uses the supplied identity. Its initial password is in the
ACL-protected local pairing directory, never Git. Sign in with **Email & password**
and enroll authenticator MFA normally before sensitive owner actions. Buyer
WhatsApp codes use the actual separately linked sender; no fixture codes or
fake delivered-code responses are enabled. Local SMTP is a private mailbox sink,
not external email delivery. Configure a real email provider before relying on
email verification/password-reset delivery to an inbox.

The storefront catalogue uses a private copy of the supplied M1 PLA bundle with
the confirmed Textured PEI plate. Its rate card retains INR 3/g and INR 10/hour,
with no added fee. Razorpay and commerce printer dispatch remain disabled; the
new commerce connector has not been physically commissioned. Hosting does not
activate payments or automatically send paid orders to the AD5X. The saved
printer address `192.168.100.200` was unreachable from this Wi-Fi network at setup.

The WhatsApp sender is installed under the private WSL `otp-sender` runtime and
uses an isolated Chrome profile. Its key and session remain private. The owner
explicitly requested a local QR image; the ignored pairing hook renders that
image into an ACL-protected local folder only, with no QR HTTP endpoint. Scan it
using WhatsApp **Linked devices**. A ready response confirms linking, not actual
message delivery. Request and enter a real code yourself through the website.

Verification: 67 web tests, TypeScript, optimized storefront build, source lint,
19 local-storage/configuration tests, and all four sender tests under WSL passed.
Direct HTTP checks confirmed API readiness. Automated frontend process launches
were rejected as “blocked by policy”, including loopback; the owner was given the
prepared launcher. The frontend subsequently became available on the exact LAN
address. HTTP checks through that frontend confirmed the home, sign-in, request,
buyer and owner pages, catalogue, owner login and owner dashboard. The native
station proxy returned 404 as expected in storefront mode. WhatsApp subsequently
linked and its authenticated sender readiness check returned true. A browser
click-through, real WhatsApp message delivery, payment or physical print is not
claimed by these checks. Sanitized evidence is in the ignored file
`.local/preview/lan-storefront-final-verification.json`.

The owner subsequently requested the `d826901` model configurator layout. The
customer page now reuses that station's styles and accordion layout, retaining
normal buyer/owner authentication and quotations. The private catalogue retains
the existing preset and adds 60 hash-pinned layer/infill/support variants through
`tools/expand_print_presets.py`. The API and worker were reloaded without changing
auth secrets, prices, the original station, or physical-dispatch flags.

The refreshed web build was prepared separately in `.next-verification` to avoid
rebuilding the live `.next-lan` directory. The ignored `restart-custom-ui.ps1`
switches this installation to that build using `PRINTFLOW_WEB_VERIFICATION=1`
and the same API target/LAN address; this flag selects a build directory only.
After the process switch, HTTP checks confirmed both the restored page and its
actual configurator JavaScript bundle. The catalogue exposes all 60 combinations.
Seventy web tests, the preset compilation test, TypeScript, lint and optimized
build passed. Two real Orca runs verified their chosen process fields and yielded
different measured mass/time. Browser click-through and a physical print were not
performed. Evidence is in `.local/preview/restored-ui-verification.json` and
`restored-ui-real-slicing.json`.
