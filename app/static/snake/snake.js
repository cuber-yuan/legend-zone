// --- Audio Setup ---
let bgmAudio = new Audio('/static/snake/assets/snake.m4a');
bgmAudio.loop = true;
bgmAudio.volume = 1;
let moveAudio = new Audio('/static/snake/assets/move.mp3');
moveAudio.volume = 0.2;
let explosionAudio = new Audio('/static/snake/assets/explosion.mp3');
explosionAudio.volume = 0.3;
let gameoverAudio = new Audio('/static/snake/assets/gameover.m4a');
gameoverAudio.volume = 1;

// Play a clip, restarting one-shots so repeated replay ticks retrigger them.
// Swallows the autoplay-policy rejection (resolved after the first user gesture).
function _tryPlay(audio) {
    if (!audio) return;
    if (!audio.loop) audio.currentTime = 0;
    const p = audio.play();
    if (p && p.catch) p.catch(() => {});
}

// --- Phaser Scene Definition ---
class SnakeScene extends Phaser.Scene {
    constructor() {
        super({ key: 'SnakeScene' });
        this.fieldWidth = 0;
        this.fieldHeight = 0;
        this.snake1 = [];
        this.snake2 = [];
        this.obstacles = [];
        this.CELL_SIZE = 0;
        this.obstacleLayer = null;
        this.snake1Layer = null;
        this.snake2Layer = null;
        this.turn = 0;
    }

    create() {
        this.boardLayer = this.add.graphics();
        this.obstacleLayer = this.add.graphics();
        this.snake1Layer = this.add.graphics();
        this.snake2Layer = this.add.graphics();
        this.waitingText = this.add.text(this.scale.width / 2, this.scale.height / 2, 'Waiting for match…', {
            fontFamily: 'system-ui, sans-serif', fontSize: '15px', color: '#94a3b8'
        }).setOrigin(0.5);
    }

    updateFromState(state) {
        if (!state) return;
        if (state.width && state.height) {
            this.drawInitialState(state);
        } else {
            this.applyActions(state);
        }
        const turnCounter = document.getElementById('turnCounter');
        if (turnCounter) {
            turnCounter.textContent = `Turn: ${this.turn}`;
        }
    }

    drawInitialState(state) {
        if (this.waitingText) { this.waitingText.destroy(); this.waitingText = null; }
        this.fieldWidth = state.width;
        this.fieldHeight = state.height;
        this.obstacles = state.obstacle;
        this.turn = 0;
        this.snake1 = [{ x: state['0'].x, y: state['0'].y, dir: -1 }];
        this.snake2 = [{ x: state['1'].x, y: state['1'].y, dir: -1 }];
        resizeCanvas();
    }

    applyActions(actions) {
        this.turn += 1;
        // Directions: 0=up, 1=right, 2=down, 3=left
        const directions = [
            { x: -1, y: 0 },
            { x: 0, y: 1 },
            { x: 1, y: 0 },
            { x: 0, y: -1 }
        ];
        // Snake 1
        const head1 = this.snake1[0];
        const newHead1 = {
            x: head1.x + directions[actions['0']].x,
            y: head1.y + directions[actions['0']].y,
            dir: actions['0']
        };
        this.snake1.unshift(newHead1);
        // Snake 2
        const head2 = this.snake2[0];
        const newHead2 = {
            x: head2.x + directions[actions['1']].x,
            y: head2.y + directions[actions['1']].y,
            dir: actions['1']
        };
        this.snake2.unshift(newHead2);

        // Growth logic
        let shouldGrow = false;
        if (this.turn <= 25) {
            shouldGrow = true;
        } else if ((this.turn - 25) % 3 === 0) {
            shouldGrow = true;
        }
        if (!shouldGrow) {
            this.snake1.pop();
            this.snake2.pop();
        }
        this.renderAll();
    }

    renderBoard() {
        const g = this.boardLayer;
        const c = this.CELL_SIZE;
        g.clear();
        g.fillStyle(0x111f32);
        g.fillRect(0, 0, this.scale.width, this.scale.height);
        for (let row = 0; row < this.fieldHeight; row++) {
            for (let col = 0; col < this.fieldWidth; col++) {
                g.fillStyle((row + col) % 2 ? 0x1b2c42 : 0x19293e);
                g.fillRoundedRect(col * c + c * 0.035, row * c + c * 0.035,
                    c * 0.93, c * 0.93, c * 0.09);
            }
        }
    }

    renderAll() {
        const g = this.obstacleLayer;
        const c = this.CELL_SIZE;
        g.clear();
        this.obstacles.forEach(obs => {
            const x = (obs.y - 0.5) * c;
            const y = (obs.x - 0.5) * c;
            g.fillStyle(0x080f1c, 0.45);
            g.fillRoundedRect(x - c * 0.38, y - c * 0.32, c * 0.76, c * 0.76, c * 0.15);
            g.fillStyle(0x64748b);
            g.fillRoundedRect(x - c * 0.38, y - c * 0.38, c * 0.76, c * 0.72, c * 0.15);
            g.fillStyle(0x94a3b8);
            g.fillRoundedRect(x - c * 0.38, y - c * 0.38, c * 0.76, c * 0.62, c * 0.15);
            g.lineStyle(Math.max(1, c * 0.025), 0xcbd5e1, 0.6);
            g.lineBetween(x - c * 0.23, y - c * 0.25, x + c * 0.18, y - c * 0.25);
        });
        this.renderSnake(this.snake1, { body: 0x4198f5, light: 0xb8e0ff }, this.snake1Layer);
        this.renderSnake(this.snake2, { body: 0xf16c7b, light: 0xffd1d6 }, this.snake2Layer);
    }

    renderSnake(snake, palette, g) {
        g.clear();
        if (!snake.length) return;
        const c = this.CELL_SIZE;
        // State coordinates are one-based: x is row and y is column.
        const points = snake.map(segment => ({ x: (segment.y - 0.5) * c, y: (segment.x - 0.5) * c }));
        const radius = () => c * 0.19;
        // A connected silhouette keeps corners seamless; a tapered end marks the tail.
        const drawBody = (color, offset, alpha = 1) => {
            g.fillStyle(color, alpha);
            for (let i = points.length - 1; i >= 0; i--) {
                const p = points[i];
                const r = radius(i);
                if (i > 0) {
                    const q = points[i - 1];
                    const qr = radius(i - 1);
                    const angle = Math.atan2(q.y - p.y, q.x - p.x);
                    const nx = -Math.sin(angle), ny = Math.cos(angle);
                    if (i === points.length - 1) {
                        // Curved edges start tangent to the body and taper gradually into a soft tip.
                        const length = Math.hypot(p.x - q.x, p.y - q.y) + c * 0.16;
                        const tx = -Math.cos(angle), ty = -Math.sin(angle);
                        const edges = [[], []];
                        for (let step = 0; step <= 24; step++) {
                            const t = step / 24;
                            const width = r * (1 - t * t);
                            const bend = Math.sin(Math.PI * t) ** 2 * c * 0.055;
                            const x = q.x + tx * length * t + nx * bend;
                            const y = q.y + ty * length * t + ny * bend + offset;
                            edges[0].push({ x: x + nx * width, y: y + ny * width });
                            edges[1].push({ x: x - nx * width, y: y - ny * width });
                        }
                        g.fillPoints([...edges[0], ...edges[1].reverse()], true);
                        continue;
                    }
                    g.fillPoints([
                        { x: p.x + nx * r, y: p.y + ny * r + offset },
                        { x: q.x + nx * qr, y: q.y + ny * qr + offset },
                        { x: q.x - nx * qr, y: q.y - ny * qr + offset },
                        { x: p.x - nx * r, y: p.y - ny * r + offset }
                    ], true);
                }
                g.fillCircle(p.x, p.y + offset, r);
            }
        };
        drawBody(0x080f1c, c * 0.055, 0.5);
        drawBody(palette.body, 0);
        // Small chevrons follow the body toward the head, recalling the original sprites.
        const chevron = (p, direction) => {
            const nx = -direction.y, ny = direction.x;
            g.lineStyle(Math.max(0.7, c * 0.025), palette.light, 0.5);
            g.beginPath();
            g.moveTo(p.x - direction.x * c * 0.045 + nx * c * 0.065,
                p.y - direction.y * c * 0.045 + ny * c * 0.065);
            g.lineTo(p.x + direction.x * c * 0.035, p.y + direction.y * c * 0.035);
            g.lineTo(p.x - direction.x * c * 0.045 - nx * c * 0.065,
                p.y - direction.y * c * 0.045 - ny * c * 0.065);
            g.strokePath();
        };
        for (let i = 1; i < points.length - 1; i++) {
            const p = points[i], q = points[i - 1];
            const distance = Math.hypot(q.x - p.x, q.y - p.y);
            const direction = { x: (q.x - p.x) / distance, y: (q.y - p.y) / distance };
            for (const t of [0.25, 0.7]) {
                if (i === 1 && t > 0.5) continue;
                chevron({ x: p.x + (q.x - p.x) * t, y: p.y + (q.y - p.y) * t }, direction);
            }
        }
        const head = points[0];
        const drawEye = (x, y, lookX = 0, lookY = 0) => {
            g.fillStyle(0xf8fafc);
            g.fillCircle(x, y, c * 0.06);
            g.fillStyle(0x15253b);
            g.fillCircle(x + lookX * c * 0.02, y + lookY * c * 0.02, c * 0.034);
        };
        if (snake[0].dir === -1) {
            // Spawn with a round head and centered pupils before a heading is chosen.
            g.fillStyle(palette.body);
            g.fillCircle(head.x, head.y, c * 0.29);
            drawEye(head.x - c * 0.11, head.y - c * 0.04);
            drawEye(head.x + c * 0.11, head.y - c * 0.04);
            return;
        }
        const vectors = [{ x: 0, y: -1 }, { x: 1, y: 0 }, { x: 0, y: 1 }, { x: -1, y: 0 }];
        const direction = vectors[snake[0].dir] || vectors[1];
        const localPoint = (forward, side) => ({
            x: head.x + c * (direction.x * forward - direction.y * side),
            y: head.y + c * (direction.y * forward + direction.x * side)
        });
        // A symmetric top-down silhouette rotates with the movement direction.
        const headShape = [];
        for (let step = 0; step < 40; step++) {
            const angle = step * Math.PI * 2 / 40;
            headShape.push(localPoint(Math.cos(angle) * 0.37 + 0.025, Math.sin(angle) * 0.255));
        }
        g.fillStyle(palette.body);
        g.fillPoints(headShape, true);
        for (const side of [-1, 1]) {
            const eye = localPoint(0.16, side * 0.135);
            drawEye(eye.x, eye.y, direction.x, direction.y);
        }


    }
}

// --- Game State & Socket.IO ---
let userId = null;
let currentGameId = null;
let gameOver = false;
const socket = io('/snake');

// --- Match Page State ---
let isSpectator = false;
let isReplayMode = false;
let replayDisplays = [];
let playerTypes = { '1': 'bot', '2': 'bot' };

// Snake moves both seats on every turn, so there is no 'whose turn' to wait for;
// what matters is whether the local seat is human at all. Two human seats are
// refused server-side, so at most one colour is steerable from this browser.
function humanSeatName() {
    if (playerTypes['1'] === 'human') return 'Blue';
    if (playerTypes['2'] === 'human') return 'Red';
    return null;
}

function canSteer() {
    return !!currentGameId && !gameOver && !isSpectator && !isReplayMode && humanSeatName() !== null;
}

function applySeatTypes(data) {
    if (data && data.player_types) playerTypes = data.player_types;
    renderSteerHint();
}

function renderSteerHint() {
    const el = document.getElementById('turnHint');
    if (!el) return;
    if (!canSteer()) {
        el.style.display = 'none';
        return;
    }
    el.style.display = 'block';
    el.textContent = `You steer ${humanSeatName()} — press W/A/S/D or the arrow keys each turn`;
}

// --- Canvas Size Helpers ---
function getCanvasSize() {
    // const padding = window.innerWidth < 600 ? 24 : 70;
    return Math.min(window.innerWidth - 48, 600);
}
let CANVAS_SIZE = getCanvasSize();
let phaserGame;

// --- Mask Overlay ---
let maskRect = null;
let maskText = null;

function showPhaserMask(msg = "Waiting for new game...") {
    const scene = phaserGame.scene.getScene('SnakeScene');
    if (!scene) return;
    hidePhaserMask();
    const width = scene.scale.width;
    const height = scene.scale.height;
    maskRect = scene.add.rectangle(width / 2, height / 2, width, height, 0x000000, 0.35).setDepth(1000);
    maskText = scene.add.text(width / 2, height / 2, msg, {
        fontSize: Math.floor(Math.min(width, height) / 18) + 'px',
        color: '#fff',
        fontStyle: 'bold'
    }).setOrigin(0.5).setDepth(1001);
}

function hidePhaserMask() {
    if (maskRect) { maskRect.destroy(); maskRect = null; }
    if (maskText) { maskText.destroy(); maskText = null; }
}

// --- Socket.IO Event Handlers ---
socket.on('init', (data) => { userId = data.user_id; });

socket.on('game_started', (data) => {
    currentGameId = data.game_id;
    gameOver = false;
    hidePhaserMask();
    applySeatTypes(data);
    const scene = phaserGame.scene.getScene('SnakeScene');
    if (scene && typeof scene.updateFromState === 'function') {
        scene.updateFromState(data.state);
        const fc = document.getElementById('floating-corner');
        if (fc && canSteer()) {
            fc.classList.remove('hidden');
        }
        gameoverAudio.pause();
        gameoverAudio.currentTime = 0;
        bgmAudio.currentTime = 0;
        _tryPlay(bgmAudio);
    } else {
        console.error("SnakeScene or its updateFromState method is not available!");
    }
});

socket.on('update', (data) => {
    if (typeof IS_MATCH_PAGE !== 'undefined' && IS_MATCH_PAGE) {
        if (data.match_id && data.match_id !== MATCH_ID) return;
    } else {
        if (!currentGameId || data.game_id !== currentGameId) {
            console.log(`Ignoring update for irrelevant game: ${data.game_id}`);
            return;
        }
    }
    applySeatTypes(data);
    const scene = phaserGame.scene.getScene('SnakeScene');
    if (scene && typeof scene.updateFromState === 'function') {
        scene.updateFromState(data.state);
    }
    const fc = document.getElementById('floating-corner');
    if (fc && canSteer()) fc.classList.remove('hidden');
    _tryPlay(moveAudio);
});

socket.on('finish', (data) => {
    if (typeof IS_MATCH_PAGE !== 'undefined' && IS_MATCH_PAGE) {
        if (data.match_id && data.match_id !== MATCH_ID) return;
    } else {
        if (!currentGameId || data.game_id !== currentGameId) {
            console.log(`Ignoring finish for irrelevant game: ${data.game_id}`);
            return;
        }
    }
    gameOver = true;
    applySeatTypes(data);
    const fc = document.getElementById('floating-corner');
    if (fc) fc.classList.add('hidden');
    if (bgmAudio) {
        bgmAudio.pause();
        bgmAudio.currentTime = 0;
    }
    _tryPlay(explosionAudio);
    _tryPlay(gameoverAudio);
    let winner = data.winner;
    let msg = winner == 0 ? 'Blue wins!' : (winner == 1 ? 'Red wins!' : 'Draw!');
    if (data.error_msg) msg = data.error_msg;
    showPhaserMask(msg);
});

socket.on('match_status', (data) => {
    if (typeof IS_MATCH_PAGE === 'undefined' || !IS_MATCH_PAGE) return;
    if (data.match_id !== MATCH_ID) return;

    if (data.status === 'playing') {
        isSpectator = true;
        currentGameId = data.game_id;
        gameOver = false;
        applySeatTypes(data);
        hidePhaserMask();
        document.getElementById('spectatorBadge').style.display = 'block';
        const fc = document.getElementById('floating-corner');
        if (fc) fc.classList.add('hidden');
        if (data.latest_display) {
            const scene = phaserGame.scene.getScene('SnakeScene');
            if (scene) scene.updateFromState(data.latest_display);
        }
    } else if (data.status === 'finished') {
        startReplay(data.displays || [], data.winner);
    } else if (data.status === 'not_started') {
        autoStartMatch(data.players);
    }
});

socket.on('match_finished', (data) => {
    if (typeof IS_MATCH_PAGE === 'undefined' || !IS_MATCH_PAGE) return;
    if (data.match_id !== MATCH_ID) return;
    isSpectator = false;
    document.getElementById('spectatorBadge').style.display = 'none';
    startReplay(data.displays || [], data.winner);
});

// --- Match Page: Auto Start ---
function autoStartMatch(playersJson) {
    let players = [];
    try {
        const parsed = typeof playersJson === 'string' ? JSON.parse(playersJson) : playersJson;
        const normalize = (p) => (typeof p === 'string' ? { name: p } : (p || {}));
        if (Array.isArray(parsed)) {
            players = parsed.map(normalize);
        } else if (parsed && typeof parsed === 'object' && parsed.player_1) {
            players = [normalize(parsed.player_1), normalize(parsed.player_2)];
        }
    } catch (e) {
        console.error('Failed to parse match players:', e);
        return;
    }
    if (players.length < 2) return;

    socket.emit('new_game', {
        user_id: userId,
        p1_bot_id: players[0].bot_id || null,
        p2_bot_id: players[1].bot_id || null,
        p1_is_human: players[0].type === 'human',
        p2_is_human: players[1].type === 'human',
        match_id: MATCH_ID,
        game_name: (typeof MATCH_GAME_NAME !== 'undefined' && MATCH_GAME_NAME) ? MATCH_GAME_NAME : 'Snake'
    });
}

// --- Replay ---
// Rebuild state at frame index: displays[0] is the initial state, then frames 1..index are applied one by one
function renderReplayFrame(index) {
    if (!replayDisplays.length) return;
    const scene = phaserGame.scene.getScene('SnakeScene');
    if (!scene) return;

    scene.updateFromState(JSON.parse(JSON.stringify(replayDisplays[0])));
    for (let i = 1; i <= index; i++) {
        const display = replayDisplays[i];
        if (display && display['0'] !== undefined && display['1'] !== undefined) {
            scene.updateFromState(display);
        }
    }

    // Mirror the live-match audio: a move each turn, explosion+gameover at the end.
    if (index > 0) _tryPlay(moveAudio);
    if (index >= replayDisplays.length - 1 && replayDisplays.length > 1) {
        if (bgmAudio) { bgmAudio.pause(); bgmAudio.currentTime = 0; }
        _tryPlay(explosionAudio);
        _tryPlay(gameoverAudio);
    }
}

const replayController = new ReplayController({
    onRender: renderReplayFrame,
    baseIntervalMs: 800
});

function startReplay(displays, winner) {
    isReplayMode = true;
    replayDisplays = displays;
    renderSteerHint();
    const fc = document.getElementById('floating-corner');
    if (fc) fc.classList.add('hidden');


    // Start BGM; browsers block autoplay without a gesture, so arm a one-time
    // unlock that resumes it on the first click/keypress.
    if (bgmAudio) {
        gameoverAudio.pause();
        gameoverAudio.currentTime = 0;
        bgmAudio.currentTime = 0;
        _tryPlay(bgmAudio);
        const unlock = () => {
            if (isReplayMode && bgmAudio.paused) _tryPlay(bgmAudio);
            document.removeEventListener('pointerdown', unlock);
            document.removeEventListener('keydown', unlock);
        };
        document.addEventListener('pointerdown', unlock);
        document.addEventListener('keydown', unlock);
    }

    let msg = winner == 0 ? 'Blue wins!' : (winner == 1 ? 'Red wins!' : 'Draw!');
    replayController.load(Math.max(0, displays.length - 1));
    replayController.setStatus(msg + ' (' + Math.max(0, displays.length - 1) + ' turns)');
    replayController.play();
}

// --- Canvas Resize ---
function resizeCanvas() {
    if (!phaserGame) return;
    const scene = phaserGame.scene.getScene('SnakeScene');
    if (!scene || !scene.sys.isActive()) return;
    const container = document.getElementById('phaser-container');
    // Size against the frame's content area, including mobile card padding.
    const availableWidth = container.parentElement.clientWidth - 16;
    if (!scene.fieldWidth || !scene.fieldHeight) {
        const size = Math.max(1, Math.floor(availableWidth));
        container.style.width = container.style.height = size + 'px';
        scene.scale.resize(size, size);
        if (scene.waitingText) scene.waitingText.setPosition(size / 2, size / 2);
        return;
    }
    const cellSize = Math.max(1, Math.floor(availableWidth / scene.fieldWidth));
    const canvasWidth = cellSize * scene.fieldWidth;
    const canvasHeight = cellSize * scene.fieldHeight;
    container.style.width = canvasWidth + 'px';
    container.style.height = canvasHeight + 'px';
    scene.scale.resize(canvasWidth, canvasHeight);
    scene.CELL_SIZE = cellSize;
    scene.renderBoard();
    scene.renderAll();
    if (maskText) showPhaserMask(maskText.text);
}

// --- Event Listeners & Initialization ---
window.addEventListener('resize', () => {
    resizeCanvas();
});

document.addEventListener('DOMContentLoaded', () => {
    // Phaser initialization
    CANVAS_SIZE = Math.floor(document.querySelector('.snake-board-frame').clientWidth - 16);
    const config = {
        type: Phaser.AUTO,
        width: CANVAS_SIZE,
        height: CANVAS_SIZE,
        parent: 'phaser-container',
        backgroundColor: '#19293e',
        scene: [SnakeScene]
    };
    phaserGame = new Phaser.Game(config);

    // Arrow button events
    const arrowLeft = document.getElementById('arrow-left');
    const arrowDown = document.getElementById('arrow-down');
    const arrowRight = document.getElementById('arrow-right');
    const arrowUp = document.getElementById('arrow-up');
    if (arrowLeft) arrowLeft.onclick = function () { sendHumanDirection(3); };
    if (arrowDown) arrowDown.onclick = function () { sendHumanDirection(2); };
    if (arrowRight) arrowRight.onclick = function () { sendHumanDirection(1); };
    if (arrowUp) arrowUp.onclick = function () { sendHumanDirection(0); };

    // Preload audio files for caching
    const audioFiles = [
        '/static/snake/assets/snake.m4a',
        '/static/snake/assets/move.mp3',
        '/static/snake/assets/explosion.mp3',
        '/static/snake/assets/gameover.m4a'
    ];
    audioFiles.forEach(url => {
        fetch(url, { method: 'GET', cache: 'force-cache' }).catch(() => {});
    });

    // Match page vs normal page setup
    if (typeof IS_MATCH_PAGE !== 'undefined' && IS_MATCH_PAGE) {
        setupMatchPage();
    }
});

function setupMatchPage() {
    // Wire replay controls (transport buttons, slider, speed selector)
    replayController.attach();

    // Join match room after socket connects
    const waitForSocket = () => {
        if (socket.connected && userId) {
            socket.emit('join_match', { match_id: MATCH_ID });
        } else {
            setTimeout(waitForSocket, 100);
        }
    };
    waitForSocket();
}

// Keyboard control for the human seat: WASD or the arrow keys.
// direction 0=up, 1=right, 2=down, 3=left (matches DX/DY in the bot spec).
const KEY_DIRECTIONS = {
    'w': 0, 'W': 0, 'ArrowUp': 0,
    'd': 1, 'D': 1, 'ArrowRight': 1,
    's': 2, 'S': 2, 'ArrowDown': 2,
    'a': 3, 'A': 3, 'ArrowLeft': 3,
};

document.addEventListener('keydown', (e) => {
    const dir = KEY_DIRECTIONS[e.key];
    if (dir === undefined || !canSteer()) return;
    // Don't steal keys while the user is typing in a field somewhere on the page.
    const tag = e.target && e.target.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
    e.preventDefault();  // arrow keys would otherwise scroll the page
    sendHumanDirection(dir);
});

// Send human player's direction to server
function sendHumanDirection(dir) {
    if (!canSteer()) return;
    const fc = document.getElementById('floating-corner');
    if (fc) fc.classList.add('hidden');
    socket.emit('player_move', {
        user_id: userId,
        game_id: currentGameId,
        move: JSON.stringify({ response: { direction: dir } })
    });
}
