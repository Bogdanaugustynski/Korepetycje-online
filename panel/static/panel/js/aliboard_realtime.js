// panel/static/panel/js/aliboard_realtime.js
(function () {
  // Ustal roomId: global -> data-room-id -> query -> fallback
  let roomId = null;
  if (window.ALIBOARD_ROOM_ID) {
    roomId = window.ALIBOARD_ROOM_ID;
  }
  if (!roomId) {
    const root = document.getElementById("aliboard-root") || document.body;
    const dataVal = root?.getAttribute("data-room-id") || root?.dataset?.roomId;
    if (dataVal) roomId = dataVal;
  }
  if (!roomId) {
    const qs = new URLSearchParams(window.location.search);
    roomId = qs.get("room") || qs.get("room_id") || "local-test";
  }
  window.ALIBOARD_ROOM_ID = roomId;

  const clientId =
    (window.crypto?.randomUUID && window.crypto.randomUUID()) ||
    `client-${Date.now()}-${Math.random().toString(16).slice(2)}`;

  let socket = null;
  let reconnectTimer = null;
  let cursorThrottleStamp = 0;
  const CURSOR_THROTTLE_MS = 80;
  const messageQueue = [];

  // Legacy grid sync potrafił przywracać stary szablon kratki. Wyłączone domyślnie dla wariantu 5".
  const ALLOW_GRID_STATE_SYNC = false;

  const loc = window.location;
  const scheme = loc.protocol === "https:" ? "wss" : "ws";
  const wsUrl = `${scheme}://${loc.host}/ws/aliboard/${roomId}/`;

  const listeners = {
    snapshot: [],
    element_add: [],
    element_update: [],
    element_remove: [],
    cursor: [],
    grid_state: [],
    open: [],
    close: [],
    chat_message: [],
    call_signal: [],
    chat_read: [],
    chat_read_state: [],
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

  // Alias ułatwiający wysyłkę dowolnych typów (presence, audio_mode itp.)
  function sendTyped(payload) {
    send(payload);
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
    window.aliboardChat.sendChatRead = function (lastMessageId) {
      if (lastMessageId === undefined || lastMessageId === null) return;
      const idNum = Number(lastMessageId);
      if (!Number.isFinite(idNum)) return;
      send({
        type: "chat_read",
        last_message_id: idNum,
      });
    };
    window.aliboardChat.sendCallSignal = function (action) {
      if (!socket || socket.readyState !== WebSocket.OPEN) return;
      const mode = window.ALIBOARD_CALL_MODE || 1;
      const act = action || "ring";
      const base = {
        room_id: roomId,
        from_id: window.ALIBOARD_USER_ID,
        from_role: window.ALIBOARD_USER_ROLE || "unknown",
        mode,
      };
      // nowe sygnały voice:*
      send({
        ...base,
        type: act === "end" ? "voice:end" : "voice:ring",
      });
      // zgodność wstecz: call_signal
      socket.send(
        JSON.stringify({
          ...base,
          type: "call_signal",
          action: act,
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

      console.debug("[RT] recv", data.type, data);

      if (data.type === "presence:update") {
        notify("presence", data);
        return;
      }

      if (data.type === "audio_mode") {
        notify("audio_mode", data);
        window.ALIBOARD_CALL_MODE = data.mode || 1;
        return;
      }

      if (data.type === "voice:ring") {
        if (
          window.aliboardChat &&
          typeof window.aliboardChat.onCallSignal === "function"
        ) {
          window.aliboardChat.onCallSignal(data);
        }
        notify("call_signal", data);
        return;
      }

      if (data.type === "voice:offer") {
        if (
          window.aliboardVoice &&
          typeof window.aliboardVoice.onOffer === "function"
        ) {
          window.aliboardVoice.onOffer(data);
        }
        return;
      }

      if (data.type === "voice:answer") {
        if (
          window.aliboardVoice &&
          typeof window.aliboardVoice.onAnswer === "function"
        ) {
          window.aliboardVoice.onAnswer(data);
        }
        return;
      }

      if (data.type === "voice:ice") {
        if (
          window.aliboardVoice &&
          typeof window.aliboardVoice.onIceCandidate === "function"
        ) {
          window.aliboardVoice.onIceCandidate(data);
        }
        return;
      }

      if (data.type === "voice:end" || data.type === "voice:busy") {
        if (
          window.aliboardChat &&
          typeof window.aliboardChat.onCallSignal === "function"
        ) {
          window.aliboardChat.onCallSignal(data);
        }
        notify("call_signal", data);
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

      if (data.type === "grid_state") {
        if (ALLOW_GRID_STATE_SYNC) {
          if (typeof window.aliboardApplyGridState === "function") {
            window.aliboardApplyGridState({
              gridSize: data.gridSize,
              kind: data.kind,
            });
          }
          notify("grid_state", data);
        }
        return;
      }

      if (data.type === "chat_read") {
        if (
          window.aliboardChat &&
          typeof window.aliboardChat.onChatRead === "function"
        ) {
          window.aliboardChat.onChatRead(data);
        }
        notify("chat_read", data);
        return;
      }

      if (data.type === "chat_read_state") {
        if (
          window.aliboardChat &&
          typeof window.aliboardChat.onChatReadState === "function"
        ) {
          window.aliboardChat.onChatReadState(data);
        }
        notify("chat_read_state", data);
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
          const authorName = data.author_name || null;
          window.aliboardChat.onServerMessage(
            data.text || "",
            authorId,
            authorName,
            data.created_at,
            data.id,
            data.is_history
          );
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
    send: sendTyped,
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
    // --- SYNC kratki (grid) ---
    sendGridState(state) {
      if (!ALLOW_GRID_STATE_SYNC) return;
      if (!state) return;
      const isObj = typeof state === "object";
      const rawSize = isObj ? state.gridSize : state;
      const kind = isObj ? state.kind : "grid";
      send({
        type: "grid_state",
        gridSize: rawSize,
        kind: kind || "grid",
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
    sendChatRead(lastMessageId) {
      if (lastMessageId === undefined || lastMessageId === null) return;
      const idNum = Number(lastMessageId);
      if (!Number.isFinite(idNum)) return;
      send({
        type: "chat_read",
        last_message_id: idNum,
      });
    },
    sendCallSignal(action) {
      const mode = window.ALIBOARD_CALL_MODE || 1;
      const act = action || "ring";
      const base = {
        room_id: roomId,
        from_id: window.ALIBOARD_USER_ID,
        from_role: window.ALIBOARD_USER_ROLE || "unknown",
        mode,
      };
      send({
        ...base,
        type: act === "end" ? "voice:end" : "voice:ring",
      });
      send({
        ...base,
        type: "call_signal",
        action: act,
      });
    },
    sendChatPing() {
      send({ type: "chat_ping" });
    },
    sendChatMicState(isMuted) {
      send({ type: "chat_mic_state", muted: !!isMuted });
    },
    voiceOffer(to_id, sdp) {
      if (!to_id || !sdp) return;
      send({
        type: "voice:offer",
        room_id: roomId,
        from_id: window.ALIBOARD_USER_ID,
        to_id,
        sdp,
      });
    },
    voiceAnswer(to_id, sdp) {
      if (!to_id || !sdp) return;
      send({
        type: "voice:answer",
        room_id: roomId,
        from_id: window.ALIBOARD_USER_ID,
        to_id,
        sdp,
      });
    },
    voiceIce(to_id, candidate) {
      if (!to_id || !candidate) return;
      send({
        type: "voice:ice",
        room_id: roomId,
        from_id: window.ALIBOARD_USER_ID,
        to_id,
        candidate,
      });
    },
  };

  window.AliboardRealtime = api;
})();
