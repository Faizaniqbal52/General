// Seeds demo data: an admin, a user, zones, vehicles, agents and a few deliveries.
// Safe to re-run — skips anything that already exists.
const bcrypt = require('bcryptjs');
const db = require('../src/db');

function upsertUser(name, email, password, role) {
  const existing = db.prepare('SELECT id FROM users WHERE email = ?').get(email);
  if (existing) return existing.id;
  return db
    .prepare('INSERT INTO users (name, email, password, role) VALUES (?, ?, ?, ?)')
    .run(name, email, bcrypt.hashSync(password, 10), role).lastInsertRowid;
}

const adminId = upsertUser('Admin', 'admin@dms.local', 'admin123', 'admin');
upsertUser('Operator', 'user@dms.local', 'user1234', 'user');

const zones = [
  ['North Zone', 'Srinagar'],
  ['South Zone', 'Srinagar'],
  ['Central Zone', 'Delhi'],
];
for (const [name, city] of zones) {
  if (!db.prepare('SELECT id FROM zones WHERE name = ?').get(name)) {
    db.prepare('INSERT INTO zones (name, city) VALUES (?, ?)').run(name, city);
  }
}

const vehicles = [
  ['JK01A1234', 'bike', 15],
  ['JK01B5678', 'van', 500],
  ['DL05C9012', 'truck', 2000],
];
for (const [plate, type, cap] of vehicles) {
  if (!db.prepare('SELECT id FROM vehicles WHERE plate_number = ?').get(plate)) {
    db.prepare('INSERT INTO vehicles (plate_number, type, capacity_kg) VALUES (?, ?, ?)').run(plate, type, cap);
  }
}

const agents = [
  ['Arif Khan', '+91-9000000001', 1, 1],
  ['Sameer Lone', '+91-9000000002', 2, 2],
  ['Rahul Verma', '+91-9000000003', 3, 3],
];
for (const [name, phone, zoneId, vehicleId] of agents) {
  if (!db.prepare('SELECT id FROM agents WHERE phone = ?').get(phone)) {
    db.prepare('INSERT INTO agents (name, phone, zone_id, vehicle_id) VALUES (?, ?, ?, ?)').run(name, phone, zoneId, vehicleId);
  }
}

if (db.prepare('SELECT COUNT(*) AS n FROM deliveries').get().n === 0) {
  const insert = db.prepare(
    `INSERT INTO deliveries (tracking_number, customer_name, customer_phone, pickup_address, drop_address, zone_id, weight_kg, status, created_by)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`
  );
  const event = db.prepare('INSERT INTO delivery_events (delivery_id, status, note, actor_id) VALUES (?, ?, ?, ?)');

  const rows = [
    ['DMS-SEED0001', 'Aisha Mir', '+91-9111111111', 'Lal Chowk, Srinagar', 'Hazratbal, Srinagar', 1, 2.5, 'pending'],
    ['DMS-SEED0002', 'Vikram Singh', '+91-9222222222', 'Karol Bagh, Delhi', 'Saket, Delhi', 3, 12, 'assigned'],
    ['DMS-SEED0003', 'Neha Sharma', '+91-9333333333', 'Pampore, Srinagar', 'Anantnag', 2, 6, 'in_transit'],
    ['DMS-SEED0004', 'Omar Abdullah', '+91-9444444444', 'Rajbagh, Srinagar', 'Bemina, Srinagar', 1, 1, 'delivered'],
  ];
  for (const [tn, cname, cphone, pickup, drop, zoneId, kg, status] of rows) {
    const id = insert.run(tn, cname, cphone, pickup, drop, zoneId, kg, status, adminId).lastInsertRowid;
    event.run(id, 'pending', 'Delivery created', adminId);
    if (status !== 'pending') event.run(id, 'assigned', 'Assigned to agent', adminId);
    if (['in_transit', 'delivered'].includes(status)) {
      event.run(id, 'picked_up', 'Package picked up', adminId);
      event.run(id, 'in_transit', 'Out for delivery', adminId);
    }
    if (status === 'delivered') event.run(id, 'delivered', 'Delivered to customer', adminId);
    if (status !== 'pending') {
      db.prepare('UPDATE deliveries SET agent_id = ? WHERE id = ?').run(((zoneId - 1) % 3) + 1, id);
    }
  }
}

console.log('Seed complete.');
console.log('  Admin: admin@dms.local / admin123');
console.log('  User:  user@dms.local  / user1234');
