// static/js/aliboard_sync.js
(function(){
  const cfg = window.ALIBOARD_CONFIG || {};
  const roomId = cfg.roomId || 'local-test';
  const base = (cfg.wsBase || `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws/aliboard/`).replace(/\/+$/, '');
  const wsUrl = `${base}/${roomId}/`;

  function randomId(){
    if(window.crypto?.getRandomValues){
      const buf = new Uint8Array(16);
      window.crypto.getRandomValues(buf);
      return Array.from(buf).map(b=>b.toString(16).padStart(2,'0')).join('');
    }
    return `local-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  const clientId = randomId();
  const listeners = new Set();
  let socket = null;
  let queue = [];

  function flush(){
    if(!socket || socket.readyState !== WebSocket.OPEN) return;
    while(queue.length){ socket.send(queue.shift()); }
  }

  function notify(data){
    listeners.forEach(fn=>{
      try{ fn(data); }
      catch(err){ console.error('[Aliboard Sync] listener error', err); }
    });
  }

  function connect(){
    try{
      socket = new WebSocket(wsUrl);
    }catch(err){
      console.error('[Aliboard Sync] WebSocket init failed', err);
      return;
    }
    socket.addEventListener('open', ()=>{
      console.info('[Aliboard Sync] connected');
      flush();
    });
    socket.addEventListener('message', (event)=>{
      let data = null;
      try{ data = JSON.parse(event.data); }
      catch(_){ return; }
      if(!data || data.clientId === clientId) return;
      notify(data);
    });
    socket.addEventListener('close', ()=>{
      console.warn('[Aliboard Sync] disconnected, retrying...');
      setTimeout(connect, 2000);
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
    console.warn('[Aliboard Sync] roomId missing  WebSocket disabled');
  }

  window.ALIBOARD_SYNC = {
    clientId,
    send,
    onMessage,
    status: ()=> socket ? socket.readyState : WebSocket.CLOSED
  };
})();
