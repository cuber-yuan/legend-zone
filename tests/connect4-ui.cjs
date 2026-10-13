/* Run with Playwright installed, e.g. PLAYWRIGHT_MODULE=/path/to/playwright node tests/connect4-ui.cjs.
 * CONNECT4_PREVIEW_DIR optionally sets the screenshot output directory.
 * The real Phaser renderer runs against a deterministic Socket.IO adapter.
 */
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { spawnSync } = require('node:child_process');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '..');
const preview = process.env.CONNECT4_PREVIEW_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'connect4-ui-'));
const rendered = spawnSync(process.env.PYTHON_PATH || 'python', [path.join(__dirname, 'render-connect4-preview.py'), preview], {encoding:'utf8'});
assert.equal(rendered.status, 0, rendered.stderr || rendered.error?.message);
const socketStub = `window.io = () => {
  const socket = { connected: true, handlers: {}, sent: [],
    on(event, callback) { this.handlers[event] = callback; },
    emit(event, data) { this.sent.push({event, data}); }
  }; window.testSocket = socket; return socket;
};`;

async function open(page, status = 'playing') {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/socket.io.min.js', route => route.fulfill({ contentType: 'application/javascript', body: socketStub }));
  await page.route('http://connect4.test/**', route => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === '/match/smoke') return route.fulfill({ contentType: 'text/html', body: fs.readFileSync(path.join(preview, `connect4-${status}.html`), 'utf8') });
    if (pathname.startsWith('/static/')) {
      const file = path.join(root, 'app', pathname);
      const mime = pathname.endsWith('.js') ? 'application/javascript' : pathname.endsWith('.css') ? 'text/css' : 'image/svg+xml';
      if (fs.existsSync(file)) return route.fulfill({ contentType: mime, body: fs.readFileSync(file) });
    }
    return route.fulfill({ status: 404, body: '' });
  });
  await page.goto('http://connect4.test/match/smoke', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => typeof scene !== 'undefined' && scene !== null);
  await page.evaluate(() => testSocket.handlers.init({ user_id: 'u1' }));
  return errors;
}

async function start(page) {
  await page.evaluate(() => testSocket.handlers.game_started({ game_id: 'g1', board: emptyBoard(), current_player: 1, player_types: {1:'human', 2:'human'} }));
}

async function drop(page, x, player) {
  return page.evaluate(({x, player}) => {
    const next = copyBoard(board);
    let y = 5; while (y >= 0 && next[y][x]) y--;
    next[y][x] = player;
    testSocket.handlers.update({ match_id:'smoke', game_id:'g1', board:next, current_player:3-player, ai_move:{x,y,player} });
    return {x,y,player};
  }, {x,player});
}

async function settled(page) {
  await page.waitForFunction(() => !isAnimating && frames.length === 0, {timeout:15000});
}

(async () => {
  const browser = await chromium.launch({ headless:true, ...(process.env.CHROME_PATH ? {executablePath:process.env.CHROME_PATH} : {}) });
  try {
    const page = await browser.newPage({viewport:{width:1280,height:1100}});
    const errors = await open(page);
    assert.equal(await page.locator('[data-player="1"] .c4-player-label').innerText(),'GravityBot');
    assert.equal(await page.locator('[data-player="2"] .c4-player-label').innerText(),'cuber');
    assert.ok((await page.locator('[data-player="1"] .c4-player-side').textContent()).includes('Bot v3'));
    assert.ok((await page.locator('[data-player="2"] .c4-player-side').textContent()).includes('Human'));
    assert.equal(await page.evaluate(()=>Math.round(document.querySelector('.c4-arena').getBoundingClientRect().width)),
      await page.evaluate(()=>Math.round(document.querySelector('.c4-page').getBoundingClientRect().width)));
    await start(page);
    await page.locator('[data-column="3"]').click();
    await page.evaluate(() => sendPlayerMove(3));
    assert.equal(await page.evaluate(() => testSocket.sent.filter(e=>e.event==='player_move').length), 1, 'Repeated input must not double-submit');
    await drop(page, 3, 1);
    assert.equal(await page.evaluate(()=>isAnimating), true);
    await page.waitForTimeout(140);
    const inFlight = await page.evaluate(()=>({y:fallingToken.y,target:centerY(5),blocked:!canPlay()}));
    assert.ok(inFlight.y>40 && inFlight.y<inFlight.target, 'Disc should fall through intermediate positions');
    assert.ok(inFlight.blocked, 'Input must stay locked during a drop');
    await page.locator('.c4-arena').screenshot({path:path.join(preview,'connect4-falling.png')});
    // Back-to-back updates must finish in server order, without dropping a frame.
    await drop(page, 2, 2); await drop(page, 3, 1); await drop(page, 4, 2);
    await settled(page);
    assert.deepEqual(await page.evaluate(()=>displayBoard), await page.evaluate(()=>board));
    assert.equal(await page.evaluate(()=>displayBoard.flat().filter(Boolean).length),4);

    await page.evaluate(()=>testSocket.handlers.match_status({match_id:'smoke',status:'playing',game_id:'g1',board,current_player:1,player_types:{1:'human',2:'human'}}));
    assert.equal(await page.evaluate(()=>canPlay()),false,'Spectators cannot submit moves');

    await start(page);
    const winningMoves=[];
    for(const [x,p] of [[0,1],[6,2],[1,1],[6,2],[2,1],[5,2],[3,1]]) winningMoves.push(await drop(page,x,p));
    await page.evaluate(moves=>testSocket.handlers.match_finished({match_id:'smoke',winner:1,move_history:moves}),winningMoves);
    assert.equal(await page.evaluate(()=>isReplayMode),false,'Completion must wait for the final drop');
    await settled(page);
    assert.equal(await page.evaluate(()=>winningCells(displayBoard).length),4);
    assert.equal(await page.evaluate(()=>replayController.index),7);
    assert.equal(await page.locator('#resultTitle').innerText(),'GravityBot wins');
    await page.screenshot({path:path.join(preview,'connect4-desktop.png'),fullPage:true});

    // Seeking backwards or jumping snaps immediately; stepping forwards animates.
    await page.evaluate(()=>replayController.goto(2));
    assert.equal(await page.evaluate(()=>displayBoard.flat().filter(Boolean).length),2);
    assert.equal(await page.evaluate(()=>isAnimating),false);
    await page.evaluate(()=>replayController.step(1));
    assert.equal(await page.evaluate(()=>isAnimating),true);
    await page.evaluate(()=>replayController.goto(1));
    assert.equal(await page.evaluate(()=>isAnimating),false);
    assert.equal(await page.evaluate(()=>displayBoard.flat().filter(Boolean).length),1);
    await page.evaluate(()=>{replayController.setSpeed(4);replayController.play();});
    await page.waitForFunction(()=>replayController.index===7 && !isAnimating);
    assert.equal(await page.evaluate(()=>displayBoard.flat().filter(Boolean).length),7);

    // Resize during a live drop must preserve the authoritative position.
    await start(page); await drop(page,3,1);
    await page.setViewportSize({width:375,height:950});
    await settled(page);
    assert.equal(await page.evaluate(()=>displayBoard[5][3]),1);
    for(const width of [375,320]) {
      await page.setViewportSize({width,height:950});
      await page.screenshot({path:path.join(preview,`connect4-mobile-${width}.png`),fullPage:true});
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'No page overflow');
    }
    await page.emulateMedia({reducedMotion:'reduce'});
    await start(page); await drop(page,2,1);
    assert.equal(await page.evaluate(()=>isAnimating),false,'Reduced motion should snap');
    assert.equal(await page.evaluate(()=>displayBoard[5][2]),1);
    await page.evaluate(()=>applyPlayers(JSON.stringify({player_1:'Legacy Bot',player_2:{name:'<img src=x onerror=alert(1)>',type:'human'}})));
    await page.evaluate(()=>renderHUD());
    assert.equal(await page.locator('[data-player="1"] .c4-player-label').innerText(),'Legacy Bot');
    assert.equal(await page.locator('[data-player="2"] .c4-player-label img').count(),0);
    assert.deepEqual(errors,[]);

    const finished = await browser.newPage();
    const finishedErrors=await open(finished,'finished');
    await finished.waitForFunction(()=>replayController.index===1 && !isAnimating);
    assert.equal(await finished.evaluate(()=>displayBoard[5][3]),1);
    assert.deepEqual(finishedErrors,[]);
    console.log('PASS: gravity, queued moves, input lock, spectators, completion, replay/seek/4x, resize, mobile and reduced motion.');
    console.log('Screenshots: ' + preview);
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exit(1);});
