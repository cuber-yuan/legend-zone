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
        document.getElementById('floating-corner').classList.remove('hidden');
        gameoverAudio.pause();
        gameoverAudio.currentTime = 0;
        bgmAudio.currentTime = 0;
        bgmAudio.play();
    } else {
        console.error("SnakeScene or its updateFromState method is not available!");
    }
});

socket.on('update', (data) => {
    if (!currentGameId || data.game_id !== currentGameId) {
        console.log(`Ignoring update for irrelevant game: ${data.game_id}`);
        return;
    }
    const scene = phaserGame.scene.getScene('SnakeScene');
    if (scene && typeof scene.updateFromState === 'function') {
        scene.updateFromState(data.state);
    }
    document.getElementById('floating-corner').classList.remove('hidden');
    moveAudio.play();
});

socket.on('finish', (data) => {
    if (!currentGameId || data.game_id !== currentGameId) {
        console.log(`Ignoring finish for irrelevant game: ${data.game_id}`);
        return;
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
    // New Game button
    document.getElementById('newGameBtn').addEventListener('click', () => {
        newGame();
    });

    // Phaser initialization
    const config = {
        type: Phaser.AUTO,
        width: CANVAS_SIZE,
        height: CANVAS_SIZE,
        parent: 'phaser-container',
        scene: [SnakeScene]
    };
    phaserGame = new Phaser.Game(config);

    // Only one human checkbox can be checked at a time
    const leftCheckbox = document.getElementById('left-is-human');
    const rightCheckbox = document.getElementById('right-is-human');
    const leftSelect = document.getElementById('aiSelectLeft');
    const rightSelect = document.getElementById('aiSelectRight');

    leftCheckbox.addEventListener('change', () => {
        if (leftCheckbox.checked) {
            rightCheckbox.checked = false;
            rightSelect.disabled = false;
            rightSelect.classList.remove('bg-gray-200', 'cursor-not-allowed');
        }
        leftSelect.disabled = leftCheckbox.checked;
        leftSelect.classList.toggle('bg-gray-200', leftCheckbox.checked);
        leftSelect.classList.toggle('cursor-not-allowed', leftCheckbox.checked);
    });

    rightCheckbox.addEventListener('change', () => {
        if (rightCheckbox.checked) {
            leftCheckbox.checked = false;
            leftSelect.disabled = false;
            leftSelect.classList.remove('bg-gray-200', 'cursor-not-allowed');
        }
        rightSelect.disabled = rightCheckbox.checked;
        rightSelect.classList.toggle('bg-gray-200', rightCheckbox.checked);
        rightSelect.classList.toggle('cursor-not-allowed', rightCheckbox.checked);
    });

    // Arrow button events
    document.getElementById('arrow-left').onclick = function () {
        sendHumanDirection(3);
    };
    document.getElementById('arrow-down').onclick = function () {
        sendHumanDirection(2);
    };
    document.getElementById('arrow-right').onclick = function () {
        sendHumanDirection(1);
    };
    document.getElementById('arrow-up').onclick = function () {
        sendHumanDirection(0);
    };

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

    
});

// Keyboard control for human player (WASD)
document.addEventListener('keydown', (e) => {
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

/**
 * WebGamePlayer: A generic Phaser-based web game replay player.
 * Usage:
 *   const player = new WebGamePlayer({
 *     phaserConfig: { ... }, // Phaser config
 *     mountId: 'phaser-container', // DOM id to mount
 *     createScene: () => new YourPhaserSceneClass(),
 *   });
 *   player.loadReplay(replayArray);
 *   player.play();
 *   player.pause();
 *   player.goto(turnIndex);
 *   player.onTurnChange = (turn) => { ... };
 */
class WebGamePlayer {
    constructor({ phaserConfig, mountId, createScene }) {
        this.mountId = mountId;
        this.createScene = createScene;
        this.phaserConfig = Object.assign({}, phaserConfig, {
            parent: mountId,
            scene: [createScene()]
        });
        this.phaserGame = new Phaser.Game(this.phaserConfig);
        this.replayArr = [];
        this.turnIdx = 0;
        this.timer = null;
        this.playing = false;
        this.onTurnChange = null;
        this.maxTurn = 0;
        this.scene = null;
        this._initSceneReady();
    }

    _initSceneReady() {
        // Wait for Phaser scene to be ready
        this.phaserGame.events.on('ready', () => {
            this.scene = this.phaserGame.scene.scenes[0];
        });
        // Fallback: try to get scene after short delay
        setTimeout(() => {
            if (!this.scene) {
                this.scene = this.phaserGame.scene.scenes[0];
            }
        }, 500);
    }

    loadReplay(replayArr) {
        this.replayArr = replayArr;
        this.maxTurn = replayArr.length - 1;
        this.turnIdx = 0;
        if (this.scene && this.replayArr.length > 0) {
            this._gotoTurn(0);
        }
    }

    play() {
        if (this.playing || !this.replayArr.length) return;
        this.playing = true;
        this._playLoop();
    }

    pause() {
        this.playing = false;
        if (this.timer) clearTimeout(this.timer);
    }

    goto(turnIdx) {
        this.pause();
        this._gotoTurn(turnIdx);
    }

    _gotoTurn(idx) {
        idx = Math.max(0, Math.min(this.maxTurn, idx));
        // Reset to initial state
        if (!this.scene) return;
        let initialState = JSON.parse(JSON.stringify(this.replayArr[0]));
        this.scene.updateFromState(initialState);
        // Apply actions incrementally
        for (let i = 1; i <= idx; ++i) {
            this.scene.updateFromState(this.replayArr[i]);
        }
        this.turnIdx = idx;
        if (typeof this.onTurnChange === 'function') {
            this.onTurnChange(idx);
        }
    }

    _playLoop() {
        if (!this.playing) return;
        if (this.turnIdx < this.maxTurn) {
            this.turnIdx++;
            this._gotoTurn(this.turnIdx);
            this.timer = setTimeout(() => this._playLoop(), 400);
        } else {
            this.pause();
        }
    }
}

// Example usage for Snake game (replace original replay logic):
// const player = new WebGamePlayer({
//     phaserConfig: {
//         type: Phaser.AUTO,
//         width: CANVAS_SIZE,
//         height: CANVAS_SIZE,
//     },
//     mountId: 'phaser-container',
//     createScene: () => new SnakeScene()
// });
// player.loadReplay(replayArr);
// player.play();
// player.pause();
// player.goto(turnIdx);
// player.onTurnChange = (idx) => { ... };

