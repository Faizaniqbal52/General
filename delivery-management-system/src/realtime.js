// Socket.IO layer: authenticated clients join the 'ops' room and receive
// live delivery lifecycle events emitted by the REST handlers.
const { Server } = require('socket.io');
const jwt = require('jsonwebtoken');
const { JWT_SECRET } = require('./middleware/auth');

let io = null;

function initRealtime(httpServer) {
  io = new Server(httpServer, { cors: { origin: true } });

  io.use((socket, next) => {
    const token = socket.handshake.auth?.token;
    if (!token) return next(new Error('Authentication required'));
    try {
      socket.user = jwt.verify(token, JWT_SECRET);
      next();
    } catch {
      next(new Error('Invalid token'));
    }
  });

  io.on('connection', (socket) => {
    socket.join('ops');
    socket.emit('connected', { user: socket.user.name, role: socket.user.role });
  });

  return io;
}

function emitDeliveryUpdate(event, payload) {
  if (io) io.to('ops').emit(event, payload);
}

function closeRealtime() {
  if (io) io.close(); // also closes the underlying HTTP server
}

module.exports = { initRealtime, emitDeliveryUpdate, closeRealtime };
