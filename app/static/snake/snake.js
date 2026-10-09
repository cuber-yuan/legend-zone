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

    preload() {
        const assetPath = '/static/snake/assets/';
        const colors = ['red', 'blue'];
        colors.forEach(color => {
            this.load.image(`head_${color}_nodir`, `${assetPath}head_${color}_nodir.png`);
            this.load.image(`head_${color}_dir0`, `${assetPath}head_${color}_dir0.png`);
            this.load.image(`tail_${color}_dir0`, `${assetPath}tail_${color}_dir0.png`);
            this.load.image(`body_${color}_dir0`, `${assetPath}body_${color}_dir0.png`);
            this.load.image(`body_${color}_dir01`, `${assetPath}body_${color}_dir01.png`);
        });
        this.load.image('stone', `${assetPath}stone.png`);
    }

    create() {
        this.obstacleLayer = this.add.group();
        this.snake1Layer = this.add.group();
        this.snake2Layer = this.add.group();
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
        // Directions: 0=left, 1=down, 2=right, 3=up
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

    renderAll() {
        this.obstacleLayer.clear(true, true);
        this.snake1Layer.clear(true, true);
        this.snake2Layer.clear(true, true);

        // Render obstacles
        this.obstacles.forEach(obs => {
            const x = (obs.x - 1 + 0.5) * this.CELL_SIZE;
            const y = (obs.y - 1 + 0.5) * this.CELL_SIZE;
            const sprite = this.add.sprite(y, x, 'stone');
            sprite.setDisplaySize(this.CELL_SIZE, this.CELL_SIZE);
            this.obstacleLayer.add(sprite);
        });

        // Render snakes
        this.renderSnake(this.snake1, 'blue', this.snake1Layer);
        this.renderSnake(this.snake2, 'red', this.snake2Layer);
    }

    renderSnake(snake, color, layer) {
        const dirToAngle = [90, 180, 270, 0];
        for (let i = 0; i < snake.length; i++) {
            const segment = snake[i];
            const x = (segment.x - 1 + 0.5) * this.CELL_SIZE;
            const y = (segment.y - 1 + 0.5) * this.CELL_SIZE;
            let spriteKey = '';
            let angle = 0;
            if (i === 0) {
                spriteKey = segment.dir === -1 ? `head_${color}_nodir` : `head_${color}_dir0`;
                if (segment.dir !== -1) angle = dirToAngle[segment.dir];
            } else if (i === snake.length - 1 && snake.length > 1) {
                const prevSegment = snake[i - 1];
                spriteKey = `tail_${color}_dir0`;
                angle = dirToAngle[prevSegment.dir];
            } else {
                const prevSegment = snake[i - 1];
                if (prevSegment.dir === segment.dir || (prevSegment.dir + 2) % 4 === segment.dir) {
                    spriteKey = `body_${color}_dir0`;
                    angle = dirToAngle[segment.dir];
                } else {
                    const inDir = (segment.dir + 2) % 4;
                    const outDir = prevSegment.dir;
                    spriteKey = `body_${color}_dir01`;
                    if ((inDir + 1) % 4 === outDir) {
                        angle = dirToAngle[inDir];
                    } else if ((inDir + 3) % 4 === outDir) {
                        angle = dirToAngle[outDir];
                    }
                    const sprite = this.add.sprite(y, x, spriteKey);
                    sprite.setDisplaySize(this.CELL_SIZE, this.CELL_SIZE);
                    sprite.setAngle(angle);
                    layer.add(sprite);
                    continue;
                }
            }
            if (spriteKey) {
                const sprite = this.add.sprite(y, x, spriteKey);
                sprite.setDisplaySize(this.CELL_SIZE, this.CELL_SIZE);
                sprite.setAngle(angle);
                layer.add(sprite);
            }
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
    const scene = phaserGame.scene.getScene('SnakeScene');
    if (scene && typeof scene.updateFromState === 'function') {
        scene.updateFromState(data.state);
        const fc = document.getElementById('floating-corner');
        if (fc && !(typeof IS_MATCH_PAGE !== 'undefined' && IS_MATCH_PAGE)) {
            fc.classList.remove('hidden');
        }
        gameoverAudio.pause();
        gameoverAudio.currentTime = 0;
        bgmAudio.currentTime = 0;
        bgmAudio.play();
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
    const scene = phaserGame.scene.getScene('SnakeScene');
    if (scene && typeof scene.updateFromState === 'function') {
        scene.updateFromState(data.state);
    }
    const fc = document.getElementById('floating-corner');
    if (fc) fc.classList.remove('hidden');
    moveAudio.play();
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
    if (bgmAudio) {
        bgmAudio.pause();
        bgmAudio.currentTime = 0;
    }
    explosionAudio.play();
    gameoverAudio.play();
    let winner = data.winner;
    if (winner == 0) {
        showPhaserMask('Blue wins!');
    } else if (winner == 1) {
        showPhaserMask('Red wins!');
    } else {
        showPhaserMask('Draw!');
    }
    gameOver = true;
});

socket.on('match_status', (data) => {
    if (typeof IS_MATCH_PAGE === 'undefined' || !IS_MATCH_PAGE) return;
    if (data.match_id !== MATCH_ID) return;

    if (data.status === 'playing') {
        isSpectator = true;
        currentGameId = data.game_id;
        gameOver = false;
        hidePhaserMask();
        document.getElementById('spectatorBadge').style.display = 'block';
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

// --- Game Control Functions ---
function newGame() {
    if (!userId) {
        alert("Not connected to server yet.");
        return;
    }
    const leftPlayerId = document.getElementById('aiSelectLeft').value;
    const rightPlayerId = document.getElementById('aiSelectRight').value;
    socket.emit('new_game', {
        user_id: userId,
        left_player_id: leftPlayerId,
        right_player_id: rightPlayerId,
        left_is_human: document.getElementById('left-is-human').checked,
        right_is_human: document.getElementById('right-is-human').checked,
        page_path: window.location.pathname
    });
}

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
// 重建到第 index 帧：displays[0] 是初始状态，1..index 逐帧应用
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

    const controls = document.getElementById('replayControls');
    if (controls) controls.style.display = 'flex';

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
    const scene = phaserGame.scene.getScene('SnakeScene');
    // Add a guard to prevent running with invalid dimensions
    if (!scene || !scene.fieldWidth || !scene.fieldHeight) {
        
        return;
    }
    const maxScreenWidth = Math.min(window.innerWidth * 0.95, 900);
    const cellSize = Math.floor(maxScreenWidth / scene.fieldWidth);
    const canvasWidth = cellSize * scene.fieldWidth;
    const canvasHeight = cellSize * scene.fieldHeight;
    const container = document.getElementById('phaser-container');
    container.style.width = canvasWidth + 'px';
    container.style.height = canvasHeight + 'px';
    scene.scale.resize(canvasWidth, canvasHeight);
    scene.CELL_SIZE = cellSize;
    scene.renderAll();
}

// --- Event Listeners & Initialization ---
window.addEventListener('resize', () => {
    resizeCanvas();
});

document.addEventListener('DOMContentLoaded', () => {
    // Phaser initialization
    const config = {
        type: Phaser.AUTO,
        width: CANVAS_SIZE,
        height: CANVAS_SIZE,
        parent: 'phaser-container',
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
    } else {
        setupNormalPage();
    }
});

function setupNormalPage() {
    const newGameBtn = document.getElementById('newGameBtn');
    if (newGameBtn) {
        newGameBtn.addEventListener('click', () => { newGame(); });
    }

    const leftCheckbox = document.getElementById('left-is-human');
    const rightCheckbox = document.getElementById('right-is-human');
    const leftSelect = document.getElementById('aiSelectLeft');
    const rightSelect = document.getElementById('aiSelectRight');

    if (leftCheckbox) {
        leftCheckbox.addEventListener('change', () => {
            if (leftCheckbox.checked) {
                if (rightCheckbox) rightCheckbox.checked = false;
                if (rightSelect) {
                    rightSelect.disabled = false;
                    rightSelect.classList.remove('bg-gray-200', 'cursor-not-allowed');
                }
            }
            if (leftSelect) {
                leftSelect.disabled = leftCheckbox.checked;
                leftSelect.classList.toggle('bg-gray-200', leftCheckbox.checked);
                leftSelect.classList.toggle('cursor-not-allowed', leftCheckbox.checked);
            }
        });
    }

    if (rightCheckbox) {
        rightCheckbox.addEventListener('change', () => {
            if (rightCheckbox.checked) {
                if (leftCheckbox) leftCheckbox.checked = false;
                if (leftSelect) {
                    leftSelect.disabled = false;
                    leftSelect.classList.remove('bg-gray-200', 'cursor-not-allowed');
                }
            }
            if (rightSelect) {
                rightSelect.disabled = rightCheckbox.checked;
                rightSelect.classList.toggle('bg-gray-200', rightCheckbox.checked);
                rightSelect.classList.toggle('cursor-not-allowed', rightCheckbox.checked);
            }
        });
    }
}

function setupMatchPage() {
    // Wire replay controls (transport buttons, slider, speed selector)
    replayController.attach();

    // Show player names
    showMatchPlayerNames();

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

function showMatchPlayerNames() {
    let players = [];
    try {
        const raw = (typeof MATCH_PLAYERS !== 'undefined') ? MATCH_PLAYERS : null;
        if (!raw) return;
        const parsed = typeof raw === 'string' ? JSON.parse(raw) : raw;
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

    const fmt = (p) => p && p.name ? (p.version ? `${p.name} v${p.version}` : p.name) : '';
    const blueEl = document.getElementById('bluePlayerName');
    const redEl = document.getElementById('redPlayerName');
    if (blueEl) blueEl.textContent = fmt(players[0]) || 'Player 1';
    if (redEl) redEl.textContent = fmt(players[1]) || 'Player 2';
}

// Keyboard control for human player (WASD)
document.addEventListener('keydown', (e) => {
    if (typeof IS_MATCH_PAGE !== 'undefined' && IS_MATCH_PAGE) return;
    let dir = null;
    if (e.key === 'a' || e.key === 'A') dir = 3;
    else if (e.key === 's' || e.key === 'S') dir = 2;
    else if (e.key === 'd' || e.key === 'D') dir = 1;
    else if (e.key === 'w' || e.key === 'W') dir = 0;
    if (dir !== null) {
        sendHumanDirection(dir);
    }
});

// Send human player's direction to server
function sendHumanDirection(dir) {
    document.getElementById('floating-corner').classList.add('hidden');
    socket.emit('player_move', {
        user_id: userId,
        game_id: currentGameId,
        move: JSON.stringify({ response: { direction: dir } })
    });
}
