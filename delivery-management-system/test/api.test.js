// End-to-end smoke tests: boots the real server on a random port with a
// throwaway database and exercises auth, RBAC, master data, the delivery
// lifecycle, public tracking, and the realtime socket event.
const test = require('node:test');
const assert = require('node:assert');
const os = require('os');
const path = require('path');

process.env.DB_PATH = path.join(os.tmpdir(), `dms-test-${Date.now()}.db`);
process.env.JWT_SECRET = 'test-secret';

const { server } = require('../server');
const { closeRealtime } = require('../src/realtime');

let base;
let adminToken;
let userToken;

async function api(pathname, { method = 'GET', token, body } = {}) {
  const res = await fetch(base + pathname, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  return { status: res.status, data: await res.json() };
}

test.before(async () => {
  await new Promise((resolve) => server.listen(0, resolve));
  base = `http://127.0.0.1:${server.address().port}`;
});

test.after(() => {
  closeRealtime(); // closes socket.io and the underlying HTTP server
  server.closeAllConnections?.();
});

test('health check responds', async () => {
  const { status, data } = await api('/api/health');
  assert.equal(status, 200);
  assert.equal(data.ok, true);
});

test('first registered user becomes admin, second becomes user', async () => {
  let r = await api('/api/auth/register', {
    method: 'POST',
    body: { name: 'Boss', email: 'boss@test.io', password: 'secret1' },
  });
  assert.equal(r.status, 201);
  assert.equal(r.data.user.role, 'admin');
  adminToken = r.data.token;

  r = await api('/api/auth/register', {
    method: 'POST',
    body: { name: 'Ops', email: 'ops@test.io', password: 'secret1' },
  });
  assert.equal(r.status, 201);
  assert.equal(r.data.user.role, 'user');
  userToken = r.data.token;
});

test('register validates input and rejects duplicates', async () => {
  let r = await api('/api/auth/register', { method: 'POST', body: { name: 'X', email: 'bad', password: '1' } });
  assert.equal(r.status, 400);
  r = await api('/api/auth/register', {
    method: 'POST',
    body: { name: 'Dup', email: 'boss@test.io', password: 'secret1' },
  });
  assert.equal(r.status, 409);
});

test('login works and bad credentials are rejected', async () => {
  let r = await api('/api/auth/login', { method: 'POST', body: { email: 'boss@test.io', password: 'secret1' } });
  assert.equal(r.status, 200);
  r = await api('/api/auth/login', { method: 'POST', body: { email: 'boss@test.io', password: 'wrong' } });
  assert.equal(r.status, 401);
});

test('protected routes require a token', async () => {
  const r = await api('/api/deliveries');
  assert.equal(r.status, 401);
});

test('role middleware blocks non-admin writes to master data', async () => {
  let r = await api('/api/master/zones', { method: 'POST', token: userToken, body: { name: 'Zone A', city: 'Srinagar' } });
  assert.equal(r.status, 403);

  r = await api('/api/master/zones', { method: 'POST', token: adminToken, body: { name: 'Zone A', city: 'Srinagar' } });
  assert.equal(r.status, 201);

  // but any authenticated user can read master data
  r = await api('/api/master/zones', { token: userToken });
  assert.equal(r.status, 200);
  assert.equal(r.data.zones.length, 1);
});

test('admin can create vehicle and agent', async () => {
  let r = await api('/api/master/vehicles', {
    method: 'POST',
    token: adminToken,
    body: { plate_number: 'JK01T0001', type: 'bike', capacity_kg: 12 },
  });
  assert.equal(r.status, 201);

  r = await api('/api/master/agents', {
    method: 'POST',
    token: adminToken,
    body: { name: 'Agent One', phone: '9999900000', zone_id: 1, vehicle_id: 1 },
  });
  assert.equal(r.status, 201);
  assert.equal(r.data.agent.zone_name, 'Zone A');
});

test('full delivery lifecycle with audit trail and realtime event', async () => {
  // Listen on the socket as the admin before creating the delivery.
  const { io } = require('socket.io-client');
  const socket = io(base, { auth: { token: adminToken } });
  const createdEvent = new Promise((resolve) => socket.on('delivery:created', resolve));
  // Wait for the server's post-join handshake so we can't miss the event.
  await new Promise((resolve, reject) => {
    socket.on('connected', resolve);
    socket.on('connect_error', reject);
    setTimeout(() => reject(new Error('socket connect timed out')), 5000);
  });

  let r = await api('/api/deliveries', {
    method: 'POST',
    token: userToken,
    body: {
      customer_name: 'Test Customer',
      customer_phone: '9888800000',
      pickup_address: 'Lal Chowk, Srinagar',
      drop_address: 'Hazratbal, Srinagar',
      zone_id: 1,
      weight_kg: 3,
    },
  });
  assert.equal(r.status, 201);
  const delivery = r.data.delivery;
  assert.match(delivery.tracking_number, /^DMS-/);
  assert.equal(delivery.status, 'pending');

  const live = await createdEvent;
  assert.equal(live.tracking_number, delivery.tracking_number);
  socket.close();

  // Illegal transition is rejected
  r = await api(`/api/deliveries/${delivery.id}/status`, { method: 'POST', token: userToken, body: { status: 'delivered' } });
  assert.equal(r.status, 409);

  // pending -> assigned -> picked_up -> in_transit -> delivered
  r = await api(`/api/deliveries/${delivery.id}/assign`, { method: 'POST', token: userToken, body: { agent_id: 1 } });
  assert.equal(r.status, 200);
  assert.equal(r.data.delivery.status, 'assigned');
  for (const status of ['picked_up', 'in_transit', 'delivered']) {
    r = await api(`/api/deliveries/${delivery.id}/status`, { method: 'POST', token: userToken, body: { status } });
    assert.equal(r.status, 200, `transition to ${status}`);
  }

  // Audit trail recorded every step
  r = await api(`/api/deliveries/${delivery.id}`, { token: userToken });
  assert.deepEqual(
    r.data.events.map((e) => e.status),
    ['pending', 'assigned', 'picked_up', 'in_transit', 'delivered']
  );

  // Public tracking works without a token
  r = await api(`/api/track/${delivery.tracking_number}`);
  assert.equal(r.status, 200);
  assert.equal(r.data.delivery.status, 'delivered');
  assert.equal(r.data.events.length, 5);

  // Deleting is admin-only
  r = await api(`/api/deliveries/${delivery.id}`, { method: 'DELETE', token: userToken });
  assert.equal(r.status, 403);
  r = await api(`/api/deliveries/${delivery.id}`, { method: 'DELETE', token: adminToken });
  assert.equal(r.status, 200);
});

test('stats endpoint aggregates counts', async () => {
  const r = await api('/api/stats', { token: userToken });
  assert.equal(r.status, 200);
  assert.equal(typeof r.data.totals.deliveries, 'number');
  assert.equal(r.data.totals.agents, 1);
});
