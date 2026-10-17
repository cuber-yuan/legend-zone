// Real templates and static files, synthetic data, no application startup.
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const {spawnSync} = require('node:child_process');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '..');
const rendered = spawnSync(process.env.PYTHON_PATH || 'python', ['-c', `
import json
from types import SimpleNamespace
from jinja2 import Environment,FileSystemLoader
env=Environment(loader=FileSystemLoader('app/templates'),autoescape=True)
env.globals['url_for']=lambda e,**kw:'/static/'+kw['filename'] if e=='static' else '/'+e
env.globals['current_user']=SimpleNamespace(is_authenticated=False)
env.globals['request']=SimpleNamespace(path='/bot/test',endpoint='main.bot_detail')
bot={'id':'test','name':'Test Bot','owner':'Owner','language':'cpp','game':'Connect Four','rating':1500,
     'latest_version':2,'user_id':1,'is_private':False,'is_owner':False,'source_code':'print("fixture")'}
matches=[{'id':'match-1','game':'Connect Four','status':'finished','winner':0,'player_1':'<script>bad</script>'+('LongName'*15),
          'player_1_id':'test','player_1_version':1,'player_2':'Human','player_2_is_human':True,'created_at':'2026-10-17T01:02:00Z','rating_delta':16.125}]
pages={}
for name in ('public','private','owner','empty'):
 b=dict(bot)
 if name in ('private','owner'):b.update(is_private=True,is_owner=name=='owner')
 if name=='private':b.pop('source_code')
 pages[name]=env.get_template('bot_detail.html').render(bot=b,versions=[],history=[],history_total=0,history_limit=20,recent_matches=[] if name=='empty' else matches)
pages['home']=env.get_template('index.html').render()
print(json.dumps({'pages':pages,'matches':matches}))
`], {cwd:root,encoding:'utf8',env:{...process.env,PYTHONIOENCODING:'utf-8'}});
assert.equal(rendered.status, 0, rendered.stderr);
const {pages,matches} = JSON.parse(rendered.stdout);
(async () => {
 const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
 try {
  for (const [name,html] of Object.entries(pages)) {
   const page=await browser.newPage(),errors=[];
   page.on('pageerror', e=>errors.push(e.message));
   await page.addInitScript(()=>{window.io=()=>({on(e,fn){if(e==='latest_matches')document.addEventListener('DOMContentLoaded',()=>fn({matches:window.fixtureMatches}));},emit(){}});});
   await page.addInitScript(data=>{window.fixtureMatches=data;},matches);
   await page.route('**/*',r=>{
    const url=new URL(r.request().url());
    if(url.hostname==='cdn.tailwindcss.com')return r.fulfill({body:fs.readFileSync(path.join(process.env.PREVIEW_DIR,'tailwind.js')),contentType:'application/javascript'});
    if(url.pathname==='/page')return r.fulfill({body:html,contentType:'text/html'});
    const file=path.join(root,'app',url.pathname);
    if(url.pathname.startsWith('/static/')&&fs.existsSync(file))return r.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'image/svg+xml'});
    return r.fulfill({body:'',contentType:'application/javascript'});
   });
   await page.goto('http://fixture.test/page');
   const tbody=page.locator(name==='home'?'#latest-matches-tbody':'#bot-matches-tbody');
   assert.equal(await tbody.locator('tr').count(),1,name);
   if(name==='empty')assert.match(await tbody.innerText(),/No matches yet/);
   else {
    assert.equal(await tbody.locator('.lm-watch').getAttribute('href'),'/match/match-1');
    assert.equal(await tbody.locator('.lm-pname').first().textContent(),matches[0].player_1);
    assert.equal(await tbody.locator('script').count(),0);
    assert.equal(await tbody.locator('[title="Winner"]').count(),1);
   }
   if(name!=='home') {
    assert.equal(await page.locator('.lm-table th').first().textContent(),'Rating Δ');
    if(name!=='empty') {
     assert.equal(await tbody.locator('.lm-rating').textContent(),'+16.13');
     assert.equal(await tbody.locator('.lm-rating').evaluate(el=>getComputedStyle(el).color),'rgb(22, 163, 74)');
     await page.evaluate(data=>{
      MatchTable.render(document.getElementById('bot-matches-tbody'),
        [-12.25,0,null].map(rating_delta=>({...data,rating_delta})), 'No matches yet.', {showRatingDelta:true});
     }, matches[0]);
     assert.deepEqual(await tbody.locator('.lm-rating').allTextContents(),['-12.25','0.00','-']);
     assert.deepEqual(await tbody.locator('.lm-rating').evaluateAll(els=>els.map(el=>getComputedStyle(el).color)),
       ['rgb(220, 38, 38)','rgb(100, 116, 139)','rgb(100, 116, 139)']);
    }
    assert.equal(await page.locator('#source-panel').isVisible(),false);
    await page.getByRole('tab',{name:'Source Code'}).click();
    assert.equal(await page.locator('#matches-panel').isVisible(),false);
    assert.equal(await page.locator('#source-panel').isVisible(),true);
    if(name==='private') {
     assert.match(await page.locator('#source-panel').innerText(),/source code is private/);
     assert.ok(!html.includes('print(&#34;fixture&#34;)'));
     assert.equal(await page.locator('#copy-code,#toggle-visibility').count(),0);
    } else {
     assert.equal(await page.locator('#bot-source').textContent(),'print("fixture")');
     assert.equal(await page.locator('#toggle-visibility').count(),name==='owner'?1:0);
    }
    await page.getByRole('tab',{name:'Source Code'}).press('ArrowLeft');
    assert.equal(await page.locator('#matches-tab').getAttribute('aria-selected'),'true');
   } else {
    assert.equal(await page.locator('.lm-table th').first().textContent(),'Game');
    assert.equal(await tbody.locator('td').first().textContent(),'Connect Four');
   }
   for(const width of [1280,390,320]) {
    await page.setViewportSize({width,height:1000});
    await page.waitForTimeout(100);
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`${name} overflow ${width}`);
    if(name!=='home') {
     await page.getByRole('tab',{name:'Source Code'}).click();
     assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`${name} source overflow ${width}`);
     await page.getByRole('tab',{name:'Recent Matches'}).click();
    }
    if(name==='public'&&width===390)await page.screenshot({path:path.join(process.env.PREVIEW_DIR,'bot-matches-390.png'),fullPage:true});
   }
   assert.deepEqual(errors,[],name);
   console.log(`${name}: tabs, table, permissions and desktop/390/320 layout OK`);
   await page.close();
  }
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
