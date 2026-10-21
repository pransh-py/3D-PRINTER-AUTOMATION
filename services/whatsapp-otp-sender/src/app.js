// Delivery path adapted from pransh-py/OTPigeon@313734d72e6f77513bce6d72fd4e4695f1cab62c.
// PrintFlow owns verification; this private service only delivers a bounded message.
const express = require('express');
const { createHash, timingSafeEqual } = require('node:crypto');

function createApp({ apiKey, client }) {
  if (typeof apiKey !== 'string' || Buffer.byteLength(apiKey) < 32) throw new Error('A strong private key is required.');
  const app = express();
  app.disable('x-powered-by');
  const digest = value => createHash('sha256').update(value).digest();
  const expected = digest(apiKey);
  app.get('/health', (_req, res) => res.json({ status: 'ok' }));
  app.use((req, res, next) => {
    const supplied = req.get('X-SENDER-API-KEY');
    if (typeof supplied !== 'string' || !timingSafeEqual(digest(supplied), expected)) {
      return res.status(401).json({ error: 'unauthorized' });
    }
    next();
  });
  app.get('/ready', (_req, res) => res.json({ ready: client.ready === true }));
  app.post('/send-otp', express.json({ limit: '1kb', strict: true }), async (req, res) => {
    const body = req.body;
    if (!body || typeof body !== 'object' || Array.isArray(body)
        || Object.keys(body).sort().join(',') !== 'otp,phone'
        || typeof body.phone !== 'string' || !/^\+91[6-9][0-9]{9}$/.test(body.phone)
        || typeof body.otp !== 'string' || !/^[0-9]{6}$/.test(body.otp)) {
      return res.status(400).json({ error: 'invalid_request' });
    }
    if (client.ready !== true) return res.status(503).json({ error: 'sender_not_ready' });
    let timer;
    try {
      const send = async () => {
        const recipient = await client.getNumberId(body.phone.slice(1));
        if (!recipient) return false;
        await client.sendMessage(recipient._serialized,
          `Your verification code is ${body.otp}. It expires in 5 minutes. Do not share it.`);
        return true;
      };
      const result = await Promise.race([send(), new Promise((_, reject) => {
        timer = setTimeout(() => reject(Object.assign(new Error('timeout'), { code: 'SEND_TIMEOUT' })), 15000);
      })]);
      return result ? res.json({ sent: true }) : res.status(404).json({ error: 'number_not_registered' });
    } catch (error) {
      return res.status(error?.code === 'SEND_TIMEOUT' ? 504 : 500)
        .json({ error: error?.code === 'SEND_TIMEOUT' ? 'send_timeout' : 'send_failed' });
    } finally { clearTimeout(timer); }
  });
  app.use((_req, res) => res.status(404).json({ error: 'not_found' }));
  app.use((_error, _req, res, _next) => res.status(400).json({ error: 'invalid_request' }));
  return app;
}
module.exports = { createApp };
