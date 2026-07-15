// Master data (admin-managed): zones, vehicles, agents.
// Any authenticated user can read; only admins can create/update/delete.
const express = require('express');
const db = require('../db');
const { authenticate, requireAdmin } = require('../middleware/auth');
const { requireFields } = require('../middleware/validate');

const router = express.Router();
router.use(authenticate);

function notFound(res) {
  return res.status(404).json({ error: 'Not found' });
}

// ---------- Zones ----------
router.get('/zones', (req, res) => {
  res.json({ zones: db.prepare('SELECT * FROM zones ORDER BY name').all() });
});

router.post(
  '/zones',
  requireAdmin,
  requireFields({ name: { type: 'string', minLength: 2 }, city: { type: 'string', minLength: 2 } }),
  (req, res) => {
    try {
      const info = db.prepare('INSERT INTO zones (name, city) VALUES (?, ?)').run(req.body.name.trim(), req.body.city.trim());
      res.status(201).json({ zone: db.prepare('SELECT * FROM zones WHERE id = ?').get(info.lastInsertRowid) });
    } catch (e) {
      if (String(e.message).includes('UNIQUE')) return res.status(409).json({ error: 'Zone name already exists' });
      throw e;
    }
  }
);

router.put(
  '/zones/:id',
  requireAdmin,
  requireFields({ name: { type: 'string', minLength: 2, optional: true }, city: { type: 'string', minLength: 2, optional: true } }),
  (req, res) => {
    const zone = db.prepare('SELECT * FROM zones WHERE id = ?').get(req.params.id);
    if (!zone) return notFound(res);
    const name = req.body.name?.trim() ?? zone.name;
    const city = req.body.city?.trim() ?? zone.city;
    db.prepare('UPDATE zones SET name = ?, city = ? WHERE id = ?').run(name, city, zone.id);
    res.json({ zone: db.prepare('SELECT * FROM zones WHERE id = ?').get(zone.id) });
  }
);

router.delete('/zones/:id', requireAdmin, (req, res) => {
  const info = db.prepare('DELETE FROM zones WHERE id = ?').run(req.params.id);
  if (!info.changes) return notFound(res);
  res.json({ deleted: true });
});

// ---------- Vehicles ----------
router.get('/vehicles', (req, res) => {
  res.json({ vehicles: db.prepare('SELECT * FROM vehicles ORDER BY id').all() });
});

router.post(
  '/vehicles',
  requireAdmin,
  requireFields({
    plate_number: { type: 'string', minLength: 4 },
    type: { type: 'string', enum: ['bike', 'van', 'truck'] },
    capacity_kg: { type: 'number', optional: true },
  }),
  (req, res) => {
    try {
      const info = db
        .prepare('INSERT INTO vehicles (plate_number, type, capacity_kg) VALUES (?, ?, ?)')
        .run(req.body.plate_number.trim().toUpperCase(), req.body.type, req.body.capacity_kg ?? 0);
      res.status(201).json({ vehicle: db.prepare('SELECT * FROM vehicles WHERE id = ?').get(info.lastInsertRowid) });
    } catch (e) {
      if (String(e.message).includes('UNIQUE')) return res.status(409).json({ error: 'Plate number already exists' });
      throw e;
    }
  }
);

router.put('/vehicles/:id', requireAdmin, (req, res) => {
  const vehicle = db.prepare('SELECT * FROM vehicles WHERE id = ?').get(req.params.id);
  if (!vehicle) return notFound(res);
  const { plate_number, type, capacity_kg, active } = req.body;
  if (type && !['bike', 'van', 'truck'].includes(type)) {
    return res.status(400).json({ error: 'Validation failed', fields: { type: 'must be one of: bike, van, truck' } });
  }
  db.prepare('UPDATE vehicles SET plate_number = ?, type = ?, capacity_kg = ?, active = ? WHERE id = ?').run(
    plate_number?.trim().toUpperCase() ?? vehicle.plate_number,
    type ?? vehicle.type,
    capacity_kg ?? vehicle.capacity_kg,
    active === undefined ? vehicle.active : active ? 1 : 0,
    vehicle.id
  );
  res.json({ vehicle: db.prepare('SELECT * FROM vehicles WHERE id = ?').get(vehicle.id) });
});

router.delete('/vehicles/:id', requireAdmin, (req, res) => {
  const info = db.prepare('DELETE FROM vehicles WHERE id = ?').run(req.params.id);
  if (!info.changes) return notFound(res);
  res.json({ deleted: true });
});

// ---------- Agents ----------
const AGENT_SELECT = `
  SELECT a.*, z.name AS zone_name, v.plate_number AS vehicle_plate
  FROM agents a
  LEFT JOIN zones z ON z.id = a.zone_id
  LEFT JOIN vehicles v ON v.id = a.vehicle_id`;

router.get('/agents', (req, res) => {
  res.json({ agents: db.prepare(`${AGENT_SELECT} ORDER BY a.name`).all() });
});

router.post(
  '/agents',
  requireAdmin,
  requireFields({ name: { type: 'string', minLength: 2 }, phone: { type: 'string', minLength: 7 } }),
  (req, res) => {
    const { name, phone, zone_id, vehicle_id } = req.body;
    try {
      const info = db
        .prepare('INSERT INTO agents (name, phone, zone_id, vehicle_id) VALUES (?, ?, ?, ?)')
        .run(name.trim(), phone.trim(), zone_id ?? null, vehicle_id ?? null);
      res.status(201).json({ agent: db.prepare(`${AGENT_SELECT} WHERE a.id = ?`).get(info.lastInsertRowid) });
    } catch (e) {
      if (String(e.message).includes('UNIQUE')) return res.status(409).json({ error: 'Phone number already exists' });
      if (String(e.message).includes('FOREIGN KEY')) return res.status(400).json({ error: 'Unknown zone_id or vehicle_id' });
      throw e;
    }
  }
);

router.put('/agents/:id', requireAdmin, (req, res) => {
  const agent = db.prepare('SELECT * FROM agents WHERE id = ?').get(req.params.id);
  if (!agent) return notFound(res);
  const { name, phone, zone_id, vehicle_id, active } = req.body;
  try {
    db.prepare('UPDATE agents SET name = ?, phone = ?, zone_id = ?, vehicle_id = ?, active = ? WHERE id = ?').run(
      name?.trim() ?? agent.name,
      phone?.trim() ?? agent.phone,
      zone_id === undefined ? agent.zone_id : zone_id,
      vehicle_id === undefined ? agent.vehicle_id : vehicle_id,
      active === undefined ? agent.active : active ? 1 : 0,
      agent.id
    );
  } catch (e) {
    if (String(e.message).includes('FOREIGN KEY')) return res.status(400).json({ error: 'Unknown zone_id or vehicle_id' });
    throw e;
  }
  res.json({ agent: db.prepare(`${AGENT_SELECT} WHERE a.id = ?`).get(agent.id) });
});

router.delete('/agents/:id', requireAdmin, (req, res) => {
  const info = db.prepare('DELETE FROM agents WHERE id = ?').run(req.params.id);
  if (!info.changes) return notFound(res);
  res.json({ deleted: true });
});

module.exports = router;
