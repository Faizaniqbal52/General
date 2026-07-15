const http = require('http');
const path = require('path');
const express = require('express');
const helmet = require('helmet');
const cors = require('cors');
const rateLimit = require('express-rate-limit');

const { initRealtime } = require('./src/realtime');

const app = express();
const server = http.createServer(app);
initRealtime(server);

app.use(helmet({ contentSecurityPolicy: false })); // CSP off so the bundled dashboard's inline scripts work
app.use(cors());
app.use(express.json());

app.use(
  '/api/auth',
  rateLimit({ windowMs: 15 * 60 * 1000, limit: 50, standardHeaders: true, legacyHeaders: false })
);

app.use('/api/auth', require('./src/routes/auth'));
app.use('/api/master', require('./src/routes/master'));
app.use('/api/deliveries', require('./src/routes/deliveries'));
app.use('/api/track', require('./src/routes/track'));
app.use('/api/stats', require('./src/routes/stats'));

app.get('/api/health', (req, res) => res.json({ ok: true, uptime: process.uptime() }));

// Dashboard
app.use(express.static(path.join(__dirname, 'public')));

app.use('/api', (req, res) => res.status(404).json({ error: 'Route not found' }));

// eslint-disable-next-line no-unused-vars
app.use((err, req, res, next) => {
  console.error(err);
  res.status(500).json({ error: 'Internal server error' });
});

const PORT = process.env.PORT || 3000;
if (require.main === module) {
  server.listen(PORT, () => console.log(`Delivery Management System running on http://localhost:${PORT}`));
}

module.exports = { app, server };
