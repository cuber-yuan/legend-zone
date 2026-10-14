/* Real homepage template with fixture APIs; no app factory or database. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {spawnSync} = require('node:child_process');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '..');
const rendered = spawnSync(process.env.PYTHON_PATH || 'python', ['-c', `
from types import SimpleNamespace
from jinja2 import Environment,FileSystemLoader
e=Environment(loader=FileSystemLoader('app/templates'),autoescape=True)
e.globals['url_for']=lambda endpoint,**kw: '/static/'+kw['filename'] if endpoint=='static' else '/'+endpoint
print(e.get_template('index.html').render(current_user=SimpleNamespace(is_authenticated=True,username='Fixture'),request=SimpleNamespace(endpoint='main.home')))
`], {cwd:root,encoding:'utf8',env:{...process.env,PYTHONIOENCODING:'utf-8'}});
assert.equal(rendered.status,0,rendered.stderr);
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
 try {
  for(const width of [1280,390,320]) {
   const page=await browser.newPage({viewport:{width,height:1000}});
   await page.emulateMedia({reducedMotion:'reduce'});
   const errors=[];
   let posted;
   page.on('pageerror',e=>errors.push(e.message));
   await page.route('https://cdn.tailwindcss.com/',r=>r.fulfill({contentType:'application/javascript',body:fs.readFileSync(path.join(process.env.PREVIEW_DIR,'tailwind.js'))}));
   await page.route('**/socket.io.min.js',r=>r.fulfill({contentType:'application/javascript',body:'window.io=()=>({on(){},emit(){},disconnect(){}});'}));
   await page.route('http://versions.test/**',r=>{
    const url=new URL(r.request().url());
    if(url.pathname==='/')return r.fulfill({contentType:'text/html',body:rendered.stdout});
    if(url.pathname==='/api/games')return r.fulfill({json:[{id:1,name:'Connect Four'}]});
    if(url.pathname==='/api/bots')return r.fulfill({json:[{id:'a',name:'Alpha <Bot>',versions:[3,2,1]},{id:'b',name:'Beta',versions:[1]}]});
    if(url.pathname==='/api/matches') {
     posted=r.request().postDataJSON();
     return r.fulfill({json:{match_id:'fixture'}});
    }
    if(url.pathname==='/match/fixture')return r.fulfill({contentType:'text/html',body:'Fixture match'});
    return r.fulfill({status:404,body:''});
   });
   await page.goto('http://versions.test/');
   await page.locator('#btn-create-table').click();
   await page.locator('.game-card').click();
   await page.locator('#btn-modal-create').click();
   const first=page.locator('.seat-card').nth(0), second=page.locator('.seat-card').nth(1);
   await first.locator('.version-option').last().waitFor({state:'attached'});
   assert.equal(await first.locator('.player-version').inputValue(),'3');
   assert.equal(await first.locator('.version-option').first().textContent(),'v3 (latest)');
   assert.equal(await first.locator('.seat-version select').count(),0);
   assert.ok(await first.locator('.version-options').isHidden());
   const botBounds = await first.locator('.player-bot').boundingBox();
   await first.locator('.seat-version summary').click();
   assert.ok(await first.locator('.version-option[data-version="1"]').isVisible());
   if(process.env.PREVIEW_DIR)await page.locator('#modal-player-setup .dialog-card').screenshot({path:path.join(process.env.PREVIEW_DIR,`bot-versions-menu-${width}.png`)});
   await first.locator('.version-option[data-version="1"]').click();
   assert.equal(await first.locator('[data-version-label]').textContent(),'v1');
   const selectedBounds = await first.locator('.player-bot').boundingBox();
   assert.equal(selectedBounds.width,botBounds.width,'Changing version must not resize the bot selector');
   assert.equal(selectedBounds.x,botBounds.x,'Changing version must not shift the bot selector horizontally');
   assert.ok(await first.locator('.version-options').isHidden());
   assert.match(await page.locator('#lineup-note').textContent(),/either player/);
   await second.locator('.player-bot').selectOption('b');
   assert.equal(await second.locator('.player-version').inputValue(),'1');
   assert.equal(await second.locator('.version-option').count(),1);
   await first.locator('.seg-human').click();
   assert.ok(await first.locator('.version-options').isHidden());
   assert.equal(await page.locator('#lineup-note').textContent(),'');
   await first.locator('.seg-bot').click();
   assert.equal(await first.locator('.player-version').inputValue(),'1');
   assert.ok(await first.locator('.seat-version summary').isVisible());
   await first.locator('.seat-version summary').click();
   await page.keyboard.press('Escape');
   assert.ok(await first.locator('.version-options').isHidden());
   assert.ok(await page.locator('#modal-player-setup').isVisible());
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
   assert.ok(await page.locator('#btn-start-game').isEnabled());
   if(process.env.PREVIEW_DIR)await page.locator('#modal-player-setup .dialog-card').screenshot({path:path.join(process.env.PREVIEW_DIR,`bot-versions-${width}.png`)});
   await page.locator('#btn-start-game').click();
   await page.waitForURL('**/match/fixture');
   assert.deepEqual(posted.players.map(p=>[p.botId,p.version]),[['a',1],['b',null]]);
   assert.deepEqual(errors,[]);
   await page.close();
  }
  console.log('PASS: homepage version defaults, bot changes, Human toggle, old-version notice, posted selection and 1280/390/320px layouts.');
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
