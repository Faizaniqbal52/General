// Public package tracking — no authentication, exposes only non-sensitive fields.
const express = require('express');
const db = require('../db');

const router = express.Router();

router.get('/:trackingNumber', (req, res) => {
  const delivery = db
    .prepare(
      `SELECT d.tracking_number, d.status, d.customer_name, d.drop_address, d.created_at, d.updated_at,
              z.name AS zone_name, a.name AS agent_name
       FROM deliveries d
       LEFT JOIN zones z ON z.id = d.zone_id
       LEFT JOIN agents a ON a.id = d.agent_id
       WHERE d.tracking_number = ?`
    )
    .get(req.params.trackingNumber.trim().toUpperCase());

  if (!delivery) return res.status(404).json({ error: 'Tracking number not found' });

  const events = db
    .prepare(
      `SELECT e.status, e.note, e.created_at
       FROM delivery_events e
       JOIN deliveries d ON d.id = e.delivery_id
       WHERE d.tracking_number = ? ORDER BY e.id`
    )
    .all(delivery.tracking_number);

  res.json({ delivery, events });
});

module.exports = router;
