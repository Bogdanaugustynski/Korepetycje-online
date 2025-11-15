// panel/static/js/aliboard_sync.js
(function () {
  // Bez room_id nie ma co robić
  const roomId = window.ALIBOARD_ROOM_ID;
  if (!roomId) {
    console.warn("Aliboard Sync: brak window.ALIBOARD_ROOM_ID – pomijam WebSocket.");
    return;
  }

  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  const wsUrl = scheme + "://" + window.location.host + "/ws/aliboard/" + roomId + "/";

  // Unikalny identyfikator klienta (żeby nie rysować własnych echo)
  const clientId =
    (window.crypto && window.crypto.randomUUID && window.crypto.randomUUID()) ||
    ("c_" + Math.random().toString(36).slice(2));

  let socket = null;

  function connect() {
    try {
      socket = new WebSocket(wsUrl);
    } catch (e) {
      console.error("Aliboard Sync: błąd tworzenia WebSocket", e);
      return;
    }

    socket.onopen = function () {
      console.log("Aliboard Sync: połączono z", wsUrl);
    };

    socket.onclose = function () {
      console.warn("Aliboard Sync: rozłączono, spróbuję ponownie za 3s");
      setTimeout(connect, 3000);
    };

    socket.onerror = function (err) {
      console.error("Aliboard Sync: błąd WebSocket", err);
    };

    socket.onmessage = function (event) {
      let data;
      try {
        data = JSON.parse(event.data);
      } catch (e) {
        console.warn("Aliboard Sync: niepoprawny JSON", event.data);
        return;
      }

      if (!data || data.clientId === clientId) {
        // moje echo – ignoruj
        return;
      }

      if (data.type === "stroke" && data.stroke) {
        // Rysowanie zdalnej kreski – obsługiwane w głównym skrypcie tablicy
        if (window.aliboardDrawRemoteStroke) {
          window.aliboardDrawRemoteStroke(data.stroke);
        } else {
          console.warn("Aliboard Sync: brak window.aliboardDrawRemoteStroke");
        }
      }
    };
  }

  connect();

  // Funkcja wywoływana z głównego skryptu tablicy,
  // kiedy lokalnie zakończymy rysowanie jednej kreski.
  window.aliboardSendStroke = function (stroke) {
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      console.warn("Aliboard Sync: socket nie gotowy, stroke nie wysłany");
      return;
    }
    try {
      socket.send(
        JSON.stringify({
          type: "stroke",
          stroke: stroke,
          clientId: clientId,
        })
      );
    } catch (e) {
      console.error("Aliboard Sync: błąd wysyłania stroke", e);
    }
  };
})();

