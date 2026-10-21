# OTPigeon delivery for PrintFlow

Delivery is adapted from [pransh-py/OTPigeon](https://github.com/pransh-py/OTPigeon/tree/313734d72e6f77513bce6d72fd4e4695f1cab62c),
commit `313734d72e6f77513bce6d72fd4e4695f1cab62c`. Only its WhatsApp Web delivery
architecture is reused. PrintFlow generates and verifies challenges in its own API/database.
There is no MongoDB dependency, public QR endpoint, sender-management API or console OTP mode.

## Pairing on this Mac

From the repository root, with the private key already prepared under `.local/otp-sender`:

```sh
OTP_SENDER_API_KEY_FILE="$PWD/.local/otp-sender/sender.key" \
OTP_SENDER_DATA_DIR="$PWD/.local/otp-sender/session" \
OTP_SENDER_BROWSER_EXECUTABLE="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
npm --prefix services/whatsapp-otp-sender start
```

Run that command **yourself in an interactive terminal**. In WhatsApp, choose Linked devices
and scan the private QR shown there. Do not share the QR, key, browser-session files or OTPs.
Keep this terminal running. `WhatsApp sender ready.` means the linked client is ready; it is
not evidence of a delivered OTP. Request the first code to your own phone through the website
and enter it yourself. Existing owner email/password plus authenticator MFA is unaffected.

The service uses installed Chrome, **not its normal browsing profile**. Its separate LocalAuth
state and HTML cache live in the mode-0700 session directory. The key file must be mode 0600.
It binds only to `127.0.0.1:3201`; `/ready` and `/send-otp` require the private server key.
`/health` reveals only process health. Never expose this port publicly or add a QR/status proxy.

## API configuration

The API needs `XXX_WHATSAPP_OTP_ENABLED=true`, `XXX_WHATSAPP_OTP_SENDER_URL=http://127.0.0.1:3201`
and `XXX_WHATSAPP_OTP_SENDER_API_KEY` loaded privately from the same key file. Never use a
`NEXT_PUBLIC_` variable. The existing local-service launcher reads its private configuration
instead of inherited `XXX_` variables; update that configuration locally when deliberately
activating it. A separate isolated phone preview is prepared during verification; existing
demo databases and printer configuration are not migrated or replaced automatically.

Apply API migration `0013_phone_identity` to a backed-up, intended database before starting
the new API. It preserves existing email identities and adds nullable email/password, unique
verified buyer phones and bounded challenge state. Do not run migrations against an unrelated
or production database. Downgrade is intentionally refused to preserve verified identities.

## Installation and checks

```sh
npm --prefix services/whatsapp-otp-sender ci --ignore-scripts
npm --prefix services/whatsapp-otp-sender test
```

Do not bypass npm's install-script approval policy. Browser download is neither needed nor
performed. `OTP_SENDER_BROWSER_EXECUTABLE` must be an absolute, executable installed Chrome
path. Chrome sandbox-disabling flags are not used. The sender's Node entry point is not a
production deployment: production API configuration rejects this local-only integration.

## Known dependency and delivery limits

The dependency audit is **not clean**. `basic-ftp` is patched to 6.2.3 through an exact override.
The remaining chain includes `extract-zip` 2.0.1, through Puppeteer's browser installer, with
[GHSA-jmr9-qjv8-65gv](https://github.com/advisories/GHSA-jmr9-qjv8-65gv) and
[GHSA-7pqw-9j4j-h8q3](https://github.com/advisories/GHSA-7pqw-9j4j-h8q3).
The affected archive-download/extraction path is not used: installation skips scripts and
runtime requires an installed browser. No proxy configuration or arbitrary archive URLs are
accepted. Revisit when the upstream client supports a patched Puppeteer chain or extract-zip
is fixed; do not silently force a Puppeteer major upgrade or downgrade OTPigeon dependencies.

This is unofficial WhatsApp Web automation, without delivery guarantees; the account may be
restricted and changes to WhatsApp Web can break it. Use a dedicated testing account for
acceptance. `sent:true` means the client accepted `sendMessage`, not a delivery/read receipt.
Real QR pairing and phone delivery must be confirmed by the owner, not inferred from unit tests.
Codes expire in five minutes, are one-use and never logged. Timeouts never retry a send.
WhatsApp order notifications and email/phone account merging are not implemented. Phone-only
buyers follow order updates in their dashboard; legacy email accounts remain separate.
