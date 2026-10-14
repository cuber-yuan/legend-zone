/* Authoritative state and presentation are separate: queued drops never lose moves. */
const COLS = 7, ROWS = 6, CELL = 80, BOARD_X = 40, BOARD_Y = 100;
const emptyBoard = () => Array.from({ length: ROWS }, () => Array(COLS).fill(0));
const copyBoard = value => value.map(row => row.slice());
const settings = window.CONNECT4_CONFIG;
const motionPreference = window.matchMedia('(prefers-reduced-motion: reduce)');
let board = emptyBoard(), displayBoard = emptyBoard(), lastMove = null;
let gameOver = true, userId = null, currentGameId = null, currentPlayer = 1;
let playerTypes = { '1': 'bot', '2': 'bot' };
let players = [];
let awaitingMove = false, isSpectator = false, isReplayMode = false;
let scene = null, ghost = null, highlights = null, tokenObjects = [];
let fallingToken = null, animationGeneration = 0, isAnimating = false;
let frames = [], pendingFinish = null, replayMoves = [], replayWinner = 0, replayIndex = 0;
let replaySnap = false, queuedReplayIndex = null, hoveredColumn = null;
const centerX = x => BOARD_X + x * CELL + CELL / 2;
const centerY = y => BOARD_Y + y * CELL + CELL / 2;

function canPlay() {
  return !!scene && !!userId && !gameOver && !isSpectator && !isReplayMode &&
    !awaitingMove && !isAnimating && frames.length === 0 && playerTypes[String(currentPlayer)] === 'human';
}

function resultMessage(winner) {
  return winner === 1 || winner === 2 ? `${playerName(winner)} wins` : 'Draw';
}

function parsePlayers(value) {
  const parsed = typeof value === 'string' ? JSON.parse(value) : value;
  if (!parsed) return [];
  const entries = Array.isArray(parsed) ? parsed : [parsed.player_1, parsed.player_2];
  return entries.map(player => typeof player === 'string' ? { name: player } : player || {});
}

function playerName(side) {
  return players[side - 1]?.name || `Player ${side}`;
}

function applyPlayers(value) {
  if (!value) return;
  try { players = parsePlayers(value); }
  catch (error) { console.error('Failed to parse match players:', error); }
}

function renderHUD(message) {
  document.querySelectorAll('.match-player').forEach(el => {
    const side = Number(el.dataset.playerSlot);
    el.querySelector('.match-player-name').textContent = playerName(side);
  });
  document.querySelectorAll('[data-column]').forEach(button => {
    button.disabled = !canPlay() || board[0][Number(button.dataset.column)] !== 0;
  });
  document.getElementById('spectatorBadge').style.display = isSpectator && !isReplayMode ? 'block' : 'none';
  const hint = document.getElementById('turnHint');
  const showHint = !gameOver && !isReplayMode && !isSpectator && Object.values(playerTypes).includes('human');
  hint.style.display = showHint ? 'block' : 'none';
  if (!showHint) hint.textContent = '';
  else if (message) hint.textContent = message;
  else if (isAnimating || frames.length) hint.textContent = 'Disc in motion…';
  else if (awaitingMove) hint.textContent = 'Move submitted · waiting for the board';
  else hint.textContent = playerTypes[String(currentPlayer)] === 'human'
    ? `${playerName(currentPlayer)} to move · choose a column`
    : `Waiting for ${playerName(currentPlayer)}…`;
  updatePreview(hoveredColumn);
}

function makeDiscTexture(player) {
  const texture = scene.textures.createCanvas(`disc-${player}`, 128, 128);
  const ctx = texture.context;
  const colors = player === 1 ? ['#bfdbfe', '#60a5fa', '#2563eb', '#1646a2'] : ['#ffe4e6', '#fb8b9b', '#f05270', '#be244b'];
  const gradient = ctx.createRadialGradient(43, 34, 3, 65, 66, 59);
  gradient.addColorStop(0, colors[0]); gradient.addColorStop(0.3, colors[1]);
  gradient.addColorStop(0.78, colors[2]); gradient.addColorStop(1, colors[3]);
  ctx.beginPath(); ctx.arc(64, 64, 58, 0, Math.PI * 2); ctx.fillStyle = gradient; ctx.fill();
  ctx.lineWidth = 2; ctx.strokeStyle = 'rgba(255,255,255,0.4)'; ctx.stroke();
  ctx.beginPath(); ctx.arc(64, 64, 45, 0, Math.PI * 2); ctx.strokeStyle = 'rgba(15,23,42,0.15)'; ctx.stroke();
  ctx.beginPath(); ctx.arc(62, 60, 46, Math.PI * 1.1, Math.PI * 1.8);
  ctx.strokeStyle = 'rgba(255,255,255,0.5)'; ctx.lineWidth = 3; ctx.stroke();
  texture.refresh();
}

function makeBoardTexture() {
  const texture = scene.textures.createCanvas('c4-frame', 640, 640);
  const ctx = texture.context;
  const gradient = ctx.createLinearGradient(0, 84, 640, 596);
  gradient.addColorStop(0, '#31517b'); gradient.addColorStop(0.45, '#233e63'); gradient.addColorStop(1, '#142b49');
  ctx.beginPath(); ctx.roundRect(24, 84, 592, 512, 22); ctx.fillStyle = gradient; ctx.fill();
  ctx.strokeStyle = 'rgba(255,255,255,0.25)'; ctx.lineWidth = 2; ctx.stroke();
  ctx.globalCompositeOperation = 'destination-out';
  for (let y = 0; y < ROWS; y++) for (let x = 0; x < COLS; x++) {
    ctx.beginPath(); ctx.arc(centerX(x), centerY(y), CELL * 0.38, 0, Math.PI * 2); ctx.fill();
  }
  ctx.globalCompositeOperation = 'source-over';
  for (let y = 0; y < ROWS; y++) for (let x = 0; x < COLS; x++) {
    ctx.beginPath(); ctx.arc(centerX(x), centerY(y), CELL * 0.395, 0, Math.PI * 2);
    ctx.strokeStyle = 'rgba(4,16,34,0.55)'; ctx.lineWidth = 3; ctx.stroke();
    ctx.beginPath(); ctx.arc(centerX(x), centerY(y) + 1, CELL * 0.4, 0.12, Math.PI - 0.12);
    ctx.strokeStyle = 'rgba(147,197,253,0.16)'; ctx.lineWidth = 1.5; ctx.stroke();
  }
  texture.refresh();
}

function create() {
  scene = this;
  makeDiscTexture(1); makeDiscTexture(2); makeBoardTexture();
  const backing = scene.add.graphics().setDepth(0);
  backing.fillStyle(0x0f172a, 0.05); backing.fillEllipse(320, 620, 555, 22);
  backing.fillStyle(0x10243f); backing.fillRoundedRect(24, 96, 592, 512, 22);
  backing.fillStyle(0x1b3353); backing.fillRoundedRect(18, 602, 604, 12, 6);
  for (let y = 0; y < ROWS; y++) for (let x = 0; x < COLS; x++) {
    backing.fillStyle(0x0c1c32); backing.fillCircle(centerX(x), centerY(y), CELL * 0.39);
    backing.lineStyle(1, 0x83a3cc, 0.13); backing.strokeCircle(centerX(x), centerY(y) + 2, CELL * 0.35);
  }
  scene.add.image(0, 0, 'c4-frame').setOrigin(0).setDepth(20);
  highlights = scene.add.graphics().setDepth(25);
  ghost = scene.add.image(centerX(3), 42, 'disc-1').setDisplaySize(70, 70).setAlpha(0.65).setDepth(30).setVisible(false);
  scene.input.on('pointermove', pointer => updatePreview(Math.floor((pointer.x - BOARD_X) / CELL)));
  scene.input.on('pointerdown', pointer => sendPlayerMove(Math.floor((pointer.x - BOARD_X) / CELL)));
  scene.input.on('gameout', () => updatePreview(null));
  renderBoard(displayBoard); renderHUD();
  if (queuedReplayIndex !== null) {
    const index = queuedReplayIndex; queuedReplayIndex = null; replayController.render(index);
  }
  pumpFrames();
}

const phaserGame = new Phaser.Game({
  type: Phaser.AUTO, width: 640, height: 640, parent: 'phaser-container', transparent: true,
  resolution: Math.min(window.devicePixelRatio || 1, 2),
  scale: { mode: Phaser.Scale.FIT, autoCenter: Phaser.Scale.CENTER_HORIZONTALLY },
  scene: { create },
});

function winningCells(snapshot) {
  for (let y = 0; y < ROWS; y++) for (let x = 0; x < COLS; x++) {
    const player = snapshot[y][x];
    if (!player) continue;
    for (const [dx, dy] of [[1, 0], [0, 1], [1, 1], [1, -1]]) {
      const cells = Array.from({ length: 4 }, (_, i) => ({ x: x + dx * i, y: y + dy * i }));
      if (cells.every(c => c.x >= 0 && c.x < COLS && c.y >= 0 && c.y < ROWS && snapshot[c.y][c.x] === player)) return cells;
    }
  }
  return [];
}

function renderBoard(snapshot, move = lastMove) {
  displayBoard = copyBoard(snapshot); lastMove = move;
  if (!scene) return;
  tokenObjects.forEach(token => token.destroy()); tokenObjects = [];
  for (let y = 0; y < ROWS; y++) for (let x = 0; x < COLS; x++) {
    if (snapshot[y][x]) tokenObjects.push(scene.add.image(centerX(x), centerY(y), `disc-${snapshot[y][x]}`)
      .setDisplaySize(64, 64).setDepth(10));
  }
  highlights.clear();
  const winners = winningCells(snapshot);
  if (winners.length) {
    highlights.lineStyle(3, 0xfde68a, 0.9);
    winners.forEach(c => highlights.strokeCircle(centerX(c.x), centerY(c.y), 27));
  } else if (move && snapshot[move.y] && snapshot[move.y][move.x]) {
    highlights.lineStyle(2, 0xffffff, 0.7); highlights.strokeCircle(centerX(move.x), centerY(move.y), 25);
  }
}

function updatePreview(column) {
  hoveredColumn = column;
  if (!ghost) return;
  const visible = canPlay() && Number.isInteger(column) && column >= 0 && column < COLS && board[0][column] === 0;
  ghost.setVisible(visible);
  if (visible) ghost.setTexture(`disc-${currentPlayer}`).setX(centerX(column));
}

function cancelMotion() {
  animationGeneration++;
  if (fallingToken) { scene.tweens.killTweensOf(fallingToken); fallingToken.destroy(); fallingToken = null; }
  isAnimating = false;
}

function addedDisc(target) {
  const changes = [];
  for (let y = 0; y < ROWS; y++) for (let x = 0; x < COLS; x++) {
    if (target[y][x] !== displayBoard[y][x]) {
      if (displayBoard[y][x] !== 0 || ![1, 2].includes(target[y][x])) return null;
      changes.push({ x, y, player: target[y][x] });
    }
  }
  return changes.length === 1 ? changes[0] : null;
}

function transitionBoard(target, move, done, interval = 750) {
  const drop = addedDisc(target);
  if (!scene || !drop || motionPreference.matches) { renderBoard(target, move); done(); return; }
  isAnimating = true; renderHUD();
  const generation = animationGeneration;
  const duration = Math.min(230 + drop.y * 45, interval * 0.7);
  fallingToken = scene.add.image(centerX(drop.x), 40, `disc-${drop.player}`).setDisplaySize(64, 64).setDepth(10);
  const complete = () => {
    if (generation !== animationGeneration) return;
    fallingToken.destroy(); fallingToken = null; isAnimating = false;
    renderBoard(target, move || drop); done();
  };
  scene.tweens.add({ targets: fallingToken, y: centerY(drop.y), duration, ease: 'Quad.easeIn', onComplete: () => {
    if (generation !== animationGeneration) return;
    if (duration < 200) { complete(); return; }
    scene.tweens.add({ targets: fallingToken, y: centerY(drop.y) - 5, duration: 65,
      yoyo: true, ease: 'Sine.easeOut', onComplete: complete });
  }});
}

function pumpFrames() {
  if (!scene || isAnimating) return;
  const frame = frames.shift();
  if (!frame) {
    renderHUD();
    if (pendingFinish) {
      const result = pendingFinish; pendingFinish = null;
      startReplay(result.move_history || [], result.winner, false, result.error_msg);
    }
    return;
  }
  transitionBoard(frame.board, frame.move, () => {
    if (frame.winner || frame.error) {
      gameOver = true; showResult(frame.winner || 0, frame.error);
    }
    pumpFrames();
  });
}

function showResult(winner, error) {
  const result = document.getElementById('gameResult');
  result.classList.add('visible');
  document.getElementById('resultTitle').textContent = error && !winner ? 'Match ended' : resultMessage(winner);
  const detail = document.getElementById('resultDetail');
  detail.textContent = error || '';
  detail.hidden = !error;
}

function applyState(data) {
  applyPlayers(data.players);
  if (data.board) board = copyBoard(data.board);
  if (data.current_player) currentPlayer = data.current_player;
  if (data.player_types) playerTypes = data.player_types;
}

function resetGame(data, spectator = false) {
  replayController.pause(); cancelMotion(); frames = []; pendingFinish = null;
  isReplayMode = false; isSpectator = spectator; gameOver = false; awaitingMove = false;
  currentGameId = data.game_id; applyState(data); lastMove = null;
  document.getElementById('gameResult').classList.remove('visible');
  replayController.hide();
  replayController.setStatus('');
  renderBoard(board, null); renderHUD();
}

const socket = io('/connect4');
socket.on('init', data => { userId = data.user_id; renderHUD(); });
socket.on('game_started', data => resetGame(data));
socket.on('match_started', data => resetGame(data, true));
socket.on('update', data => {
  if (settings.matchId ? data.match_id && data.match_id !== settings.matchId : !currentGameId || data.game_id !== currentGameId) return;
  if (isReplayMode) return;
  awaitingMove = false; applyState(data);
  if (data.winner || data.error_msg) gameOver = true;
  frames.push({ board: copyBoard(board), move: data.ai_move || lastMove, winner: data.winner, error: data.error_msg });
  renderHUD(); pumpFrames();
});
socket.on('match_status', data => {
  if (data.match_id !== settings.matchId) return;
  applyPlayers(data.players);
  if (data.status === 'playing') resetGame(data, true);
  else if (data.status === 'finished') startReplay(data.move_history || [], data.winner, true);
  else if (data.status === 'not_started') autoStartMatch(data.players);
});
socket.on('match_finished', data => {
  if (data.match_id !== settings.matchId) return;
  gameOver = true;
  // Do not replace the final falling disc with replay frame zero.
  pendingFinish = data; pumpFrames();
});

const replayController = new ReplayController({
  baseIntervalMs: 750,
  onRender: index => {
    if (!scene) { queuedReplayIndex = index; return; }
    const previousIndex = replayIndex;
    cancelMotion(); frames = [];
    const snapshot = emptyBoard();
    for (let i = 0; i < index; i++) {
      const move = replayMoves[i]; snapshot[move.y][move.x] = move.player;
    }
    replayIndex = index;
    const move = index ? replayMoves[index - 1] : null;
    const done = () => {
      if (index === replayMoves.length) showResult(replayWinner);
      renderHUD();
    };
    document.getElementById('gameResult').classList.remove('visible');
    if (!replaySnap && index === previousIndex + 1) {
      const before = copyBoard(snapshot); before[move.y][move.x] = 0;
      renderBoard(before, index > 1 ? replayMoves[index - 2] : null);
      transitionBoard(snapshot, move, done, replayController.intervalMs);
    } else { renderBoard(snapshot, move); done(); }
  },
});

function startReplay(moves, winner, autoplay = true, error = null) {
  cancelMotion(); frames = []; pendingFinish = null;
  isReplayMode = true; isSpectator = false; gameOver = true;
  replayMoves = moves; replayWinner = winner; replayIndex = 0;
  replaySnap = true;
  replayController.load(moves.length);
  if (!autoplay) replayController.goto(moves.length);
  replaySnap = false;
  replayController.setStatus(`${error || resultMessage(winner)} · ${moves.length} drops`);
  if (autoplay) replayController.play();
  else showResult(winner, error);
  renderHUD();
}

function autoStartMatch(playersJson) {
  try {
    applyPlayers(playersJson); renderHUD();
    const players = parsePlayers(playersJson);
    if (players.length < 2 || !players[0] || !players[1]) return;
    const [p1, p2] = players;
    socket.emit('new_game', { user_id: userId, black_bot: p1.bot_id || null, white_bot: p2.bot_id || null,
      black_is_human: p1.type === 'human', white_is_human: p2.type === 'human', match_id: settings.matchId });
  } catch (error) { console.error('Failed to parse match players:', error); }
}

function sendPlayerMove(column) {
  if (!canPlay() || !Number.isInteger(column) || column < 0 || column >= COLS || board[0][column] !== 0) return;
  awaitingMove = true; renderHUD();
  socket.emit('player_move', { user_id: userId, x: column, game_id: currentGameId });
}

document.querySelectorAll('[data-column]').forEach(button => {
  const column = Number(button.dataset.column);
  button.addEventListener('click', () => sendPlayerMove(column));
  button.addEventListener('focus', () => updatePreview(column));
  button.addEventListener('mouseenter', () => updatePreview(column));
  button.addEventListener('mouseleave', () => updatePreview(null));
  button.addEventListener('blur', () => updatePreview(null));
});
applyPlayers(settings.players);
replayController.attach(); renderHUD();
if (settings.status === 'finished') startReplay(settings.moves || [], settings.winner, true);
else if (settings.matchId) {
  const join = () => {
    if (socket.connected && userId) socket.emit('join_match', { match_id: settings.matchId });
    else setTimeout(join, 100);
  };
  join();
}
// FIT keeps logical coordinates stable; resizing also settles any interrupted drop.
window.addEventListener('resize', () => {
  if (!scene || !isAnimating) return;
  cancelMotion();
  if (isReplayMode) { replaySnap = true; replayController.render(replayIndex); replaySnap = false; }
  else { frames = []; renderBoard(board); pumpFrames(); }
});
motionPreference.addEventListener('change', () => {
  if (!motionPreference.matches || !isAnimating) return;
  cancelMotion();
  if (isReplayMode) { replaySnap = true; replayController.render(replayIndex); replaySnap = false; }
  else { frames = []; renderBoard(board); pumpFrames(); }
});
