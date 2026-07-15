const express = require('express');
const db = require('../db');
const { authenticate } = require('../middleware/auth');

const router = express.Router();

router.get('/', authenticate, (req, res) => {
  const byStatus = {};
  for (const row of db.prepare('SELECT status, COUNT(*) AS n FROM deliveries GROUP BY status').all()) {
    byStatus[row.status] = row.n;
  }
  const totals = {
    deliveries: db.prepare('SELECT COUNT(*) AS n FROM deliveries').get().n,
    agents: db.prepare('SELECT COUNT(*) AS n FROM agents WHERE active = 1').get().n,
    vehicles: db.prepare('SELECT COUNT(*) AS n FROM vehicles WHERE active = 1').get().n,
    zones: db.prepare('SELECT COUNT(*) AS n FROM zones').get().n,
  };
  const deliveredToday = db
    .prepare("SELECT COUNT(*) AS n FROM delivery_events WHERE status = 'delivered' AND date(created_at) = date('now')")
    .get().n;

  res.json({ totals, byStatus, deliveredToday });
});

module.exports = router;
