const express = require('express');
const bcrypt = require('bcryptjs');
const db = require('../db');
const { signToken, authenticate } = require('../middleware/auth');
const { requireFields } = require('../middleware/validate');

const router = express.Router();

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

router.post(
  '/register',
  requireFields({
    name: { type: 'string', minLength: 2 },
    email: { type: 'string', pattern: EMAIL_RE, patternMessage: 'must be a valid email' },
    password: { type: 'string', minLength: 6 },
  }),
  (req, res) => {
    const { name, email, password } = req.body;
    const exists = db.prepare('SELECT id FROM users WHERE email = ?').get(email);
    if (exists) return res.status(409).json({ error: 'Email already registered' });

    // First account ever becomes admin so a fresh install is usable immediately.
    const isFirstUser = db.prepare('SELECT COUNT(*) AS n FROM users').get().n === 0;
    const role = isFirstUser ? 'admin' : 'user';

    const hash = bcrypt.hashSync(password, 10);
    const info = db
      .prepare('INSERT INTO users (name, email, password, role) VALUES (?, ?, ?, ?)')
      .run(name.trim(), email.toLowerCase(), hash, role);

    const user = { id: info.lastInsertRowid, name: name.trim(), role };
    res.status(201).json({ token: signToken(user), user: { ...user, email: email.toLowerCase() } });
  }
);

router.post(
  '/login',
  requireFields({ email: { type: 'string' }, password: { type: 'string' } }),
  (req, res) => {
    const { email, password } = req.body;
    const user = db.prepare('SELECT * FROM users WHERE email = ?').get(email);
    if (!user || !bcrypt.compareSync(password, user.password)) {
      return res.status(401).json({ error: 'Invalid email or password' });
    }
    res.json({
      token: signToken(user),
      user: { id: user.id, name: user.name, email: user.email, role: user.role },
    });
  }
);

router.get('/me', authenticate, (req, res) => {
  const user = db.prepare('SELECT id, name, email, role, created_at FROM users WHERE id = ?').get(req.user.id);
  if (!user) return res.status(404).json({ error: 'User not found' });
  res.json({ user });
});

module.exports = router;
