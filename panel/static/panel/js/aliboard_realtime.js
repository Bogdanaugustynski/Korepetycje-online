// panel/static/panel/js/aliboard_realtime.js
(function () {
  const root = document.getElementById("aliboard-root") || document.body;
  const roomId = root?.getAttribute("data-room-id");
  if (!roomId) {
    console.warn("[AliboardRealtime] brak room-id, realtime wyłączony");
    return;
  }

  const clientId =
    (window.crypto?.randomUUID && window.crypto.randomUUID()) ||
    `client-${Date.now()}-${Math.random().toString(16).slice(2)}`;

  let socket = null;
  let reconnectTimer = null;
  let cursorThrottleStamp = 0;
  const CURSOR_THROTTLE_MS = 80;
  const messageQueue = [];

  const loc = window.location;
  const scheme = loc.protocol === "https:" ? "wss" : "ws";
  const wsUrl = `${scheme}://${loc.host}/ws/aliboard/${roomId}/`;

  const listeners = {
    snapshot: [],
    element_add: [],
    element_update: [],
    element_remove: [],
    cursor: [],
    open: [],
    close: [],
    chat_message: [],
    call_signal: [],
  };

  function notify(event, payload) {
    (listeners[event] || []).forEach((cb) => {
      try {
        cb(payload);
      } catch (err) {
        console.error("[AliboardRealtime] listener error", err);
      }
    });
  }

  function enqueue(payload) {
    messageQueue.push(JSON.stringify(payload));
  }

  function flushQueue() {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    while (messageQueue.length) {
      socket.send(messageQueue.shift());
    }
  }

  function send(payload) {
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      enqueue(payload);
      return;
    }
    socket.send(JSON.stringify(payload));
  }

  function connect() {
    try {
      socket = new WebSocket(wsUrl);
    } catch (err) {
      console.error("[AliboardRealtime] nie udało się utworzyć WebSocket", err);
      scheduleReconnect();
      return;
    }

    // Integracja czatu z WebSocketem
    window.aliboardChat = window.aliboardChat || {};
    window.aliboardVoice = window.aliboardVoice || {};
    window.aliboardChat.sendToServer = function (text) {
      if (!text || !text.trim()) return;
      if (!socket || socket.readyState !== WebSocket.OPEN) return;
      const payload = {
        type: "chat_message",
        text: text.trim().slice(0, 500),
        author_role: window.ALIBOARD_USER_ROLE || "unknown",
      };
      socket.send(JSON.stringify(payload));
    };
    window.aliboardChat.sendCallSignal = function (action) {
      if (!socket || socket.readyState !== WebSocket.OPEN) return;
      socket.send(
        JSON.stringify({
          type: "call_signal",
          action: action || "ring",
          from_id: window.ALIBOARD_USER_ID,
          from_role: window.ALIBOARD_USER_ROLE || "unknown",
        })
      );
    };
    window.aliboardVoice.sendSignal = function (payload) {
      if (!payload || typeof payload !== "object" || !payload.type) return;
      send({
        ...payload,
      });
    };

    socket.onopen = function () {
      console.info("[AliboardRealtime] połączono", wsUrl);
      flushQueue();
      notify("open");
    };

    socket.onclose = function () {
      console.warn("[AliboardRealtime] rozłączono – ponawiam próbę…");
      notify("close");
      scheduleReconnect();
    };

    socket.onerror = function (err) {
      console.error("[AliboardRealtime] błąd WebSocket", err);
    };

    socket.onmessage = function (event) {
      let data;
      try {
        data = JSON.parse(event.data);
      } catch (e) {
        console.warn("[AliboardRealtime] niepoprawny JSON", event.data);
        return;
      }

      if (data.type === "call_signal") {
        if (
          window.aliboardChat &&
          typeof window.aliboardChat.onCallSignal === "function"
        ) {
          window.aliboardChat.onCallSignal(data);
        }
        notify("call_signal", data);
        return;
      }

      if (data.type === "chat_message") {
        if (
          window.aliboardChat &&
          typeof window.aliboardChat.onServerMessage === "function"
        ) {
          const authorIdRaw = data.author_id;
          const authorId =
            typeof authorIdRaw === "number"
              ? authorIdRaw
              : authorIdRaw != null
              ? Number(authorIdRaw)
              : null;
          window.aliboardChat.onServerMessage(data.text || "", authorId);
        }
        notify("chat_message", data);
        return;
      }

      if (data.type === "webrtc_offer") {
        if (
          window.aliboardVoice &&
          typeof window.aliboardVoice.onOffer === "function"
        ) {
          window.aliboardVoice.onOffer(data);
        }
        return;
      }

      if (data.type === "webrtc_answer") {
        if (
          window.aliboardVoice &&
          typeof window.aliboardVoice.onAnswer === "function"
        ) {
          window.aliboardVoice.onAnswer(data);
        }
        return;
      }

      if (data.type === "webrtc_ice_candidate") {
        if (
          window.aliboardVoice &&
          typeof window.aliboardVoice.onIceCandidate === "function"
        ) {
          window.aliboardVoice.onIceCandidate(data);
        }
        return;
      }

      if (data.type === "snapshot") {
        notify("snapshot", data.elements || []);
      } else if (data.type === "element_add") {
        notify("element_add", data.element || null);
      } else if (data.type === "element_update") {
        notify("element_update", data.element || null);
      } else if (data.type === "element_remove") {
        notify("element_remove", data.id || data.element || null);
      } else if (data.type === "cursor") {
        notify("cursor", data.cursor || null);
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

  const api = {
    clientId,
    on(event, handler) {
      if (!listeners[event]) listeners[event] = [];
      listeners[event].push(handler);
      return () => {
        const idx = listeners[event].indexOf(handler);
        if (idx >= 0) listeners[event].splice(idx, 1);
      };
    },
    broadcastElementAdd(element) {
      if (!element || !element.id) return;
      send({ type: "element_add", element });
    },
    broadcastElementUpdate(element) {
      if (!element || !element.id) return;
      send({ type: "element_update", element });
    },
    broadcastElementRemove(id) {
      if (!id) return;
      send({ type: "element_remove", id });
    },
    sendCursor(cursor) {
      if (!cursor) return;
      const now = Date.now();
      if (now - cursorThrottleStamp < CURSOR_THROTTLE_MS) return;
      cursorThrottleStamp = now;
      send({
        type: "cursor",
        cursor: {
          id: clientId,
          label: window.ALIBOARD_USER_LABEL || "Uczestnik",
          color: window.ALIBOARD_USER_COLOR || "#3b82f6",
          ...cursor,
        },
      });
    },
    sendChatMessage(text) {
      if (!text) return;
      const payload =
        typeof text === "string" ? text : text?.toString?.() || "";
      if (!payload) return;
      send({
        type: "chat_message",
        text: payload,
      });
    },
    sendCallSignal(action) {
      send({
        type: "call_signal",
        action: action || "ring",
        from_id: window.ALIBOARD_USER_ID,
        from_role: window.ALIBOARD_USER_ROLE || "unknown",
      });
    },
    sendChatPing() {
      send({ type: "chat_ping" });
    },
    sendChatMicState(isMuted) {
      send({ type: "chat_mic_state", muted: !!isMuted });
    },
  };

  window.AliboardRealtime = api;
})();
