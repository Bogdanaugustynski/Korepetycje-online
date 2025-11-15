// static/js/aliboard_sync.js

(function () {
  const roomId = window.ALIBOARD_ROOM_ID || "demo";

  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const socketUrl = `${protocol}://${window.location.host}/ws/aliboard/${roomId}/`;

  let socket = null;
  const listeners = {}; // { type: [handler, ...] }
  let reconnectDelay = 1000;
  const maxReconnectDelay = 10000;

  function log(...args) {
    // console.log("[AliboardSync]", ...args);
  }

  function connect() {
    log("Connecting to", socketUrl);
    socket = new WebSocket(socketUrl);

    socket.onopen = () => {
      log("WebSocket connected");
      reconnectDelay = 1000;
    };

    socket.onclose = (event) => {
      log("WebSocket closed", event.code, event.reason);
      // try to reconnect (simple backoff)
      setTimeout(() => {
        reconnectDelay = Math.min(reconnectDelay * 1.5, maxReconnectDelay);
        connect();
      }, reconnectDelay);
    };

    socket.onerror = (error) => {
      log("WebSocket error", error);
    };

    socket.onmessage = (event) => {
      let data;
      try {
        data = JSON.parse(event.data);
      } catch (e) {
        log("Cannot parse message", event.data);
        return;
      }

      const type = data.type;
      const payload = data.payload;
      const handlers = listeners[type] || [];
      handlers.forEach((h) => {
        try {
          h(payload);
        } catch (e) {
          console.error("AliboardSync handler error", e);
        }
      });
    };
  }

  function send(type, payload) {
    const message = JSON.stringify({ type, payload });
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(message);
    } else {
      log("Cannot send, socket not open", type);
    }
  }

  function on(type, handler) {
    if (!listeners[type]) {
      listeners[type] = [];
    }
    listeners[type].push(handler);
    return () => {
      const arr = listeners[type];
      if (!arr) return;
      const idx = arr.indexOf(handler);
      if (idx !== -1) arr.splice(idx, 1);
    };
  }

  // public API
  window.AliboardSync = {
    send,
    on,
  };

  connect();
})();

