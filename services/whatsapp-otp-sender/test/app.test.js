const assert = require('node:assert/strict');
const test = require('node:test');
const { createApp } = require('../src/app');
const { loadConfig } = require('../src/main');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const key = 'test-only-key-never-used-for-real-sending-123456';

async function serve(run, changes = {}) {
  const messages = [];
  const client = { ready: true, getNumberId: async () => ({ _serialized: 'fictional@c.us' }),
    sendMessage: async (...args) => { messages.push(args); return {}; }, ...changes };
  const server = createApp({ apiKey: key, client }).listen(0, '127.0.0.1');
  await new Promise(resolve => server.once('listening', resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  const post = (body, supplied = key) => fetch(origin + '/send-otp', { method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-SENDER-API-KEY': supplied }, body: JSON.stringify(body) });
  try { await run({ post, origin, messages }); }
  finally { await new Promise(resolve => server.close(resolve)); }
}

test('only authenticated valid requests can use the delivery boundary', async () => {
  await serve(async ({ post, messages }) => {
    const body = { phone: '+919000000001', otp: '004219' };
    assert.equal((await post(body, '')).status, 401);
    assert.equal((await post(body, 'wrong')).status, 401);
    assert.equal((await post({ ...body, sender: 'injected' })).status, 400);
    assert.equal((await post({ ...body, otp: '12345a' })).status, 400);
    assert.equal((await post({ ...body, phone: '+15551234567' })).status, 400);
    assert.equal(messages.length, 0);
    const result = await post(body);
    assert.equal(result.status, 200);
    assert.deepEqual(await result.json(), { sent: true });
    assert.equal(messages.length, 1);
    assert.match(messages[0][1], /004219/);
  });
});

test('unpaired sender is honest, and QR/session admin is not exposed', async () => {
  await serve(async ({ post, origin, messages }) => {
    assert.equal((await post({ phone: '+919000000001', otp: '123456' })).status, 503);
    assert.equal(messages.length, 0);
    assert.deepEqual(await (await fetch(origin + '/health')).json(), { status: 'ok' });
    for (const path of ['/qr', '/status', '/senders']) {
      assert.equal((await fetch(origin + path, { headers: { 'X-SENDER-API-KEY': key } })).status, 404);
    }
  }, { ready: false });
});

test('unregistered recipient never receives a success response', async () => {
  await serve(async ({ post, messages }) => {
    assert.equal((await post({ phone: '+919000000001', otp: '123456' })).status, 404);
    assert.equal(messages.length, 0);
  }, { getNumberId: async () => null });
});

test('startup refuses unsafe key, browser and session paths without launching a client', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'otpigeon-config-'));
  const keyFile = path.join(dir, 'sender.key');
  const browser = path.join(dir, 'fake-browser');
  fs.writeFileSync(keyFile, key, { mode: 0o600 });
  fs.writeFileSync(browser, 'unit test fixture, never executed', { mode: 0o700 });
  const env = { OTP_SENDER_API_KEY_FILE: keyFile, OTP_SENDER_DATA_DIR: path.join(dir, 'session'), OTP_SENDER_BROWSER_EXECUTABLE: browser };
  assert.equal(loadConfig(env).browser, browser);
  for (const value of [undefined, 'relative', dir]) assert.throws(() => loadConfig({ ...env, OTP_SENDER_BROWSER_EXECUTABLE: value }));
  fs.chmodSync(browser, 0o600);
  assert.throws(() => loadConfig(env));
  fs.chmodSync(browser, 0o700);
  fs.chmodSync(keyFile, 0o644);
  assert.throws(() => loadConfig(env));
  fs.chmodSync(keyFile, 0o600);
  fs.writeFileSync(keyFile, 'short');
  assert.throws(() => loadConfig(env));
  fs.writeFileSync(keyFile, key);
  assert.throws(() => loadConfig({ ...env, OTP_SENDER_DATA_DIR: 'relative' }));
});
