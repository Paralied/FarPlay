'use strict';
const $=id=>document.getElementById(id);
let lookChannel=null,lastVideoProgress=0;
let pc=null, channel=null, heartbeat=null, statsTimer=null, lastStats=null, renderedFrames=0, lastFrameCount=0, statTime=0, networkMs=0, streamInfo='', sessionTimer=null, mode='idle', audio=null, audioNext=0, epoch=0;
const status=text=>{$('status').textContent=text;};
const signal=payload=>window.FarPlay.signal(JSON.stringify(payload));
function send(payload){
  if(payload.type==='move'&&lookChannel?.readyState==='open'){if(lookChannel.bufferedAmount<1024)lookChannel.send(JSON.stringify(payload));return;}
  if(mode==='compatibility')signal({type:'input',payload});
  else if(channel?.readyState==='open'){
    // Drop stale motion before it can queue behind a busy network; keep releases reliable.
    if(['move','pointer'].includes(payload.type)&&channel.bufferedAmount>1024)return;
    if(channel.bufferedAmount<16384||payload.type==='release'||payload.down===false)channel.send(JSON.stringify(payload));
  }
}
function release(){send({type:'release'});resetControls();}
function end(message='Disconnected. Tap Connect when you are ready.'){
  epoch++;release();clearInterval(statsTimer);statsTimer=null;lastStats=null;renderedFrames=0;lastFrameCount=0;streamInfo='';closeMenu();composing=false;typingBusy=false;window.FarPlay.setPlaying(false);clearInterval(heartbeat);clearTimeout(sessionTimer);heartbeat=null;mode='idle';
  const previous=pc;pc=null;channel=null;lookChannel=null;previous?.close();
  window.FarPlay.disconnectPC();
  $('video').srcObject=null;$('session').hidden=true;$('setup').hidden=false;
  $('connect').disabled=false;$('badge').textContent='PAIRED';status(message);
  if(audio){audio.close().catch(()=>{});audio=null;}audioNext=0;
}
function showSession(){
  clearTimeout(sessionTimer);if($('session').hidden)window.FarPlay.setPlaying(true);$('session').hidden=false;$('setup').hidden=true;
  if(!statsTimer){lastVideoProgress=performance.now();statTime=performance.now();statsTimer=setInterval(updateStats,1000);}
  $('video').hidden=mode==='compatibility';$('compat').hidden=mode!=='compatibility';
}
function sound(){
  if(!audio)audio=new (window.AudioContext||window.webkitAudioContext)({sampleRate:48000});
  audio.resume().catch(()=>{});$('video').muted=false;$('video').play().catch(()=>{});
}
function compatibility(){
  if(mode==='idle'||mode==='compatibility'||mode==='switching')return;
  mode='switching';const old=pc;pc=null;channel=null;lookChannel=null;old?.close();
  clearTimeout(sessionTimer);status('Trying direct compatibility mode…');
  signal({type:'compatibility'});
  sessionTimer=setTimeout(()=>end('Your PC could not start streaming. Check the PC host window.'),10000);
}
async function startStream(){
  if(mode!=='connecting')return;
  const generation=epoch;
  const connection=new RTCPeerConnection({iceServers:[],bundlePolicy:'max-bundle'});pc=connection;
  const videoReceiver=connection.addTransceiver('video',{direction:'recvonly'});
  const audioReceiver=connection.addTransceiver('audio',{direction:'recvonly'});
  for(const transceiver of [videoReceiver,audioReceiver]){try{if('jitterBufferTarget' in transceiver.receiver)transceiver.receiver.jitterBufferTarget=0;}catch{}}
  // Prefer fast H.264 at <=720p30; retain VP8 for higher frame rates/resolutions.
  if(videoReceiver.setCodecPreferences){
    const codecs=RTCRtpReceiver.getCapabilities('video')?.codecs||[];
    const mime=Number($('frame-rate').value)===60||Number($('quality').value)>1280?'video/vp8':'video/h264';
    const preferred=codecs.filter(c=>c.mimeType.toLowerCase()===mime);
    if(preferred.length)videoReceiver.setCodecPreferences([...preferred,...codecs.filter(c=>c.mimeType.toLowerCase()!==mime)]);
  }
  channel=connection.createDataChannel('controls',{ordered:true});
  lookChannel=connection.createDataChannel('look',{ordered:false,maxRetransmits:0});
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
  signal({type:'offer',sdp:connection.localDescription.sdp,width:Number($('quality').value),fps:Number($('frame-rate').value)||30});
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
        canvas.getContext('2d',{alpha:false}).drawImage(frame,0,0);renderedFrames++;showSession();
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
    if(type==='controls'){applyPreferences(data);}
    else if(type==='composer-send'){await finishComposer(data,false);}
    else if(type==='composer-cancel'){await finishComposer(data,true);}
    else if(type==='back'){if(!$('settings-layer').hidden)closeMenu();else if(!$('session').hidden)openMenu();}
    else if(type==='saved'){
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
      else if(data.type==='compatibility'){mode='compatibility';$('stats').textContent='Compatibility · measuring FPS';}
      else if(data.type==='pong'){networkMs=Date.now()-data.at;renderStats();}
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
// Touch ownership prevents one thumb releasing a key still held by another input.
const keyOwners=new Map(), activePointers=new Map(), actionPositions=new Map();
let motionX=0,motionY=0,motionFrame=null;
function flushLook(){if(motionFrame!==null)cancelAnimationFrame(motionFrame);motionFrame=null;const x=Math.trunc(motionX),y=Math.trunc(motionY);motionX-=x;motionY-=y;if(x||y)send({type:'move',x:Math.max(-300,Math.min(300,x)),y:Math.max(-300,Math.min(300,y))});}
function moveLook(x,y){motionX+=x*prefs.sensitivity;motionY+=y*prefs.sensitivity;if(motionFrame===null)motionFrame=requestAnimationFrame(flushLook);}
let physicalMouseButton=null;
let joyPointer=null, lookPointer=null, lastX=0,lastY=0,lookTravel=0,lookStarted=0;
let composing=false,typingBusy=false,composerKind='chat',draft='',cursorMode=false,toastTimer;
let prefs={sensitivity:2,size:100,opacity:70,leftHanded:false};
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
function blocked(){return composing||typingBusy||!$('settings-layer').hidden||$('session').hidden;}
function hold(key,down,owner){
  const owners=keyOwners.get(key)||new Set();const before=owners.size;
  if(down)owners.add(owner);else owners.delete(owner);
  if(owners.size)keyOwners.set(key,owners);else keyOwners.delete(key);
  if(!before&&owners.size)send({type:'key',key,down:true});
  if(before&&!owners.size)send({type:'key',key,down:false});
}
function resetControls(){
  keyOwners.clear();activePointers.clear();actionPositions.clear();physicalMouseButton=null;if(motionFrame!==null)cancelAnimationFrame(motionFrame);motionFrame=null;motionX=0;motionY=0;joyPointer=null;lookPointer=null;
  $('stick').style.transform='translate(0px,0px)';$('joystick').classList.remove('stick-active');
  document.querySelectorAll('.held').forEach(e=>e.classList.remove('held'));
  document.querySelectorAll('[data-toggle]').forEach(e=>e.setAttribute('aria-pressed','false'));
}
function toast(text){clearTimeout(toastTimer);$('toast').textContent=text;$('toast').hidden=false;toastTimer=setTimeout(()=>{$('toast').hidden=true;},2200);}
async function tapKey(key){const gen=epoch;send({type:'key',key,down:true});await delay(45);if(gen===epoch)send({type:'key',key,down:false});}
function closeMenu(){$('settings-layer').hidden=true;}
function openMenu(){release();$('settings-layer').hidden=false;}
$('menu').onclick=openMenu;$('close-menu').onclick=closeMenu;$('settings-backdrop').onclick=closeMenu;
$('leave').onclick=()=>end();$('sound').onclick=()=>{sound();toast('Sound enabled');};
$('pause-game').onclick=()=>{closeMenu();tapKey('escape');};
function toggleMouse(){release();cursorMode=!cursorMode;for(const id of ['cursor-mode','mouse-toggle'])$(id).setAttribute('aria-pressed',String(cursorMode));$('mouse-toggle').textContent=cursorMode?'Play':'Mouse';$('session').classList.toggle('mouse-mode',cursorMode);$('remote-cursor').hidden=!cursorMode;$('mouse-actions').hidden=!cursorMode;closeMenu();toast(cursorMode?'Mouse mode · tap to click. Open Game menu to release Minecraft’s mouse.':'Play mode · swipe to look');}
$('cursor-mode').onclick=$('mouse-toggle').onclick=toggleMouse;
$('game-fullscreen').onclick=()=>{closeMenu();release();send({type:'game-fullscreen'});toast('Borderless fullscreen · select Minecraft on the PC first');};
$('exclusive-fullscreen').onclick=()=>{closeMenu();tapKey('f11');toast('Minecraft F11 toggled · use this to leave exclusive fullscreen');};
let fillScreen=true;
$('session').classList.add('fill-screen');
$('screen-fit').onclick=()=>{fillScreen=!fillScreen;$('session').classList.toggle('fill-screen',fillScreen);$('screen-fit').setAttribute('aria-pressed',String(fillScreen));$('screen-fit').textContent=fillScreen?'Fill phone screen':'Fit entire desktop';};
async function mouseClick(key){if(blocked())return;const gen=epoch;send({type:'button',key,down:true});await delay(40);if(epoch===gen)send({type:'button',key,down:false});}
$('mouse-left').onclick=()=>mouseClick('left');$('mouse-right').onclick=()=>mouseClick('right');
$('scroll-up').onclick=()=>send({type:'scroll',steps:3});$('scroll-down').onclick=()=>send({type:'scroll',steps:-3});
function pointerPosition(e){
 const box=$('look').getBoundingClientRect();let left=box.left,top=box.top,width=box.width,height=box.height;
 if(!fillScreen){const media=mode==='compatibility'?$('compat'):$('video');const w=media.videoWidth||media.width,h=media.videoHeight||media.height;if(w&&h){const scale=Math.min(width/w,height/h);left+=(width-w*scale)/2;top+=(height-h*scale)/2;width=w*scale;height=h*scale;}}
 const x=Math.max(0,Math.min(1,(e.clientX-left)/width)),y=Math.max(0,Math.min(1,(e.clientY-top)/height));
 $('remote-cursor').style.left=(left-box.left+x*width)+'px';$('remote-cursor').style.top=(top-box.top+y*height)+'px';send({type:'pointer',x,y});
} 
$('hide-controls').onclick=()=>{release();$('touch-controls').hidden=true;$('restore-controls').hidden=false;closeMenu();};
$('restore-controls').onclick=()=>{$('touch-controls').hidden=false;$('restore-controls').hidden=true;};
function applyPreferences(value){
  const number=(key,min,max,fallback)=>Number.isFinite(Number(value?.[key]))?Math.max(min,Math.min(max,Number(value[key]))):fallback;
  prefs={sensitivity:number('sensitivity',.5,4,2),size:number('size',80,120,100),opacity:number('opacity',30,100,70),leftHanded:value?.leftHanded===true};
  $('sensitivity').value=prefs.sensitivity;$('control-size').value=prefs.size;$('control-opacity').value=prefs.opacity;
  $('sensitivity-value').textContent=prefs.sensitivity.toFixed(1)+'×';$('size-value').textContent=prefs.size+'%';$('opacity-value').textContent=prefs.opacity+'%';
  $('session').style.setProperty('--control-scale',prefs.size/100);$('session').style.setProperty('--control-opacity',prefs.opacity/100);
  $('session').classList.toggle('left-handed',prefs.leftHanded);$('left-handed').setAttribute('aria-pressed',String(prefs.leftHanded));
}
function savePreferences(){applyPreferences(prefs);window.FarPlay.saveControls(JSON.stringify(prefs));}
for(const [id,key] of [['sensitivity','sensitivity'],['control-size','size'],['control-opacity','opacity']])$(id).oninput=e=>{prefs[key]=Number(e.target.value);savePreferences();};
$('left-handed').onclick=()=>{release();prefs.leftHanded=!prefs.leftHanded;savePreferences();};
$('reset-layout').onclick=()=>{prefs={sensitivity:2,size:100,opacity:70,leftHanded:false};savePreferences();toast('Controls reset');};
async function compose(kind){
  if(composing||typingBusy||$('session').hidden)return;
  closeMenu();release();composing=true;composerKind=kind;
  const gen=epoch;
  if(kind==='chat'){await tapKey('t');await delay(120);}
  if(gen!==epoch)return;
  window.FarPlay.compose(kind,kind==='chat'?draft:'');
}
$('chat').onclick=()=>compose('chat');$('keyboard').onclick=()=>compose('text');
async function finishComposer(data,cancel){
  if(!composing)return;
  const kind=composerKind;const gen=epoch;
  let text=String(data?.text||'').replace(/[\x00-\x1f\x7f]/g,' ').slice(0,200);
  if(kind==='chat')draft=cancel?text:'';
  composing=false;typingBusy=true;
  try{
    if(cancel){if(kind==='chat')await tapKey('escape');return;}
    if(!text.trim()){if(kind==='chat')await tapKey('escape');return;}
    send({type:'text',text});
    if(kind==='chat'){await delay(180);if(epoch!==gen)return;await tapKey('enter');}
    if(epoch===gen)toast(kind==='chat'?'Message sent':'Text entered');
  }finally{if(epoch===gen)typingBusy=false;}
}
for(const button of document.querySelectorAll('[data-key],[data-button]')){
  button.onpointerdown=e=>{
    e.preventDefault();if(blocked()||activePointers.has(button))return;
    activePointers.set(button,e.pointerId);actionPositions.set(button,{x:e.clientX,y:e.clientY});button.setPointerCapture(e.pointerId);button.classList.add('held');
    if(button.dataset.key)hold(button.dataset.key,true,button);
    else send({type:'button',key:button.dataset.button,down:true});
  };
  button.onpointermove=e=>{if(activePointers.get(button)!==e.pointerId||!button.dataset.button||cursorMode)return;const last=actionPositions.get(button);if(last)moveLook(e.clientX-last.x,e.clientY-last.y);actionPositions.set(button,{x:e.clientX,y:e.clientY});};
  const up=e=>{if(activePointers.get(button)!==e.pointerId)return;activePointers.delete(button);actionPositions.delete(button);flushLook();button.classList.remove('held');
    if(button.dataset.key)hold(button.dataset.key,false,button);else send({type:'button',key:button.dataset.button,down:false});};
  button.onpointerup=up;button.onpointercancel=up;button.onlostpointercapture=up;
}
for(const button of document.querySelectorAll('[data-toggle]'))button.onclick=()=>{
  if(blocked())return;const down=button.getAttribute('aria-pressed')!=='true';
  hold(button.dataset.toggle,down,button);button.setAttribute('aria-pressed',String(down));
};
for(const button of document.querySelectorAll('[data-slot]'))button.onclick=()=>{
  if(blocked())return;tapKey(button.dataset.slot);
  document.querySelectorAll('[data-slot]').forEach(b=>{b.classList.toggle('selected',b===button);b.setAttribute('aria-pressed',String(b===button));});
};
function moveStick(e){
  const box=$('joystick').getBoundingClientRect();const factor=144/box.width;
  let x=(e.clientX-box.left-box.width/2)*factor,y=(e.clientY-box.top-box.height/2)*factor;
  const distance=Math.hypot(x,y);if(distance>44){x*=44/distance;y*=44/distance;}
  $('stick').style.transform=`translate(${x}px,${y}px)`;
  const moving=distance>12;
  for(const [key,down] of [['a',x<-12],['d',x>12],['w',y<-12],['s',y>12]])hold(key,moving&&down,'joystick');
}
$('joystick').onpointerdown=e=>{e.preventDefault();if(blocked()||joyPointer!==null)return;joyPointer=e.pointerId;$('joystick').setPointerCapture(joyPointer);$('joystick').classList.add('stick-active');moveStick(e);};
$('joystick').onpointermove=e=>{if(e.pointerId===joyPointer)moveStick(e);};
const stopStick=e=>{if(e.pointerId!==joyPointer)return;joyPointer=null;for(const key of ['w','a','s','d'])hold(key,false,'joystick');$('stick').style.transform='translate(0px,0px)';$('joystick').classList.remove('stick-active');};
$('joystick').onpointerup=stopStick;$('joystick').onpointercancel=stopStick;$('joystick').onlostpointercapture=stopStick;
$('look').onpointerdown=e=>{if(blocked()||lookPointer!==null)return;if(cursorMode){pointerPosition(e);if(e.pointerType==='mouse'){physicalMouseButton=e.button===2?'right':'left';send({type:'button',key:physicalMouseButton,down:true});}}lookPointer=e.pointerId;lastX=e.clientX;lastY=e.clientY;lookTravel=0;lookStarted=performance.now();$('look').setPointerCapture(e.pointerId);};
$('look').onpointermove=e=>{if(cursorMode&&!blocked()&&e.pointerType==='mouse'){pointerPosition(e);return;}if(e.pointerId!==lookPointer)return;const x=e.clientX-lastX,y=e.clientY-lastY;lookTravel+=Math.abs(x)+Math.abs(y);if(cursorMode)pointerPosition(e);else moveLook(x,y);lastX=e.clientX;lastY=e.clientY;};
$('look').onpointerup=async e=>{if(e.pointerId!==lookPointer)return;flushLook();lookPointer=null;if(physicalMouseButton){send({type:'button',key:physicalMouseButton,down:false});physicalMouseButton=null;return;}if(cursorMode&&lookTravel<8&&performance.now()-lookStarted<300){const gen=epoch;send({type:'button',key:'left',down:true});await delay(40);if(epoch===gen)send({type:'button',key:'left',down:false});}};
$('look').onpointercancel=$('look').onlostpointercapture=()=>{lookPointer=null;if(physicalMouseButton){send({type:'button',key:physicalMouseButton,down:false});physicalMouseButton=null;}};
window.addEventListener('blur',release);
window.addEventListener('resize',release);
document.addEventListener('visibilitychange',()=>{if(document.hidden)end('Paused. Tap Connect to resume.');});
window.addEventListener('pagehide',()=>end());
window.addEventListener('contextmenu',e=>{if(!$('session').hidden)e.preventDefault();});
$('look').onwheel=e=>{if(cursorMode&&!blocked()){e.preventDefault();send({type:'scroll',steps:e.deltaY>0?-1:1});}};
const keyMap={KeyW:'w',KeyA:'a',KeyS:'s',KeyD:'d',Space:'space',ShiftLeft:'shift',ControlLeft:'ctrl',KeyE:'e',KeyT:'t',Escape:'escape',Enter:'enter',Backspace:'backspace'};
for(let i=1;i<=9;i++)keyMap['Digit'+i]=String(i);
for(const type of ['keydown','keyup'])window.addEventListener(type,e=>{
  if(blocked()||!keyMap[e.code]||e.repeat||['INPUT','TEXTAREA','SELECT'].includes(e.target.tagName))return;
  e.preventDefault();hold(keyMap[e.code],type==='keydown','physical-'+e.code);
});

function renderStats(){if(!$('session').hidden)$('stats').textContent=`${mode==='compatibility'?'Compatibility':'Direct'} · ${networkMs} ms${streamInfo?' · '+streamInfo:''}`;}
async function updateStats(){
 const connection=pc,gen=epoch;
 if(mode==='compatibility'){
  const now=performance.now();streamInfo=Math.round((renderedFrames-lastFrameCount)*1000/(now-statTime))+' FPS';lastFrameCount=renderedFrames;statTime=now;renderStats();return;
 }
 if(!connection)return;
 try{
  const report=await connection.getStats();if(gen!==epoch||connection!==pc)return;
  for(const item of report.values())if(item.type==='inbound-rtp'&&(item.kind==='video'||item.mediaType==='video')){
   if(!lastStats||item.framesDecoded>lastStats.framesDecoded)lastVideoProgress=performance.now();
   if(lastStats&&item.timestamp>lastStats.timestamp){
    const count=item.framesDecoded-lastStats.framesDecoded;const fps=Math.round(count*1000/(item.timestamp-lastStats.timestamp));
    const emitted=item.jitterBufferEmittedCount-lastStats.jitterBufferEmittedCount;
    const bufferMs=emitted>0?Math.round((item.jitterBufferDelay-lastStats.jitterBufferDelay)*1000/emitted):0;
    streamInfo=(Number.isFinite(fps)?fps+' FPS':'')+(Number.isFinite(bufferMs)?' · buffer '+bufferMs+' ms':'');
   }
   lastStats=item;
  }
  renderStats();
  if(mode==='rtc'&&performance.now()-lastVideoProgress>6000){toast('Video stalled · recovering stream');compatibility();}
 }catch{} // Older WebViews may omit individual statistics.
}
