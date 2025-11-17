// panel/static/panel/js/aliboard_realtime.js
(function () {
  const root = document.getElementById("aliboard-root") || document.body;
  const roomId = root?.getAttribute("data-room-id");
  if (!roomId) {
    console.warn("[AliboardRealtime] brak room-id, realtime wyłączony");
    return;
  }

  const clientId = crypto.randomUUID ? crypto.randomUUID() : `client-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const patchLog = [];
  let socket = null;
  let reconnectTimer = null;
  let lastCursorSentAt = 0;
  const CURSOR_THROTTLE_MS = 80;

  const listeners = {
    open: [],
    close: [],
  };

  const loc = window.location;
  const scheme = loc.protocol === "https:" ? "wss" : "ws";
  const wsUrl = `${scheme}://${loc.host}/ws/aliboard/${roomId}/`;

  function notify(name, payload) {
    (listeners[name] || []).forEach((cb) => {
      try {
        cb(payload);
      } catch (err) {
        console.error("[AliboardRealtime] listener error", err);
      }
    });
  }

  function resetPatchLog(newOps = []) {
    patchLog.length = 0;
    if (Array.isArray(newOps)) {
      newOps.forEach((op) => patchLog.push(op));
    }
  }

  function handleSnapshot(ops) {
    resetPatchLog(ops);
    if (typeof window.aliboardResetBoardForSnapshot === "function") {
      window.aliboardResetBoardForSnapshot();
    }
    patchLog.forEach((patch) => {
      if (typeof window.aliboardApplyPatch === "function") {
        window.aliboardApplyPatch(patch);
      }
    });
  }

  function handlePatch(patch) {
    if (!patch) return;
    patchLog.push(patch);
    if (typeof window.aliboardApplyPatch === "function") {
      window.aliboardApplyPatch(patch);
    }
  }

  function handleCursor(cursor) {
    if (!cursor) return;
    if (cursor.id && cursor.id === clientId) return;
    if (typeof window.aliboardUpdateRemoteCursor === "function") {
      window.aliboardUpdateRemoteCursor(cursor);
    }
  }

  function sendSnapshot() {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(
      JSON.stringify({
        type: "snapshot",
        ops: patchLog,
      })
    );
  }

  function sendCursorPayload(payload) {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(
      JSON.stringify({
        type: "cursor",
        cursor: {
          ...payload,
          id: clientId,
        },
      })
    );
  }

  function connect() {
    try {
      socket = new WebSocket(wsUrl);
    } catch (err) {
      console.error("[AliboardRealtime] utworzenie WebSocket nie powiodło się", err);
      scheduleReconnect();
      return;
    }

    socket.onopen = function () {
      console.log("[AliboardRealtime] połączono", wsUrl);
      sendSnapshot();
      notify("open");
    };

    socket.onclose = function () {
      console.warn("[AliboardRealtime] rozłączono, ponawiam próbę…");
      notify("close");
      scheduleReconnect();
    };

    socket.onerror = function (err) {
      console.error("[AliboardRealtime] błąd gniazda", err);
    };

    socket.onmessage = function (event) {
      let data;
      try {
        data = JSON.parse(event.data);
      } catch (e) {
        console.warn("[AliboardRealtime] niepoprawny JSON", event.data);
        return;
      }

      if (data.type === "snapshot") {
        handleSnapshot(data.ops || []);
      } else if (data.type === "patch") {
        handlePatch(data.patch || null);
      } else if (data.type === "cursor") {
        handleCursor(data.cursor || null);
      }
    };
  }

  function scheduleReconnect() {
    if (reconnectTimer) return;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, 2000);
  }

  connect();

  const AliboardRealtime = {
    clientId,

    broadcastPatch(patch) {
      if (!patch) return;
      patchLog.push(patch);
      if (!socket || socket.readyState !== WebSocket.OPEN) {
        console.warn("[AliboardRealtime] socket niegotowy, patch odrzucony");
        return;
      }
      socket.send(
        JSON.stringify({
          type: "patch",
          patch,
        })
      );
    },

    sendSnapshot,

    sendCursor(data) {
      if (!data) return;
      const now = Date.now();
      if (now - lastCursorSentAt < CURSOR_THROTTLE_MS) return;
      lastCursorSentAt = now;
      sendCursorPayload({
        label: window.ALIBOARD_USER_LABEL || "Uczestnik",
        color: window.ALIBOARD_USER_COLOR || "#3b82f6",
        ...data,
      });
    },

    getPatchLog() {
      return patchLog.slice();
    },

    on(event, callback) {
      if (!listeners[event]) listeners[event] = [];
      listeners[event].push(callback);
      return () => {
        const idx = listeners[event].indexOf(callback);
        if (idx >= 0) listeners[event].splice(idx, 1);
      };
    },
  };

  window.AliboardRealtime = AliboardRealtime;
})();

