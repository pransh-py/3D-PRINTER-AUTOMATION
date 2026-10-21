// Single local sender, derived from OTPigeon's LocalAuth/Client delivery architecture.
const fs = require('node:fs');
const path = require('node:path');
const { createApp } = require('./app');

function loadConfig(env) {
  const keyFile = env.OTP_SENDER_API_KEY_FILE;
  const dataDir = env.OTP_SENDER_DATA_DIR;
  const browser = env.OTP_SENDER_BROWSER_EXECUTABLE;
  if (!keyFile || !path.isAbsolute(keyFile)) throw new Error('An absolute private key-file path is required.');
  const keyStat = fs.lstatSync(keyFile);
  if (!keyStat.isFile() || keyStat.isSymbolicLink() || (keyStat.mode & 0o077)) throw new Error('The sender key file must be private (mode 600).');
  const apiKey = fs.readFileSync(keyFile, 'utf8').trim();
  if (Buffer.byteLength(apiKey) < 32) throw new Error('The sender key must contain at least 32 bytes.');
  if (!dataDir || !path.isAbsolute(dataDir)) throw new Error('An absolute private session directory is required.');
  if (fs.existsSync(dataDir)) {
    const stat = fs.lstatSync(dataDir);
    if (!stat.isDirectory() || stat.isSymbolicLink() || (stat.mode & 0o077)) throw new Error('The session directory must be private (mode 700).');
  }
  if (!browser || !path.isAbsolute(browser) || !fs.statSync(browser).isFile()) throw new Error('An absolute installed Chrome executable is required.');
  fs.accessSync(browser, fs.constants.X_OK);
  const port = Number(env.OTP_SENDER_PORT || 3201);
  if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('Invalid loopback sender port.');
  return { apiKey, dataDir, browser, port };
}

async function start() {
  const config = loadConfig(process.env);
  fs.mkdirSync(config.dataDir, { recursive: true, mode: 0o700 });
  process.chdir(config.dataDir); // Also keeps WhatsApp Web's HTML cache inside private storage.
  const { Client, LocalAuth } = require('whatsapp-web.js');
  const qrcode = require('qrcode-terminal');
  const client = new Client({
    authStrategy: new LocalAuth({ clientId: 'xxx-otp', dataPath: config.dataDir }),
    puppeteer: { headless: true, executablePath: config.browser },
  });
  let ready = false;
  client.on('qr', qr => {
    ready = false;
    if (process.stdout.isTTY) {
      console.log('Link the sending account from WhatsApp → Linked devices. Keep this QR private.');
      qrcode.generate(qr, { small: true });
    } else console.error('WhatsApp pairing required. Run the sender in your interactive terminal.');
  });
  client.on('ready', () => { ready = true; console.log('WhatsApp sender ready.'); });
  client.on('auth_failure', () => { ready = false; console.error('WhatsApp authentication failed.'); });
  client.on('disconnected', () => { ready = false; console.error('WhatsApp sender disconnected.'); });
  const app = createApp({ apiKey: config.apiKey, client: {
    get ready() { return ready; },
    getNumberId: value => client.getNumberId(value),
    sendMessage: (...args) => client.sendMessage(...args),
  } });
  const server = app.listen(config.port, '127.0.0.1', () => console.log('Private OTPigeon sender listening on loopback.'));
  server.headersTimeout = 10000;
  server.requestTimeout = 30000;
  const stop = () => { ready = false; server.close(); client.destroy().finally(() => process.exit(0)); };
  process.once('SIGINT', stop); process.once('SIGTERM', stop);
  await client.initialize();
}

if (require.main === module) start().catch(() => {
  console.error('Sender could not start. Check private files and installed Chrome; no code was sent.');
  process.exit(1);
});
module.exports = { loadConfig };
