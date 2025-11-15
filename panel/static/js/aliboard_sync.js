// static/js/aliboard_sync.js

(function(){
  const rawRoomId = window.ALIBOARD_ROOM_ID != null ? String(window.ALIBOARD_ROOM_ID).trim() : '';
  const roomId = rawRoomId || 'demo';
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const wsUrl = `${scheme}://${window.location.host}/ws/aliboard/${encodeURIComponent(roomId)}/`;

  function randomId(){
    if(window.crypto?.getRandomValues){
      const buf = new Uint8Array(16);
      window.crypto.getRandomValues(buf);
      return Array.from(buf).map(b => b.toString(16).padStart(2, '0')).join('');
    }
    return `local-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  const clientId = randomId();
  const listeners = new Set();
  let socket = null;
  let queue = [];
  let reconnectTimer = null;

  function flush(){
    if(!socket || socket.readyState !== WebSocket.OPEN) return;
    while(queue.length){ socket.send(queue.shift()); }
  }

  function notify(data){
    listeners.forEach(fn => {
      try{
        fn(data);
      }catch(err){
        console.error('[Aliboard Sync] listener error', err);
      }
    });
  }

  function scheduleReconnect(){
    if(reconnectTimer) return;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, 2000);
  }

  function connect(){
    try{
      socket = new WebSocket(wsUrl);
    }catch(err){
      console.error('[Aliboard Sync] WebSocket init failed', err);
      scheduleReconnect();
      return;
    }

    socket.addEventListener('open', ()=>{
      console.info('[Aliboard Sync] connected to room', roomId);
      flush();
    });

    socket.addEventListener('message', (event)=>{
      let data = null;
      try{
        data = JSON.parse(event.data);
      }catch(_err){
        console.warn('[Aliboard Sync] invalid payload skipped');
        return;
      }
      if(!data || data.clientId === clientId) return;
      notify(data);
    });

    socket.addEventListener('close', ()=>{
      console.warn('[Aliboard Sync] disconnected, retrying...');
      scheduleReconnect();
    });

    socket.addEventListener('error', (err)=>{
      console.error('[Aliboard Sync] socket error', err);
      socket.close();
    });
  }

  function send(payload){
    if(!payload || typeof payload !== 'object') return;
    const message = JSON.stringify({ clientId, ...payload });
    if(socket && socket.readyState === WebSocket.OPEN){
      socket.send(message);
    }else{
      queue.push(message);
    }
  }

  function onMessage(handler){
    if(typeof handler !== 'function') return ()=>{};
    listeners.add(handler);
    return ()=> listeners.delete(handler);
  }

  if(roomId){
    connect();
  }else{
    console.warn('[Aliboard Sync] roomId missing; realtime disabled');
  }

  window.ALIBOARD_SYNC = {
    clientId,
    send,
    onMessage,
    status: ()=> socket ? socket.readyState : WebSocket.CLOSED
  };
})();

