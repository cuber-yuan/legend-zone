/* Shared panel and six real game templates; API and Socket.IO are fixtures. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {spawnSync} = require('node:child_process');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '..');
const cache = process.env.PREVIEW_DIR;
const rendered = spawnSync(process.env.PYTHON_PATH || 'python', ['-c', `
import json
from types import SimpleNamespace
from jinja2 import Environment,FileSystemLoader
env=Environment(loader=FileSystemLoader('app/templates'),autoescape=True)
def url_for(endpoint,**kw):
 if endpoint=='static': return '/static/'+kw['filename']
 if endpoint=='main.match_debug': return '/api/matches/'+kw['match_id']+'/debug'
 return '/'+endpoint.replace('.','/')
env.globals['url_for']=url_for
pages={}
for slug,title in [('gomoku','Gomoku'),('tictactoe','Tic Tac Toe'),('connect4','Connect Four'),('snake','Snake'),('msnake','Mini Snake'),('tank','Tank Battle')]:
 match={'game':title,'status':'playing','winner':-1,'move_history':[],'displays':[], 'players':{'player_1':{'name':'Alpha <Bot>','version':1},'player_2':{'name':'Beta '+('VeryLongName'*6),'version':1}}}
 pages[slug]=env.get_template(('snake' if slug=='msnake' else slug)+'.html').render(request=SimpleNamespace(path='/'+slug,endpoint='main.'+slug),current_user=SimpleNamespace(is_authenticated=False),bots=[],match=match,match_id='fixture')
print(json.dumps(pages))
`], {cwd:root,encoding:'utf8',env:{...process.env,PYTHONIOENCODING:'utf-8'}});
assert.equal(rendered.status,0,rendered.stderr);
const pages = JSON.parse(rendered.stdout);
const baseManifest = {available:true,status:'complete',frame_count:2,last_turn:3,failure_turn:3,truncated:false,incomplete:false,error:'Player failed to return a valid action.'};
const makeEvent = (actor, turn) => ({actor,turn,kind:actor==='judge'?'python_judge':'bot',status:turn===3&&actor==='player_2'?'timeout':'success',input:actor==='judge'?'{}':`EXACT input ${turn}\n<raw>`,stdout:actor==='judge'?JSON.stringify({accepted:true}):`  {"x": ${turn}}\n<script>window.injected=true</script>`,stderr:actor==='player_1'?'real stderr\n':'',diagnostic:turn===3&&actor==='player_2'?'Execution exceeded its time limit.':'',duration_ms:12.5,exit_code:turn===3?null:0,truncated_fields:[]});

(async () => {
 const browser = await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
 try {
  for (const [slug,html] of Object.entries(pages)) {
   const page = await browser.newPage({viewport:{width:1280,height:1100}});
   const errors=[], calls=[];
   let mode='normal';
   page.on('pageerror',e=>errors.push(e.message));
   await page.route('**/socket.io.min.js',r=>r.fulfill({contentType:'application/javascript',body:`window.io=()=>{const s={connected:true,handlers:{},sent:[],on(e,f){this.handlers[e]=f;if(e==='init')setTimeout(()=>f({user_id:'fixture'}),0);},emit(e,d){this.sent.push({e,d});}};window.testSocket=s;return s;};`}));
   await page.route('**/phaser.js',r=>r.fulfill({contentType:'application/javascript',body:fs.readFileSync(path.join(cache,'phaser-3.55.2.js'))}));
   await page.route('https://cdn.tailwindcss.com/',r=>r.fulfill({contentType:'application/javascript',body:fs.readFileSync(path.join(cache,'tailwind.js'))}));
   await page.route('**/prism*',r=>r.fulfill({contentType:r.request().url().endsWith('.css')?'text/css':'application/javascript',body:''}));
   await page.route('http://debug.test/**', async r => {
    const u=new URL(r.request().url());
    if(u.pathname==='/page')return r.fulfill({contentType:'text/html',body:html});
    if(u.pathname.startsWith('/static/')) {
     const file=path.join(root,'app',u.pathname);
     if(fs.existsSync(file))return r.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.css')?'text/css':file.endsWith('.js')?'application/javascript':file.endsWith('.m4a')?'audio/mp4':file.endsWith('.mp3')?'audio/mpeg':'image/svg+xml'});
    }
    if(u.pathname==='/api/matches/fixture/debug') {
     calls.push(u.search);
     if(mode==='network')return r.fulfill({status:503,body:''});
     if(mode==='legacy')return r.fulfill({json:{available:false,events:[],turns:[]}});
     assert.equal(u.search,'?all=1','Frontend must request the whole trace once');
     const events=[makeEvent('judge',0), ...[1,2].flatMap(turn=>['judge','player_1'].map(a=>makeEvent(a,turn))),makeEvent(mode==='judge-failure'?'judge':'player_2',3)];
     if(mode==='long')events.forEach(e=>{e.input='Long input line\n'.repeat(200);e.stdout='Long output line\n'.repeat(200);e.stderr='Long stderr line\n'.repeat(200);});
     if(mode==='truncated')events.forEach(e=>{e.truncated_fields=['input'];e.limit_reached=true;});
     if(mode==='slow-bulk')await new Promise(resolve=>setTimeout(resolve,650));
     return r.fulfill({json:{...baseManifest,...(mode==='truncated'?{truncated:true,incomplete:true}:{}),events}});
    }
    return r.fulfill({status:404,body:''});
   });
   const load=async()=>{
    await page.goto('http://debug.test/page',{waitUntil:'domcontentloaded'});
    await page.waitForFunction(()=>!!document.querySelector('#phaser-container canvas'));
    await page.evaluate(slug=>{
     if(slug==='snake'||slug==='msnake')startReplay([{height:10,width:11,obstacle:[],'0':{x:1,y:1},'1':{x:10,y:11}},{'0':1,'1':3,grow:'true'},{'0':2,'1':0,grow:'true'}],-1);
     else if(slug==='tank')startReplay([{brick:[0,0,0],water:[0,0,0],steel:[0,0,0]},{actions:[-1,-1,-1,-1]},{actions:[-1,-1,-1,-1]}],-1);
     else startReplay([{x:0,y:slug==='connect4'?5:0,player:1},{x:1,y:slug==='connect4'?5:0,player:2}],-1);
     replayController.pause();
    },slug);
   };
   await load();
   assert.equal(calls.length,0,'No debug requests before opt-in');
   assert.ok(await page.locator('[data-debug-panel]').isHidden());
   assert.equal(await page.locator('[data-replay-debug]').count(),1);
   assert.equal(await page.locator('[data-debug-toggle]').getAttribute('aria-expanded'),'false');
   assert.equal(await page.locator('[data-replay-debug] input[type="checkbox"]').count(),0);
   await page.locator('[data-debug-toggle]').focus();
   await page.keyboard.press('Enter');
   assert.equal(await page.locator('[data-debug-toggle]').getAttribute('aria-expanded'),'true');
   await page.waitForFunction(()=>document.querySelector('[data-debug-title]').textContent==='Initial state');
   assert.equal(await page.locator('[data-debug-status]').textContent(),'Not active');
   assert.equal(await page.locator('[data-debug-actor]').count(),2);
   assert.equal(await page.locator('[data-debug-actor="judge"],#rdJudgeTab').count(),0);
   assert.equal(await page.locator('[data-debug-actor="player_1"]').getAttribute('aria-selected'),'true');
   assert.equal(await page.locator('[data-debug-actor="player_1"]').innerText(),'Alpha <Bot>');
   await page.locator('[data-debug-actor="player_1"]').click();
   assert.equal(await page.locator('[data-debug-status]').textContent(),'Not active');
   const watchFlicker=()=>page.evaluate(()=>{
    window.debugFlashes=[];
    window.debugObserver?.disconnect();
    window.debugObserver=new MutationObserver(records=>{
     for(const record of records) {
      if(record.type==='attributes'&&record.target.matches('[data-debug-content]')&&record.oldValue===null)window.debugFlashes.push('content hidden');
      if(document.querySelector('[data-debug-notice]').textContent.includes('Loading debug records'))window.debugFlashes.push('loading message');
     }
    });
    window.debugObserver.observe(document.querySelector('[data-debug-panel]'),{subtree:true,childList:true,characterData:true,attributes:true,attributeOldValue:true,attributeFilter:['hidden']});
   });
   await watchFlicker();
   await page.locator('#btnNext').click();
   await page.waitForFunction(()=>document.querySelector('[data-debug-title]').textContent==='Round 1');
   assert.deepEqual(await page.evaluate(()=>window.debugFlashes),[],`${slug}: no intermediate loading/collapse`);
   assert.equal(await page.locator('[data-debug-input]').textContent(),'EXACT input 1\n<raw>');
   assert.equal(await page.locator('[data-debug-output]').textContent(),'  {"x": 1}\n<script>window.injected=true</script>');
   assert.equal(await page.evaluate(()=>window.injected),undefined);
   assert.ok(await page.locator('[data-debug-stderr-section]').evaluate(el=>el.open));
   assert.ok(await page.locator('[data-debug-stderr]').isVisible());
   assert.ok(await page.locator('[data-debug-stderr]').evaluate(el=>el.getBoundingClientRect().height<=48));
   assert.equal(await page.locator('[data-debug-stderr]').textContent(),'real stderr\n');
   const before=await page.locator('#replayCounter').textContent();
   await page.locator('[data-debug-actor="player_1"]').focus();
   await page.keyboard.press('ArrowRight');
   assert.equal(await page.locator('#replayCounter').textContent(),before);
   assert.equal(await page.locator('[data-debug-status]').textContent(),'Not active');
   assert.equal(await page.locator('[data-debug-duration]').textContent(),'— ms');
   assert.equal(await page.locator('[data-debug-exit]').textContent(),'Exit code —');
   assert.ok(await page.locator('[data-debug-fields]').isVisible());
   assert.equal(await page.locator('[data-debug-input]').textContent(),'');
   assert.equal(await page.locator('[data-debug-output]').textContent(),'');
   assert.equal(await page.locator('[data-debug-stderr]').textContent(),'');
   assert.ok(await page.locator('[data-debug-empty]').isHidden());
   for(const width of [1280,390,320]) {
    await page.setViewportSize({width,height:1100});
    const measure=()=>page.locator('.rd-record').evaluate(el=>({
     offset:el.querySelector('[data-debug-fields]').getBoundingClientRect().top-el.getBoundingClientRect().top,
     metaHeight:el.querySelector('.rd-meta').getBoundingClientRect().height
    }));
    const inactive=await measure();
    await page.locator('[data-debug-actor="player_1"]').click();
    assert.equal(await page.locator('[data-debug-status]').textContent(),'Success');
    assert.deepEqual(await measure(),inactive,`${slug}/${width}: I/O stays in place across active and inactive seats`);
    await page.locator('[data-debug-actor="player_2"]').click();
    assert.deepEqual(await measure(),inactive);
   }
   await page.locator('[data-debug-failure]').click();
   await page.waitForFunction(()=>document.querySelector('[data-debug-status]').textContent==='Timed out');
   assert.equal(await page.locator('#replayCounter').innerText(),'2 / 2');
   assert.equal(await page.locator('[data-debug-title]').innerText(),'Round 3 · failed');
   assert.equal(await page.locator('[data-debug-frame]').innerText(),'Board remains at frame 2');
   assert.equal(await page.locator('[data-debug-diagnostic]').innerText(),'Execution exceeded its time limit.');
   assert.equal(await page.locator('[data-debug-stderr]').textContent(),'(empty)');
   for(const width of [1280,390,320]) {
    await page.setViewportSize({width,height:1100});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`${slug}/${width} overflow`);
    assert.ok(await page.locator('[data-debug-panel]').evaluate(el=>{
     const outer=el.getBoundingClientRect(),inner=el.querySelector('[data-debug-content]').getBoundingClientRect();
     return Math.abs((inner.left-outer.left)-(outer.right-inner.right))<1;
    }),`${slug}/${width}: symmetric debug panel gutters`);
    const count=await page.locator('[data-debug-fields]').evaluate(el=>getComputedStyle(el).gridTemplateColumns.split(' ').length);
    assert.equal(count,width<=600?1:2,JSON.stringify({slug,width,details:await page.locator('[data-debug-fields]').evaluate(el=>({columns:getComputedStyle(el).gridTemplateColumns,innerWidth,media:matchMedia('(max-width:600px)').matches}))}));
    if(slug==='connect4'&&width!==320)await page.locator('#replayControls').screenshot({path:path.join(cache,`replay-debug-implemented-${width}.png`)});
   }
   await page.locator('#btnFirst').click();
   await page.waitForFunction(()=>document.querySelector('[data-debug-title]').textContent==='Initial state');
   assert.equal(await page.locator('[data-debug-failure]').getAttribute('aria-pressed'),'false');
   await page.locator('#btnNext').click();
   await page.locator('#btnNext').click();
   await page.waitForFunction(()=>document.querySelector('[data-debug-title]').textContent==='Round 2');
   await page.locator('[data-debug-toggle]').focus();
   await page.keyboard.press('Space');
   assert.equal(await page.locator('[data-debug-toggle]').getAttribute('aria-expanded'),'false');
   assert.ok(await page.locator('[data-debug-panel]').isHidden());
   assert.ok(await page.locator('[data-debug-failure]').isHidden());
   await page.locator('[data-debug-toggle]').click();
   await page.waitForFunction(()=>document.querySelector('[data-debug-title]').textContent==='Round 2');
   assert.deepEqual(calls,['?all=1'],`${slug}: playback, seeking, actor changes and reopening reuse one request`);
   await page.locator('[data-debug-toggle]').click();
   if(slug==='connect4') {
    for(const value of ['legacy','network','truncated','judge-failure','long','playback','slow-bulk']) {
     mode=value;
     await load();
     const callsBefore=calls.length;
     await page.locator('[data-debug-toggle]').click();
     if(value==='legacy')await page.waitForFunction(()=>document.querySelector('[data-debug-notice]').textContent.includes('No debug records'));
     if(value==='network') {
      await page.waitForFunction(()=>document.querySelector('[data-debug-notice]').textContent.includes('Could not load'));
      mode='normal';
      await page.locator('[data-debug-toggle]').click();await page.locator('[data-debug-toggle]').click();
      await page.waitForFunction(()=>document.querySelector('[data-debug-title]').textContent==='Initial state');
     }
     if(value==='truncated') {
      await page.waitForFunction(()=>document.querySelector('[data-debug-notice]').textContent.includes('truncated'));
      await page.locator('#btnNext').click();
      await page.waitForFunction(()=>document.querySelector('[data-debug-title]').textContent==='Round 1');
      assert.ok(await page.locator('[data-debug-cut="input"]').isVisible());
      assert.ok((await page.locator('[data-debug-input]').innerText()).includes('Not stored'));
     }
     if(value==='judge-failure') {
      await page.locator('[data-debug-failure]').click();
      await page.waitForFunction(()=>document.querySelector('[data-debug-title]').textContent==='Round 3 · failed');
      assert.equal(await page.locator('[data-debug-actor="player_1"]').getAttribute('aria-selected'),'true');
      assert.equal(await page.locator('[data-debug-status]').textContent(),'Not active');
      assert.ok(await page.locator('[data-debug-fields]').isVisible());
      assert.equal(await page.locator('[data-debug-input]').textContent(),'');
      assert.equal(await page.locator('[data-debug-output]').textContent(),'');
     }
     if(value==='long') {
      await page.waitForFunction(()=>document.querySelector('[data-debug-title]').textContent==='Initial state');
      const panelHeight=await page.locator('[data-debug-panel]').evaluate(el=>el.getBoundingClientRect().height);
      await page.locator('#btnNext').click();
      await page.waitForFunction(()=>document.querySelector('[data-debug-title]').textContent==='Round 1');
      for(const width of [1280,390,320]) {
       await page.setViewportSize({width,height:1100});
       assert.equal(await page.locator('[data-debug-panel]').evaluate(el=>el.getBoundingClientRect().height),panelHeight);
       assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
       for(const field of ['input','output']) {
        const pre=page.locator(`[data-debug-${field}]`);
        assert.ok(await pre.evaluate(el=>el.scrollHeight>el.clientHeight));
        await pre.hover();
        await page.mouse.wheel(0,180);
        await page.waitForFunction(field=>document.querySelector(`[data-debug-${field}]`).scrollTop>0,field);
        await pre.focus();
        await page.keyboard.press('End');
        assert.equal(await page.locator('#replayCounter').innerText(),'1 / 2');
       }
      }
      assert.ok(await page.locator('[data-debug-stderr-section]').evaluate(el=>el.open));
      assert.ok(await page.locator('[data-debug-stderr]').evaluate(el=>el.scrollHeight>el.clientHeight));
      await page.locator('[data-debug-stderr]').hover();
      await page.mouse.wheel(0,180);
      await page.waitForFunction(()=>document.querySelector('[data-debug-stderr]').scrollTop>0);
      assert.equal(await page.locator('[data-debug-panel]').evaluate(el=>el.getBoundingClientRect().height),panelHeight);
     }
     if(value==='playback') {
      await page.waitForFunction(()=>document.querySelector('[data-debug-title]').textContent==='Initial state');
      await watchFlicker();
      await page.evaluate(()=>{replayController.setSpeed(4);replayController.play();});
      await page.waitForFunction(()=>document.querySelector('[data-debug-title]').textContent==='Round 2');
      assert.equal(await page.locator('[data-debug-title]').innerText(),'Round 2');
      assert.ok((await page.locator('[data-debug-input]').textContent()).includes('EXACT input 2'));
      assert.deepEqual(await page.evaluate(()=>window.debugFlashes),[],'playback must not flash loading or collapse content');
      assert.equal(await page.locator('[data-debug-panel]').getAttribute('aria-busy'),null);
      // Cached rounds also replace the previous snapshot without intermediate UI.
      await page.locator('#btnFirst').click();
      await page.waitForFunction(()=>document.querySelector('[data-debug-title]').textContent==='Initial state');
      await page.locator('#btnLast').click();
      await page.waitForFunction(()=>document.querySelector('[data-debug-title]').textContent==='Round 2');
      assert.deepEqual(await page.evaluate(()=>window.debugFlashes),[]);
      assert.equal(calls.length,callsBefore+1,'Playback and cached seeking must not send requests');
     }
     if(value==='slow-bulk') {
      // Continue changing frames/actors while the sole bulk request is pending.
      await page.evaluate(()=>{replayController.setSpeed(4);replayController.play();});
      await page.locator('[data-debug-actor="player_2"]').evaluate(el=>el.click());
      await page.locator('[data-debug-actor="player_1"]').evaluate(el=>el.click());
      await page.waitForFunction(()=>document.querySelector('[data-debug-title]').textContent==='Round 2');
      assert.ok((await page.locator('[data-debug-input]').textContent()).includes('EXACT input 2'));
      assert.equal(calls.length,callsBefore+1,'Frame changes must share the pending snapshot request');
     }
    }
   }
   assert.deepEqual(errors,[],slug);
   await page.close();
  }
  console.log('PASS: six game templates, opt-in loading, raw escaping, stderr, actors, failed-round mapping, keyboard, stale requests, old records, retry and 1280/390/320px layouts.');
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
