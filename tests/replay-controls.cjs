/* Shared playback UI browser regression. Requires Playwright and Python/Jinja2. */
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const assert = require('node:assert/strict');
const {spawnSync} = require('node:child_process');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '..');
const output = process.env.CONNECT4_PREVIEW_DIR || fs.mkdtempSync(path.join(os.tmpdir(),'replay-ui-'));
const rendered = spawnSync(process.env.PYTHON_PATH || 'python', ['-c', `
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('app/templates'), autoescape=True)
env.globals['url_for'] = lambda endpoint, **kw: '/static/' + kw['filename']
print(env.get_template('components/replay_controls.html').render(replay_unit='Turn'))
`], {cwd:root,encoding:'utf8',env:{...process.env,PYTHONIOENCODING:'utf-8'}});
assert.equal(rendered.status,0,rendered.stderr);

(async()=>{
  const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
  try {
    const page=await browser.newPage({viewport:{width:1280,height:400}});
    const errors=[]; page.on('pageerror',error=>errors.push(error.message));
    await page.setContent(`<style>*{box-sizing:border-box}body{margin:0;background:#f3f4f6;font-family:Arial,sans-serif}.test-wrap{max-width:1000px;margin:32px auto;padding:0 16px}${fs.readFileSync(path.join(root,'app/static/replay-player.css'),'utf8')}</style><div class="test-wrap">${rendered.stdout.replace(/<link[^>]+>/g,'')}</div>`);
    await page.addScriptTag({path:path.join(root,'app/static/replay-player.js')});
    await page.evaluate(()=>{window.renderedFrames=[];window.replay=new ReplayController({baseIntervalMs:200,onRender:index=>renderedFrames.push(index)});replay.attach();});
    assert.ok(await page.locator('#replayControls').evaluate(el=>el.hidden));
    await page.evaluate(()=>{replay.load(10);replay.setStatus('Bot A wins · 10 turns');});
    assert.ok(await page.locator('#replayControls').isVisible());
    assert.equal(await page.locator('#replayCounter').innerText(),'0 / 10');
    assert.ok(await page.locator('#btnFirst').isDisabled());
    await page.locator('#btnPlayPause').click();
    assert.equal(await page.locator('#btnPlayPause').getAttribute('aria-label'),'Pause replay');
    await page.waitForFunction(()=>replay.index>=1);
    await page.locator('#btnPlayPause').click();
    assert.equal(await page.evaluate(()=>replay.playing),false);
    await page.locator('#replayControls').focus();
    const before=await page.evaluate(()=>replay.index);
    await page.keyboard.press('ArrowRight');
    assert.equal(await page.evaluate(()=>replay.index),before+1);
    await page.keyboard.press('ArrowLeft');
    assert.equal(await page.evaluate(()=>replay.index),before);
    await page.keyboard.press('Space');
    assert.equal(await page.evaluate(()=>replay.playing),true);
    await page.keyboard.press('Space');
    assert.equal(await page.evaluate(()=>replay.playing),false);
    await page.locator('#replaySlider').evaluate(el=>{el.value='7';el.dispatchEvent(new Event('input',{bubbles:true}));});
    assert.equal(await page.locator('#replayCounter').innerText(),'7 / 10');
    assert.equal(await page.locator('#replayControls').evaluate(el=>el.style.getPropertyValue('--rp-progress')),'70%');
    await page.locator('#replaySpeed').selectOption('2');
    assert.equal(await page.evaluate(()=>replay.speed),2);
    await page.locator('#btnLast').click();
    assert.ok(await page.locator('#btnNext').isDisabled());
    assert.equal(await page.locator('.rp-play-label').innerText(),'Replay');
    await page.locator('#btnPlayPause').click();
    assert.ok(await page.evaluate(()=>replay.index<10));
    await page.evaluate(()=>replay.pause());
    await page.evaluate(()=>{replay.load(0);});
    assert.ok(await page.locator('#btnPlayPause').isDisabled());
    assert.ok(await page.locator('#replaySlider').isDisabled());
    await page.evaluate(()=>{replay.load(42);replay.goto(17);replay.setStatus('GravityBot wins · 42 turns');});
    for(const width of [1280,760,375,320]) {
      await page.setViewportSize({width,height:400});
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`Overflow at ${width}`);
      await page.locator('#replayControls').screenshot({path:path.join(output,`replay-controls-${width}.png`)});
    }
    await page.evaluate(()=>replay.hide());
    assert.ok(await page.locator('#replayControls').isHidden());
    assert.deepEqual(errors,[]);
    console.log('PASS: shared playback, step/seek, speed, keyboard, empty replay, labels, progress and responsive layout.');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
