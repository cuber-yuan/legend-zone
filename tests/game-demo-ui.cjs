/* Real introduction templates with synthetic replays; never starts the app. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {spawnSync}=require('node:child_process');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(__dirname,'..'),cache=process.env.PREVIEW_DIR;
const rendered=spawnSync(process.env.PYTHON_PATH||'python',['-c',`
import json
from types import SimpleNamespace
from jinja2 import Environment,FileSystemLoader
env=Environment(loader=FileSystemLoader('app/templates'),autoescape=True)
env.globals['url_for']=lambda e,**kw:'/static/'+kw['filename'] if e=='static' else '/'+e
pages={}
for slug,title in [('gomoku','Gomoku'),('tictactoe','Tic Tac Toe'),('connect4','Connect Four'),('snake','Snake'),('msnake','Mini Snake'),('tank','Tank Battle')]:
 frames=[{'x':0,'y':5 if slug=='connect4' else 0,'player':1},{'x':1,'y':5 if slug=='connect4' else 0,'player':2}]
 if slug in ('snake','msnake'):frames=[{'width':11,'height':10,'obstacle':[],'0':{'x':1,'y':1},'1':{'x':10,'y':11}},{'0':1,'1':3,'grow':'true'},{'0':2,'1':0,'grow':'true'}]
 if slug=='tank':frames=[{'brick':[0,0,0],'water':[0,0,0],'steel':[0,0,0]},{'0':[-1,-1],'1':[-1,-1]},{'0':[1,-1],'1':[-1,-1]}]
 demo={'game':title,'frames':frames,'winner':0,'players':{'player_1':{'name':'Alpha <Bot>'},'player_2':{'name':'Beta '+('LongName'*8)}}}
 template=env.get_template(('snake' if slug=='msnake' else slug)+'.html')
 context={'request':SimpleNamespace(path='/'+slug,endpoint='main.'+slug),'current_user':SimpleNamespace(is_authenticated=False),'bots':[]}
 for populated in (True,False):pages[slug+('/demo' if populated else '/empty')]=template.render(**context,demo=demo if populated else None,match=demo if populated else None)
print(json.dumps(pages))
`],{cwd:root,encoding:'utf8',env:{...process.env,PYTHONIOENCODING:'utf-8'}});
assert.equal(rendered.status,0,rendered.stderr);
const pages=JSON.parse(rendered.stdout);
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
 try{
  for(const [key,html] of Object.entries(pages)){
   const page=await browser.newPage({viewport:{width:1280,height:1000}}),errors=[],api=[];
   await page.emulateMedia({reducedMotion:'reduce'});
   page.on('pageerror',e=>errors.push(e.message));
   await page.addInitScript(()=>{window.audioPlays=0;HTMLMediaElement.prototype.play=function(){window.audioPlays++;return Promise.resolve();};});
   await page.route('**/socket.io.min.js',r=>r.fulfill({contentType:'application/javascript',body:`window.io=()=>{const s={connected:true,sent:[],on(e,f){if(e==='init')setTimeout(()=>f({user_id:'fixture'}),0);},emit(e,d){this.sent.push({e,d});}};window.testSocket=s;return s;};`}));
   await page.route('**/phaser.js',r=>r.fulfill({contentType:'application/javascript',body:fs.readFileSync(path.join(cache,'phaser-3.55.2.js'))}));
   await page.route('https://cdn.tailwindcss.com/',r=>r.fulfill({contentType:'application/javascript',body:fs.readFileSync(path.join(cache,'tailwind.js'))}));
   await page.route('**/prism*',r=>r.fulfill({body:'',contentType:r.request().url().endsWith('.css')?'text/css':'application/javascript'}));
   await page.route('http://demo.test/**',r=>{
    const u=new URL(r.request().url());
    if(u.pathname==='/page')return r.fulfill({contentType:'text/html',body:html});
    if(u.pathname.startsWith('/api/'))api.push(u.pathname);
    const file=path.join(root,'app',u.pathname);
    if(u.pathname.startsWith('/static/')&&fs.existsSync(file))return r.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'application/octet-stream'});
    return r.fulfill({status:404,body:''});
   });
   await page.goto('http://demo.test/page',{waitUntil:'domcontentloaded'});
   await page.waitForFunction(()=>!!document.querySelector('#phaser-container canvas'));
   assert.equal(await page.locator('#replayControls,[data-replay-debug]').count(),0,key);
   if(key.endsWith('/demo')){
    await page.waitForFunction(()=>replayController.demo&&replayController.playing,null,{timeout:5000}).catch(async error=>{
     throw new Error(key+': '+JSON.stringify({errors,state:await page.evaluate(()=>({data:!!document.getElementById('gameDemoData'),demo:replayController.demo,playing:replayController.playing,scenes:phaserGame?.scene.scenes.map(s=>({active:s.sys.isActive(),status:s.sys.settings.status}))}))}));
    });
    assert.equal(await page.locator('.match-players').count(),0,key);
    await page.evaluate(()=>{replayController.pause();replayController.baseIntervalMs=150;replayController.goto(0);replayController.play();});
    await page.waitForFunction(()=>!replayController.playing&&replayController.index===replayController.maxIndex);
    const finished=Date.now();
    await page.waitForFunction(()=>replayController.playing&&replayController.index<replayController.maxIndex,{},{timeout:5000});
    assert.ok(Date.now()-finished>=1750,`${key}: final frame holds about two seconds`);
    await page.evaluate(()=>{
     Object.defineProperty(document,'hidden',{configurable:true,value:true});
     document.dispatchEvent(new Event('visibilitychange'));
    });
    assert.equal(await page.evaluate(()=>replayController.playing),false);
    await page.evaluate(()=>{
     Object.defineProperty(document,'hidden',{configurable:true,value:false});
     document.dispatchEvent(new Event('visibilitychange'));
    });
    assert.equal(await page.evaluate(()=>replayController.playing),true);
    await page.evaluate(()=>window.dispatchEvent(new Event('pagehide')));
    assert.equal(await page.evaluate(()=>replayController.playing),false);
    await page.evaluate(()=>{window.dispatchEvent(new Event('pageshow'));delete document.hidden;});
    assert.equal(await page.evaluate(()=>replayController.playing),true);
    await page.evaluate(()=>{replayController.pause();replayController.goto(1);});
    if(key.startsWith('snake')||key.startsWith('msnake'))assert.ok(await page.evaluate(()=>phaserGame.scene.getScene('SnakeScene').fieldWidth===11));
   }else{
    assert.equal(await page.locator('#gameDemoData').count(),0,key);
    assert.equal(await page.evaluate(()=>replayController.playing),false,key);
   }
   for(const width of [1280,390,320]){
    await page.setViewportSize({width,height:1000});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`${key}/${width}: overflow`);
    if(key.endsWith('/demo'))assert.equal(await page.evaluate(()=>replayController.index),1,`${key}: resize preserves frame`);
    if(width===390&&key.endsWith('/demo')&&cache)await page.locator('#phaser-container').screenshot({path:path.join(cache,`intro-demo-${key.split('/')[0]}-390.png`)});
   }
   await page.locator('#phaser-container canvas').click({position:{x:20,y:20}});
   await page.keyboard.press('ArrowRight');
   assert.deepEqual(await page.evaluate(()=>testSocket.sent),[],`${key}: no match actions or room joins`);
   assert.deepEqual(api,[],`${key}: no debug/replay API polling`);
   assert.equal(await page.evaluate(()=>audioPlays),0,`${key}: silent demo`);
   assert.deepEqual(errors,[],key);
   await page.close();
  }
  console.log('PASS: all six introductions, empty fallback, automatic frames and loop delay, no player identity, silent playback, no controls/actions/polling, 1280/390/320px layouts.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
