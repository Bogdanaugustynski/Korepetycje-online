// panel/static/js/aliboard_realtime.js
// Warstwa realtime (snapshot + patch) dla Aliboard

(function () {
  const rootEl = document.getElementById("aliboard-root") || document.body;
  const roomId = rootEl?.getAttribute("data-room-id");

  if (!roomId) {
    console.warn("[AliboardRealtime] Brak data-room-id – realtime wyłączony");
    return;
  }

  const loc = window.location;
  const wsScheme = loc.protocol === "https:" ? "wss" : "ws";
  const wsPath = `${wsScheme}://${loc.host}/ws/aliboard/${roomId}/`;

  let socket = null;
  let reconnectTimeout = null;

  const listeners = {
    patch: [],
    sync: [],
  };

  function getBoardStateOrNull() {
    if (typeof window.aliboardExportState !== "function") {
      return null;
    }
    try {
      return window.aliboardExportState();
    } catch (err) {
      console.warn("[AliboardRealtime] aliboardExportState error", err);
      return null;
    }
  }

  function sendSnapshot() {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    const state = getBoardStateOrNull();
    if (!state) return;
    socket.send(
      JSON.stringify({
        type: "snapshot",
        state,
      })
    );
  }

  function notifyListeners(type, payload) {
    const list = listeners[type] || [];
    list.forEach((cb) => {
      try {
        cb(payload);
      } catch (err) {
        console.error("[AliboardRealtime] listener error", err);
      }
    });
  }

  function connect() {
    socket = new WebSocket(wsPath);

    socket.onopen = function () {
      console.log("[AliboardRealtime] Połączono", wsPath);
      sendSnapshot();
    };

    socket.onclose = function () {
      console.warn("[AliboardRealtime] Rozłączono – próba ponownego połączenia…");
      if (reconnectTimeout) clearTimeout(reconnectTimeout);
      reconnectTimeout = setTimeout(connect, 2000);
    };

    socket.onerror = function (err) {
      console.error("[AliboardRealtime] Błąd WebSocket", err);
    };

    socket.onmessage = function (event) {
      let data;
      try {
        data = JSON.parse(event.data);
      } catch (e) {
        console.warn("[AliboardRealtime] Niepoprawny JSON", event.data);
        return;
      }

      if (data.type === "sync") {
        notifyListeners("sync", data.state || {});
        if (typeof window.aliboardImportState === "function") {
          window.aliboardImportState(data.state || {});
        }
      } else if (data.type === "patch") {
        notifyListeners("patch", data.patch || {});
        if (typeof window.aliboardApplyPatch === "function") {
          window.aliboardApplyPatch(data.patch || {});
        }
      }
    };
  }

  connect();

  const AliboardRealtime = {
    broadcastPatch(patch) {
      if (!socket || socket.readyState !== WebSocket.OPEN) {
        console.warn("[AliboardRealtime] Socket niegotowy – odrzucono patch");
        return;
      }
      socket.send(
        JSON.stringify({
          type: "patch",
          patch,
        })
      );
    },

    onPatch(callback) {
      if (typeof callback === "function") {
        listeners.patch.push(callback);
      }
    },

    onSync(callback) {
      if (typeof callback === "function") {
        listeners.sync.push(callback);
      }
    },

    sendSnapshot,
  };

  window.AliboardRealtime = AliboardRealtime;
})();
