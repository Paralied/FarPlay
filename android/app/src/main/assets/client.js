'use strict';
const $=id=>document.getElementById(id);
let pc=null, channel=null, heartbeat=null, sessionTimer=null, mode='idle', audio=null, audioNext=0, epoch=0;
const status=text=>{$('status').textContent=text;};
const signal=payload=>window.FarPlay.signal(JSON.stringify(payload));
function send(payload){
  if(mode==='compatibility')signal({type:'input',payload});
  else if(channel?.readyState==='open'&&channel.bufferedAmount<16384)channel.send(JSON.stringify(payload));
}
function release(){send({type:'release'});document.querySelectorAll('.held').forEach(e=>e.classList.remove('held'));}
function end(message='Disconnected. Tap Connect when you are ready.'){
  epoch++;release();clearInterval(heartbeat);clearTimeout(sessionTimer);heartbeat=null;mode='idle';
  const previous=pc;pc=null;channel=null;previous?.close();
  window.FarPlay.disconnectPC();
  $('video').srcObject=null;$('session').hidden=true;$('setup').hidden=false;
  $('connect').disabled=false;$('badge').textContent='PAIRED';status(message);
  if(audio){audio.close().catch(()=>{});audio=null;}audioNext=0;
}
function showSession(){
  clearTimeout(sessionTimer);$('session').hidden=false;$('setup').hidden=true;
  $('video').hidden=mode==='compatibility';$('compat').hidden=mode!=='compatibility';
}
function sound(){
  if(!audio)audio=new (window.AudioContext||window.webkitAudioContext)({sampleRate:48000});
  audio.resume().catch(()=>{});$('video').muted=false;$('video').play().catch(()=>{});
}
function compatibility(){
  if(mode==='idle'||mode==='compatibility'||mode==='switching')return;
  mode='switching';const old=pc;pc=null;channel=null;old?.close();
  clearTimeout(sessionTimer);status('Trying direct compatibility mode…');
  signal({type:'compatibility'});
  sessionTimer=setTimeout(()=>end('Your PC could not start streaming. Check the PC host window.'),10000);
}
async function startStream(){
  if(mode!=='connecting')return;
  const generation=epoch;
  const connection=new RTCPeerConnection({iceServers:[],bundlePolicy:'max-bundle'});pc=connection;
  connection.addTransceiver('video',{direction:'recvonly'});connection.addTransceiver('audio',{direction:'recvonly'});
  channel=connection.createDataChannel('controls',{ordered:true});
  channel.onclose=()=>{if(pc===connection)compatibility();};
  const media=new MediaStream();$('video').srcObject=media;
  connection.ontrack=e=>{if(pc===connection){media.addTrack(e.track);$('video').play().catch(()=>{});}};
  connection.onconnectionstatechange=()=>{
    if(pc!==connection)return;
    if(connection.connectionState==='connected'){mode='rtc';showSession();$('stats').textContent='Direct video';}
    else if(['failed','disconnected'].includes(connection.connectionState))compatibility();
  };
  sessionTimer=setTimeout(compatibility,10000);
  await connection.setLocalDescription(await connection.createOffer());
  if(connection.iceGatheringState!=='complete')await new Promise(resolve=>{
    const timer=setTimeout(done,2000);
    function done(){clearTimeout(timer);connection.removeEventListener('icegatheringstatechange',check);resolve();}
    function check(){if(connection.iceGatheringState==='complete')done();}
    connection.addEventListener('icegatheringstatechange',check);check();
  });
  if(epoch!==generation||pc!==connection)return;
  signal({type:'offer',sdp:connection.localDescription.sdp,width:Number($('quality').value)});
}
async function packet(base64){
  if(mode!=='compatibility')return;
  const gen=epoch;
  const raw=atob(base64);const bytes=new Uint8Array(raw.length);
  for(let i=0;i<raw.length;i++)bytes[i]=raw.charCodeAt(i);
  if(bytes[0]===1){
    try{
      const frame=await createImageBitmap(new Blob([bytes.subarray(1)],{type:'image/jpeg'}));
      if(gen===epoch&&mode==='compatibility'){
        const canvas=$('compat');if(canvas.width!==frame.width)canvas.width=frame.width;if(canvas.height!==frame.height)canvas.height=frame.height;
        canvas.getContext('2d',{alpha:false}).drawImage(frame,0,0);showSession();
      }
      frame.close();
    }finally{if(gen===epoch&&mode==='compatibility')signal({type:'frame-ack'});}
  }else if(bytes[0]===2&&audio?.state==='running'){
    const view=new DataView(bytes.buffer,1);const length=Math.floor(view.byteLength/4);if(!length)return;
    if(audioNext>audio.currentTime+.2)return;
    const buffer=audio.createBuffer(2,length,48000);
    for(let c=0;c<2;c++){const target=buffer.getChannelData(c);for(let i=0;i<length;i++)target[i]=view.getInt16(i*4+c*2,true)/32768;}
    const source=audio.createBufferSource();source.buffer=buffer;source.connect(audio.destination);
    audioNext=Math.max(audioNext,audio.currentTime+.025);source.start(audioNext);audioNext+=buffer.duration;
  }
}
window.onNative=async(type,data)=>{
  try{
    if(type==='saved'){
      $('pairing').hidden=data.paired;$('paired-options').hidden=!data.paired;$('connect').hidden=!data.paired;
      $('pc-name').textContent=data.name;$('badge').textContent=data.paired?'PAIRED':'NOT PAIRED';
    }else if(type==='paired'){$('pair-code').value='';status(data);}
    else if(type==='error'||type==='closed'){end(data);}
    else if(type==='packet'){await packet(data);}
    else if(type==='message'){
      if(mode==='idle')return;
      if(data.type==='ready'){
        clearTimeout(sessionTimer);
        heartbeat=setInterval(()=>{signal({type:'ping',at:Date.now()});send({type:'ping',at:Date.now()});},400);
        await startStream();
      }else if(data.type==='answer'&&pc)await pc.setRemoteDescription({type:'answer',sdp:data.sdp});
      else if(data.type==='compatibility'){mode='compatibility';$('stats').textContent='Direct compatibility · up to 20 FPS';}
      else if(data.type==='pong')$('stats').textContent=`${mode==='compatibility'?'Direct compatibility':'Direct video'} · ${Date.now()-data.at} ms`;
    }
  }catch(e){end('Connection interrupted: '+e.message);}
};
$('scan').onclick=()=>window.FarPlay.scan();
$('pair-paste').onclick=()=>{status('Pairing with your PC…');window.FarPlay.pairCode($('pair-code').value.trim());};
$('forget').onclick=()=>{end();window.FarPlay.forget();status('Scan a pairing code to add a PC.');};
$('connect').onclick=()=>{
  end();mode='connecting';$('connect').disabled=true;status('Connecting directly to your PC…');
  sound();window.FarPlay.connectPC();
  sessionTimer=setTimeout(()=>end('PC unreachable. Check that FarPlay is open on your PC.'),15000);
};
$('leave').onclick=()=>end();
$('sound').onclick=sound;
$('full').onclick=async()=>{try{await $('session').requestFullscreen();await screen.orientation?.lock('landscape');}catch{}};
$('keyboard').onclick=()=>{release();const text=prompt('Type into the focused PC field (open Minecraft chat first):');if(text)send({type:'text',text:text.slice(0,200)});};
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
