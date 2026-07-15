const express = require('express');
const crypto = require('crypto');
const db = require('../db');
const { authenticate, requireAdmin } = require('../middleware/auth');
const { requireFields } = require('../middleware/validate');
const { emitDeliveryUpdate } = require('../realtime');

const router = express.Router();
router.use(authenticate);

const STATUSES = ['pending', 'assigned', 'picked_up', 'in_transit', 'delivered', 'failed', 'cancelled'];

// Legal status transitions — a delivery moves forward through its lifecycle,
// and can fail/cancel from any non-terminal state.
const TRANSITIONS = {
  pending: ['assigned', 'cancelled'],
  assigned: ['picked_up', 'cancelled'],
  picked_up: ['in_transit', 'failed', 'cancelled'],
  in_transit: ['delivered', 'failed'],
  delivered: [],
  failed: ['assigned'], // failed deliveries can be re-attempted
  cancelled: [],
};

const DELIVERY_SELECT = `
  SELECT d.*, z.name AS zone_name, a.name AS agent_name, a.phone AS agent_phone, u.name AS created_by_name
  FROM deliveries d
  LEFT JOIN zones z ON z.id = d.zone_id
  LEFT JOIN agents a ON a.id = d.agent_id
  LEFT JOIN users u ON u.id = d.created_by`;

function generateTrackingNumber() {
  return 'DMS-' + crypto.randomBytes(4).toString('hex').toUpperCase();
}

function getDelivery(id) {
  return db.prepare(`${DELIVERY_SELECT} WHERE d.id = ?`).get(id);
}

function recordEvent(deliveryId, status, note, actorId) {
  db.prepare('INSERT INTO delivery_events (delivery_id, status, note, actor_id) VALUES (?, ?, ?, ?)').run(
    deliveryId,
    status,
    note ?? null,
    actorId ?? null
  );
}

// List with filtering + pagination
router.get('/', (req, res) => {
  const { status, agent_id, zone_id, q } = req.query;
  const page = Math.max(1, parseInt(req.query.page, 10) || 1);
  const limit = Math.min(100, Math.max(1, parseInt(req.query.limit, 10) || 20));

  const where = [];
  const params = [];
  if (status) {
    if (!STATUSES.includes(status)) return res.status(400).json({ error: `status must be one of: ${STATUSES.join(', ')}` });
    where.push('d.status = ?');
    params.push(status);
  }
  if (agent_id) { where.push('d.agent_id = ?'); params.push(agent_id); }
  if (zone_id) { where.push('d.zone_id = ?'); params.push(zone_id); }
  if (q) {
    where.push('(d.tracking_number LIKE ? OR d.customer_name LIKE ? OR d.customer_phone LIKE ?)');
    params.push(`%${q}%`, `%${q}%`, `%${q}%`);
  }
  const whereSql = where.length ? `WHERE ${where.join(' AND ')}` : '';

  const total = db.prepare(`SELECT COUNT(*) AS n FROM deliveries d ${whereSql}`).get(...params).n;
  const deliveries = db
    .prepare(`${DELIVERY_SELECT} ${whereSql} ORDER BY d.created_at DESC, d.id DESC LIMIT ? OFFSET ?`)
    .all(...params, limit, (page - 1) * limit);

  res.json({ deliveries, pagination: { page, limit, total, pages: Math.ceil(total / limit) } });
});

router.get('/:id', (req, res) => {
  const delivery = getDelivery(req.params.id);
  if (!delivery) return res.status(404).json({ error: 'Delivery not found' });
  const events = db
    .prepare('SELECT e.*, u.name AS actor_name FROM delivery_events e LEFT JOIN users u ON u.id = e.actor_id WHERE e.delivery_id = ? ORDER BY e.id')
    .all(delivery.id);
  res.json({ delivery, events });
});

router.post(
  '/',
  requireFields({
    customer_name: { type: 'string', minLength: 2 },
    customer_phone: { type: 'string', minLength: 7 },
    pickup_address: { type: 'string', minLength: 5 },
    drop_address: { type: 'string', minLength: 5 },
    weight_kg: { type: 'number', optional: true },
  }),
  (req, res) => {
    const { customer_name, customer_phone, pickup_address, drop_address, zone_id, weight_kg, notes } = req.body;
    try {
      const info = db
        .prepare(
          `INSERT INTO deliveries (tracking_number, customer_name, customer_phone, pickup_address, drop_address, zone_id, weight_kg, notes, created_by)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`
        )
        .run(
          generateTrackingNumber(),
          customer_name.trim(),
          customer_phone.trim(),
          pickup_address.trim(),
          drop_address.trim(),
          zone_id ?? null,
          weight_kg ?? 0,
          notes ?? null,
          req.user.id
        );
      recordEvent(info.lastInsertRowid, 'pending', 'Delivery created', req.user.id);
      const delivery = getDelivery(info.lastInsertRowid);
      emitDeliveryUpdate('delivery:created', delivery);
      res.status(201).json({ delivery });
    } catch (e) {
      if (String(e.message).includes('FOREIGN KEY')) return res.status(400).json({ error: 'Unknown zone_id' });
      throw e;
    }
  }
);

// Edit delivery details (only while still pending/assigned)
router.put('/:id', (req, res) => {
  const delivery = db.prepare('SELECT * FROM deliveries WHERE id = ?').get(req.params.id);
  if (!delivery) return res.status(404).json({ error: 'Delivery not found' });
  if (!['pending', 'assigned'].includes(delivery.status)) {
    return res.status(409).json({ error: `Cannot edit a delivery in '${delivery.status}' status` });
  }
  const { customer_name, customer_phone, pickup_address, drop_address, zone_id, weight_kg, notes } = req.body;
  try {
    db.prepare(
      `UPDATE deliveries SET customer_name = ?, customer_phone = ?, pickup_address = ?, drop_address = ?,
       zone_id = ?, weight_kg = ?, notes = ?, updated_at = datetime('now') WHERE id = ?`
    ).run(
      customer_name?.trim() ?? delivery.customer_name,
      customer_phone?.trim() ?? delivery.customer_phone,
      pickup_address?.trim() ?? delivery.pickup_address,
      drop_address?.trim() ?? delivery.drop_address,
      zone_id === undefined ? delivery.zone_id : zone_id,
      weight_kg ?? delivery.weight_kg,
      notes === undefined ? delivery.notes : notes,
      delivery.id
    );
  } catch (e) {
    if (String(e.message).includes('FOREIGN KEY')) return res.status(400).json({ error: 'Unknown zone_id' });
    throw e;
  }
  const updated = getDelivery(delivery.id);
  emitDeliveryUpdate('delivery:updated', updated);
  res.json({ delivery: updated });
});

// Assign an agent (moves pending -> assigned; also used for failed -> assigned re-attempts)
router.post('/:id/assign', requireFields({ agent_id: { type: 'number' } }), (req, res) => {
  const delivery = db.prepare('SELECT * FROM deliveries WHERE id = ?').get(req.params.id);
  if (!delivery) return res.status(404).json({ error: 'Delivery not found' });
  if (!TRANSITIONS[delivery.status].includes('assigned')) {
    return res.status(409).json({ error: `Cannot assign a delivery in '${delivery.status}' status` });
  }
  const agent = db.prepare('SELECT * FROM agents WHERE id = ? AND active = 1').get(req.body.agent_id);
  if (!agent) return res.status(400).json({ error: 'Agent not found or inactive' });

  db.prepare("UPDATE deliveries SET agent_id = ?, status = 'assigned', updated_at = datetime('now') WHERE id = ?").run(
    agent.id,
    delivery.id
  );
  recordEvent(delivery.id, 'assigned', `Assigned to ${agent.name}`, req.user.id);
  const updated = getDelivery(delivery.id);
  emitDeliveryUpdate('delivery:updated', updated);
  res.json({ delivery: updated });
});

// Advance the delivery through its lifecycle
router.post('/:id/status', requireFields({ status: { type: 'string', enum: STATUSES } }), (req, res) => {
  const delivery = db.prepare('SELECT * FROM deliveries WHERE id = ?').get(req.params.id);
  if (!delivery) return res.status(404).json({ error: 'Delivery not found' });

  const next = req.body.status;
  if (!TRANSITIONS[delivery.status].includes(next)) {
    return res.status(409).json({
      error: `Illegal transition: '${delivery.status}' -> '${next}'`,
      allowed: TRANSITIONS[delivery.status],
    });
  }
  if (next === 'assigned') return res.status(400).json({ error: 'Use POST /:id/assign to assign an agent' });

  db.prepare("UPDATE deliveries SET status = ?, updated_at = datetime('now') WHERE id = ?").run(next, delivery.id);
  recordEvent(delivery.id, next, req.body.note, req.user.id);
  const updated = getDelivery(delivery.id);
  emitDeliveryUpdate('delivery:updated', updated);
  res.json({ delivery: updated });
});

// Hard delete is admin-only; the audit trail goes with it (ON DELETE CASCADE)
router.delete('/:id', requireAdmin, (req, res) => {
  const delivery = db.prepare('SELECT * FROM deliveries WHERE id = ?').get(req.params.id);
  if (!delivery) return res.status(404).json({ error: 'Delivery not found' });
  db.prepare('DELETE FROM deliveries WHERE id = ?').run(delivery.id);
  emitDeliveryUpdate('delivery:deleted', { id: delivery.id, tracking_number: delivery.tracking_number });
  res.json({ deleted: true });
});

module.exports = router;
