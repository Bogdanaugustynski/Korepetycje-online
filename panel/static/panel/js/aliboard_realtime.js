// panel/static/js/aliboard_realtime.js
// Prosta warstwa realtime dla Aliboard (CRDT v1 – operacje stroke)

(function () {
  // Szukamy room_id z atrybutu data-room-id na <body> lub elemencie tablicy
  const roomAttrEl =
    document.getElementById("aliboard-root") ||
    document.body;

  const roomId = roomAttrEl.getAttribute("data-room-id");
  if (!roomId) {
    console.warn("[AliboardRealtime] Brak data-room-id – realtime wyłączony");
    return;
  }

  // Unikalny identyfikator klienta (do rozróżniania siebie vs innych)
  const senderId = "client-" + Math.random().toString(36).slice(2);

  // Adres WebSocket – obsługa http/https -> ws/wss
  const loc = window.location;
  const wsScheme = loc.protocol === "https:" ? "wss" : "ws";
  const wsPath = `${wsScheme}://${loc.host}/ws/aliboard/${roomId}/`;

  let socket = null;
  let reconnectTimeout = null;

  const listeners = {
    patch: [], // callbacki, które dostaną każdą operację z serwera
  };

  function connect() {
    socket = new WebSocket(wsPath);

    socket.onopen = function () {
      console.log("[AliboardRealtime] Połączono", wsPath);
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

      // Ignorujemy własne wiadomości (żeby nie dublować rysowania)
      if (data.sender_id && data.sender_id === senderId) return;

      if (data.type === "patch") {
        listeners.patch.forEach((cb) => cb(data.payload));
      }
    };
  }

  connect();

  const AliboardRealtime = {
    // wysyłanie operacji (patchy) na serwer
    broadcastPatch(patch) {
      const msg = {
        type: "patch",
        sender_id: senderId,
        payload: patch,
      };
      if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify(msg));
      } else {
        console.warn("[AliboardRealtime] Socket niegotowy – odrzucono patch");
      }
    },

    // rejestracja callbacka na każdą zdalną operację
    onPatch(callback) {
      if (typeof callback === "function") {
        listeners.patch.push(callback);
      }
    },
  };

  // Udostępniamy globalnie
  window.AliboardRealtime = AliboardRealtime;
})();

