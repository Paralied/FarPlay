// Run with node tests/mobile-controls.cjs. Native transport/DOM are simulated.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync('android/app/src/main/assets/index.html','utf8');
const elements=[...html.matchAll(/<(button|div|section|input|video|canvas|main|output|span|p)[^>]*>/g)].map(([tag])=>{
 const attrs=Object.fromEntries([...tag.matchAll(/([\w-]+)="([^"]*)"/g)].map(m=>[m[1],m[2]]));const classes=new Set((attrs.class||'').split(' '));
 return {id:attrs.id,dataset:Object.fromEntries(Object.entries(attrs).filter(([k])=>k.startsWith('data-')).map(([k,v])=>[k.slice(5),v])),hidden:tag.includes(' hidden'),style:{setProperty(){}},classList:{add:v=>classes.add(v),remove:v=>classes.delete(v),toggle:(v,b)=>b?classes.add(v):classes.delete(v),contains:v=>classes.has(v)},setAttribute:(k,v)=>attrs[k]=v,getAttribute:k=>attrs[k],setPointerCapture(){},getBoundingClientRect:()=>({left:0,top:0,width:144,height:144}),play:async()=>{}};
});
const get=id=>{const e=elements.find(e=>e.id===id);assert(e,'Missing element '+id);return e;};
const query=s=>elements.filter(e=>s.split(',').some(s=>s==='.held'?e.classList.contains('held'):e.dataset[s.match(/data-([^\]]+)/)?.[1]]!==undefined));
const sent=[],composers=[];
const context=vm.createContext({document:{getElementById:get,querySelectorAll:query,addEventListener(){}},window:{FarPlay:{signal:s=>sent.push(JSON.parse(s).payload),compose:(...args)=>composers.push(args),setPlaying(){},disconnectPC(){},saveControls(){}},addEventListener(){}},setTimeout,clearTimeout,setInterval,clearInterval,performance,console});
vm.runInContext(fs.readFileSync('android/app/src/main/assets/client.js','utf8'),context);
const run=s=>vm.runInContext(s,context);
const event=(id,x,y)=>({pointerId:id,clientX:x,clientY:y,preventDefault(){}});
(async()=>{
 run("mode='compatibility';showSession()");
 get('joystick').onpointerdown(event(1,110,30));assert(sent.some(x=>x.key==='d'&&x.down));assert(sent.some(x=>x.key==='w'&&x.down));
 get('joystick').onpointercancel(event(1));assert(sent.some(x=>x.key==='w'&&!x.down));assert.equal(run('keyOwners.size'),0);
 const attack=query('[data-button]').find(e=>e.dataset.button==='left');attack.onpointerdown(event(2));get('menu').onclick();assert.equal(sent.at(-1).type,'release');assert.equal(run('activePointers.size'),0);get('close-menu').onclick();
 sent.length=0;await get('chat').onclick();assert.equal(composers.at(-1)[0],'chat');await context.window.onNative('composer-send',{text:'hello'});assert.deepEqual(sent.filter(x=>x.type==='key').map(x=>[x.key,x.down]),[['t',true],['t',false],['enter',true],['enter',false]]);assert(sent.some(x=>x.type==='text'&&x.text==='hello'));
 await get('chat').onclick();await context.window.onNative('composer-cancel',{text:'draft'});await get('chat').onclick();assert.equal(composers.at(-1)[1],'draft');await context.window.onNative('composer-cancel',{text:'draft'});
 run('applyPreferences({size:900,opacity:1,sensitivity:99,leftHanded:true})');assert.equal(run('prefs.size'),120);assert.equal(run('prefs.opacity'),30);
 sent.length=0;const pending=get('chat').onclick();run('end()');await pending;assert(!sent.some(x=>x.key==='enter'));assert(get('session').hidden);
 assert(!fs.readFileSync('android/app/src/main/java/com/paralied/farplay/MainActivity.java','utf8').includes('FLAG_SECURE'));
 console.log('Mobile control checks passed: movement, cancellation, menu release, chat send/draft, settings bounds, disconnect, screenshots.');
})().catch(e=>{console.error(e);process.exitCode=1;});
