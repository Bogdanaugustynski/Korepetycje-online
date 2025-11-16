// panel/static/js/aliboard_sync.js

(function () {
  console.log("[Aliboard] init sync…");

  // 1. Ustalamy room_id
  let roomId = null;

  if (window.ALIBOARD_ROOM_ID) {
    roomId = window.ALIBOARD_ROOM_ID;
  } else {
    const root = document.querySelector("[data-room-id]");
    if (root) {
      roomId = root.dataset.roomId;
    }
  }

  if (!roomId) {
    console.warn("[Aliboard] brak roomId – używam local-test");
    roomId = "local-test";
  }

  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  const socketUrl = `${scheme}://${window.location.host}/ws/aliboard/${roomId}/`;

  console.log("[Aliboard] connecting to", socketUrl);

  const socket = new WebSocket(socketUrl);

  socket.onopen = function () {
    console.log("[Aliboard] WebSocket OPEN");
  };

  socket.onclose = function (event) {
    console.log(
      "[Aliboard] WebSocket CLOSE",
      "code:", event.code,
      "reason:", event.reason
    );
  };

  socket.onerror = function (event) {
    console.error("[Aliboard] WebSocket ERROR", event);
  };

  socket.onmessage = function (event) {
    try {
      const data = JSON.parse(event.data);
      if (data.type === "board.update") {
        console.log("[Aliboard] recv board.update");
        if (typeof window.applyRemoteBoardUpdate === "function") {
          window.applyRemoteBoardUpdate(data.payload);
        } else {
          console.warn(
            "[Aliboard] applyRemoteBoardUpdate nie jest zdefiniowane – update odebrany, ale nie ma jak go narysować."
          );
        }
      } else {
        console.log("[Aliboard] recv message", data);
      }
    } catch (e) {
      console.error("[Aliboard] błąd parsowania message", e, event.data);
    }
  };

  window.AliboardSync = {
    sendUpdate(payload) {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({
          type: "board.update",
          payload: payload,
        }));
      } else {
        console.warn(
          "[Aliboard] próba wysłania update, ale socket nie jest OPEN:",
          socket.readyState
        );
      }
    }
  };

})();

