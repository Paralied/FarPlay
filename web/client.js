'use strict';
const $ = id => document.getElementById(id);
let socket, pc, channel, heartbeat, statsTimer, negotiating = false, ice = [], sessionTimer;
const status = text => { $('status').textContent = text; };
function send(payload) {
  if (channel?.readyState === 'open' && channel.bufferedAmount < 16384) channel.send(JSON.stringify(payload));
}
function release() { send({type:'release'}); document.querySelectorAll('.held').forEach(e => e.classList.remove('held')); }
function end(message='Disconnected. Your PC controls have been released.') {
  release(); clearInterval(heartbeat); clearInterval(statsTimer); clearTimeout(sessionTimer);
  const oldSocket=socket; socket=null;
  if (oldSocket?.readyState===WebSocket.OPEN) oldSocket.send(JSON.stringify({type:'stop'}));
  oldSocket?.close(); channel?.close(); channel=null;
  const oldPC=pc; pc=null; oldPC?.close();
  $('video').srcObject=null; $('session').hidden=true; $('setup').hidden=false;
  $('connect').disabled=false; $('badge').textContent='OFFLINE'; negotiating=false; status(message);
}
async function gather(connection) {
  if(connection.iceGatheringState==='complete') return;
  await new Promise((resolve,reject)=>{
    const timeout=setTimeout(()=>{connection.removeEventListener('icegatheringstatechange',check);reject(new Error('Network discovery timed out. Check the relay configuration.'));},30000);
    function check(){if(connection.iceGatheringState==='complete'){clearTimeout(timeout);connection.removeEventListener('icegatheringstatechange',check);resolve();}}
    connection.addEventListener('icegatheringstatechange',check); check();
  });
}
async function startStream() {
  if (negotiating || pc) return;
  negotiating=true; status('Connecting to your PC…');
  const connection=new RTCPeerConnection({iceServers:ice,iceTransportPolicy:$('relay').checked?'relay':'all'});
  pc=connection;
  sessionTimer=setTimeout(()=>end('Connection timed out. Check PC status and TURN relay settings.'),60000);
  connection.addTransceiver('video',{direction:'recvonly'});
  connection.addTransceiver('audio',{direction:'recvonly'});
  channel=connection.createDataChannel('controls',{ordered:true});
  channel.onopen=()=>{
    if(pc!==connection)return;
    heartbeat=setInterval(()=>send({type:'ping',at:Date.now()}),400);
  };
  channel.onmessage=event=>{
    const data=JSON.parse(event.data);
    if(data.type==='pong')$('stats').textContent=`${Date.now()-data.at} ms · control RTT`;
  };
  channel.onclose=()=>{if(pc===connection)end('Control connection closed. Reconnect to resume.');};
  const media=new MediaStream(); $('video').srcObject=media;
  connection.ontrack=event=>{media.addTrack(event.track);$('video').play().catch(()=>{});};
  connection.onconnectionstatechange=()=>{
    if(pc!==connection)return;
    if(connection.connectionState==='connected'){
      clearTimeout(sessionTimer);$('session').hidden=false;$('setup').hidden=true;
      $('video').play().catch(()=>{});
      statsTimer=setInterval(async()=>{
        if(pc!==connection)return;
        const reports=await connection.getStats();
        reports.forEach(r=>{if(r.type==='inbound-rtp'&&r.kind==='video')$('video').title=`${r.frameWidth||0} × ${r.frameHeight||0} · ${r.framesPerSecond||0} FPS`;});
      },2000);
    }
    if(['failed','disconnected'].includes(connection.connectionState))end('Connection lost. Tap Connect to try again.');
  };
  await connection.setLocalDescription(await connection.createOffer());
  await gather(connection);
  if(pc!==connection || socket?.readyState!==WebSocket.OPEN)return;
  socket.send(JSON.stringify({type:'offer',sdp:connection.localDescription.sdp,width:Number($('quality').value)}));
}
$('connect').onclick=()=>{
  if(!window.isSecureContext){status('Open your service over HTTPS.');return;}
  const token=$('token').value.trim();
  if(token.length<32){status('Paste your phone key from service setup.');return;}
  $('connect').disabled=true;status('Finding your PC…');
  socket=new WebSocket(`${location.protocol==='https:'?'wss:':'ws:'}//${location.host}/ws`);
  const current=socket;
  current.onopen=()=>current.send(JSON.stringify({role:'phone',token}));
  current.onmessage=async event=>{
    if(socket!==current)return;
    try{
      const data=JSON.parse(event.data);
      if(data.type==='ready'){
        ice=data.iceServers;$('badge').textContent='PAIRED';
        if(data.peerOnline)await startStream();else status('Paired. Waiting for your PC host to start…');
      }else if(data.type==='peer-online'){ice=data.iceServers||ice;await startStream();}
      else if(data.type==='answer'&&pc)await pc.setRemoteDescription({type:'answer',sdp:data.sdp});
      else if(data.type==='peer-offline')end('Your PC host disconnected.');
    }catch(error){end(error.message);}
  };
  current.onclose=event=>{if(socket===current)end(event.code===1008?'Key rejected or another phone is connected.':'Connection service unavailable. Check its address and internet connection.');};
  current.onerror=()=>{if(socket===current)end('Cannot reach the connection service.');};
};
$('leave').onclick=()=>end();
$('sound').onclick=()=>{$('video').muted=false;$('video').play().catch(()=>{});};
$('full').onclick=async()=>{try{await $('session').requestFullscreen();await screen.orientation?.lock('landscape');}catch{}};
$('keyboard').onclick=()=>{
  release();const text=prompt('Type into the focused PC field (open Minecraft chat with T first):');
  if(text)send({type:'text',text:text.slice(0,200)});
};
for(const button of document.querySelectorAll('[data-key],[data-button]')){
  let pointer=null;
  const payload=down=>({type:button.dataset.key?'key':'button',key:button.dataset.key||button.dataset.button,down});
  button.onpointerdown=event=>{
    event.preventDefault();if(pointer!==null)return;pointer=event.pointerId;
    button.setPointerCapture(pointer);button.classList.add('held');send(payload(true));
  };
  const up=event=>{if(pointer!==event.pointerId)return;pointer=null;button.classList.remove('held');send(payload(false));};
  button.onpointerup=up;button.onpointercancel=up;button.onlostpointercapture=up;
}
let lookPointer=null, lastX=0,lastY=0;
$('look').onpointerdown=e=>{if(lookPointer!==null)return;lookPointer=e.pointerId;lastX=e.clientX;lastY=e.clientY;$('look').setPointerCapture(e.pointerId);};
$('look').onpointermove=e=>{if(e.pointerId!==lookPointer)return;send({type:'move',x:(e.clientX-lastX)*2,y:(e.clientY-lastY)*2});lastX=e.clientX;lastY=e.clientY;};
$('look').onpointerup=$('look').onpointercancel=()=>{lookPointer=null;};
window.addEventListener('blur',release);
document.addEventListener('visibilitychange',()=>{if(document.hidden)end('Stream paused because the app went into the background.');});
window.addEventListener('pagehide',()=>end());
window.addEventListener('contextmenu',e=>{if(!$('session').hidden)e.preventDefault();});
const keyMap={KeyW:'w',KeyA:'a',KeyS:'s',KeyD:'d',Space:'space',ShiftLeft:'shift',ControlLeft:'ctrl',KeyE:'e',KeyT:'t',Escape:'escape',Enter:'enter',Backspace:'backspace'};
for(let i=1;i<=9;i++)keyMap['Digit'+i]=String(i);
for(const type of ['keydown','keyup'])window.addEventListener(type,e=>{
  if($('session').hidden||!keyMap[e.code]||e.repeat)return;
  e.preventDefault();send({type:'key',key:keyMap[e.code],down:type==='keydown'});
});
