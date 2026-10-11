// This script is loaded by tank.html after the Phaser game object is created.
// The 'mainScene' variable is globally available and points to the main Phaser scene.

const FIELD_WIDTH = 9, FIELD_HEIGHT = 9;
const INIT_TANKS = [
    { x: 2, y: 0, side: 0, alive: true }, // Blue 0
    { x: 6, y: 0, side: 0, alive: true }, // Blue 1
    { x: 6, y: 8, side: 1, alive: true }, // Red 0
    { x: 2, y: 8, side: 1, alive: true }, // Red 1
];
const INIT_BASES = [
    { x: 4, y: 0, side: 0, alive: true }, // Blue base
    { x: 4, y: 8, side: 1, alive: true }, // Red base
];

// --- Extend the main Phaser scene with our game logic ---

class TankScene extends Phaser.Scene {
    constructor() {
        super({ key: 'TankScene' });
        // These properties will be initialized in create()
        this.mapLayer = null;
        this.baseLayer = null;
        this.tankLayer = null;
        this.mapDrawn = false;
        this.CELL_SIZE = 0;

        this.localTanks = [];
        this.localBases = [];
        this.turn = 1;

        // In-flight bullets (force-cleared on turn change / reset so none linger)
        this.activeBullets = [];

        // Bullet flight time in ms; all bullets in a turn still land together.
        // tank.html sets this dynamically from the replay speed during playback.
        this.bulletDurationMs = 200;
    }

    preload() {
        const assetPath = '/static/tank2/assets/';
        this.load.image('brick', assetPath + 'brick.png');
        this.load.image('steel', assetPath + 'steel.png');
        this.load.image('water', assetPath + 'water.png');
        this.load.image('base', assetPath + 'base.png');
        this.load.image('tank_blue', assetPath + 'tank_blue.png');
        this.load.image('tank_red', assetPath + 'tank_red.png');
    }

    create() {
        // window.mainScene = this;

        const canvasWidth = this.game.config.width;
        this.CELL_SIZE = canvasWidth / 9; // FIELD_WIDTH is 9

        this.mapLayer = this.add.group();
        this.baseLayer = this.add.group();
        this.tankLayer = this.add.group();

        this.mapDrawn = false;
        
        // The mask is controlled by tank.html. We no longer show it here by default.
        // if (window.showPhaserMask) {
        //     window.showPhaserMask("Select players and start a new game.");
        // }
    }

    updateFromState(state) {
        if (!state) return;

        // Init map and local state (every new game resets all state)
        if (state.brick && state.steel && state.water) {
            // New game: drop the previous game's in-flight bullets at once so none linger
            this.clearAllBullets();
            this.mapDrawn = false; // allow the map to be redrawn
            this.drawMap(state.brick, state.water, state.steel);
            this.mapDrawn = true;
            // Re-initialize local tanks and bases
            this.localTanks = INIT_TANKS.map(t => ({ ...t }));
            this.localBases = INIT_BASES.map(b => ({ ...b }));
            this.turn = 1;
            this.tankLayer.clear(true, true);
            this.baseLayer.clear(true, true);
            this.renderTanksAndBases();
            // Update the turn counter display
            const turnCounter = document.getElementById('turnCounter');
            if (turnCounter) {
                turnCounter.textContent = `Turn: ${this.turn}`;
            }
            return;
        }

        // Each turn only delivers both sides' actions
        if (state['0'] && state['1']) {
            this.applyActions(state['0'], state['1']);
            this.turn += 1;
            this.tankLayer.clear(true, true);
            this.baseLayer.clear(true, true);
            this.renderTanksAndBases();
            // Update the turn counter display
            const turnCounter = document.getElementById('turnCounter');
            if (turnCounter) {
                turnCounter.textContent = `Turn: ${this.turn}`;
            }
            return;
        }
    }

    renderTanksAndBases() {
        // Render tanks
        this.localTanks.forEach(tank => {
            if (tank.alive) {
                const spriteKey = tank.side === 0 ? 'tank_blue' : 'tank_red';
                const x = (tank.x + 0.5) * this.CELL_SIZE;
                const y = (tank.y + 0.5) * this.CELL_SIZE;
                const tankSprite = this.add.sprite(x, y, spriteKey);
                tankSprite.setDisplaySize(this.CELL_SIZE * 0.9, this.CELL_SIZE * 0.9);
                this.tankLayer.add(tankSprite);
            }
        });
        // Render bases
        this.localBases.forEach(base => {
            if (base.alive) {
                const x = (base.x + 0.5) * this.CELL_SIZE;
                const y = (base.y + 0.5) * this.CELL_SIZE;
                const baseSprite = this.add.sprite(x, y, 'base');
                baseSprite.setDisplaySize(this.CELL_SIZE, this.CELL_SIZE);
                this.baseLayer.add(baseSprite);
            }
        });
    }

    
    applyActions(actions0, actions1) {
        // Switching to the next turn: snap bullets still in flight straight to their targets and
        // destroy them, so this turn's bullets fly over a clean canvas with no visual overlap.
        this.forceFinishAllBullets();

        // Tank action order: Blue 0, Blue 1, Red 0, Red 1
        const dx = [0, 1, 0, -1], dy = [-1, 0, 1, 0];
        const tanks = this.localTanks;
        const bases = this.localBases;
        const allActions = [actions0[0], actions0[1], actions1[0], actions1[1]];

        // 1. Handle movement
        // Remember the original positions
        const origPos = tanks.map(t => ({ x: t.x, y: t.y, alive: t.alive }));

        // Resolve all moves first
        for (let i = 0; i < 4; i++) {
            const tank = tanks[i];
            if (!tank.alive) continue;
            const act = allActions[i];
            if (act >= 0 && act <= 3) { // move
                const nx = tank.x + dx[act], ny = tank.y + dy[act];
                // Bounds check
                if (nx < 0 || nx >= FIELD_WIDTH || ny < 0 || ny >= FIELD_HEIGHT) {
                    tank.alive = false; // moving off the board kills the tank
                    continue;
                }
                // Cannot move onto water, steel or brick
                if (this.mapData[ny][nx] && this.mapData[ny][nx] !== 0) {
                    tank.alive = false; // crashing into an obstacle kills the tank
                    continue;
                }
                tank.x = nx;
                tank.y = ny;
            }
            // Stay, or shooting: the tank does not move
        }

        // 3. Handle shooting (strictly follows the Tank2 rules)
        let bulletHits = []; // {x, y, type, shooter, dir, target?}
        for (let i = 0; i < 4; i++) {
            const tank = tanks[i];
            if (!tank.alive) continue;
            const act = allActions[i];
            if (act >= 4 && act <= 7) { // shoot
                const dir = act % 4;
                let x = tank.x, y = tank.y;
                while (true) {
                    x += dx[dir];
                    y += dy[dir];
                    if (x < 0 || x >= FIELD_WIDTH || y < 0 || y >= FIELD_HEIGHT) {
                        bulletHits.push({x, y, type: 'out', shooter: i, dir});
                        break;
                    }
                    if (this.mapData[y][x] === 3) { // steel
                        bulletHits.push({x, y, type: 'steel', shooter: i, dir});
                        break;
                    }
                    if (this.mapData[y][x] === 2) { // brick
                        bulletHits.push({x, y, type: 'brick', shooter: i, dir});
                        break;
                    }
                    // Check whether a tank is hit
                    let hitTank = false;
                    for (let j = 0; j < 4; j++) {
                        if (tanks[j].alive && tanks[j].x === x && tanks[j].y === y) {
                            // Head-to-head check
                            const theirAction = allActions[j];
                            const theirDir = theirAction % 4;
                            // If the other tank fires straight back, the bullets cancel out
                            if (theirAction >= 4 && theirAction <= 7 && (dir + 2) % 4 === theirDir) {
                                // Record a cancel event so the animation can show it
                                bulletHits.push({x, y, type: 'cancel', shooter: i, dir});
                            } else {
                                // Otherwise it is a plain hit
                                bulletHits.push({x, y, type: 'tank', shooter: i, dir, target: j});
                            }
                            hitTank = true;
                            break;
                        }
                    }
                    if (hitTank) break;
                    // Check whether a base is hit
                    let hitBase = false;
                    for (let b = 0; b < 2; b++) {
                        if (bases[b].alive && bases[b].x === x && bases[b].y === y) {
                            bulletHits.push({x, y, type: 'base', shooter: i, dir, target: b});
                            hitBase = true;
                            break;
                        }
                    }
                    if (hitBase) break;
                }
            }
        }

        // Collect every brick that was hit (each one is destroyed only once)
        let bricksToDestroy = new Set();
        bulletHits.forEach(hit => {
            if (hit.type === 'brick') bricksToDestroy.add(`${hit.x},${hit.y}`);
        });

        // Play all bullet animations (bullets hitting brick stop in front of it, never through)
        bulletHits.forEach(hit => {
            // Compute the animation endpoint
            let endX = hit.x, endY = hit.y;
            if (hit.type === 'brick' || hit.type === 'steel') {
                // The bullet stops one cell before the brick/steel block
                endX -= dx[hit.dir];
                endY -= dy[hit.dir];
            }
            // Other hit types (tank / base / out of bounds) stop at the hit cell
            this.fireBullet(tanks[hit.shooter].x, tanks[hit.shooter].y, hit.dir, endX, endY);
        });

        // Apply the hit effects in one pass
        bricksToDestroy.forEach(key => {
            const [x, y] = key.split(',').map(Number);
            this.mapData[y][x] = 0;
        });

        // Handle tanks and bases being destroyed
        bulletHits.forEach(hit => {
            // Only a hit of type 'tank' destroys a tank
            if (hit.type === 'tank') {
                tanks[hit.target].alive = false;
            }
            if (hit.type === 'base') {
                bases[hit.target].alive = false;
            }
        });

        this.refreshMapLayer();
    }

    drawMap(brickBinary, waterBinary, steelBinary) {
        this.mapLayer.clear(true, true);
        this.mapData = Array.from({length: FIELD_HEIGHT}, () => Array(FIELD_WIDTH).fill(0));
        const drawLayer = (binaryData, spriteKey, code) => {
            for (let i = 0; i < 3; i++) {
                let mask = 1;
                const chunk = binaryData[i];
                for (let y_offset = 0; y_offset < 3; y_offset++) {
                    for (let x_offset = 0; x_offset < FIELD_WIDTH; x_offset++) {
                        if (chunk & mask) {
                            const y = i * 3 + y_offset;
                            const x = x_offset;
                            this.mapData[y][x] = code; // 1=water, 2=brick, 3=steel
                            const tileX = (x + 0.5) * this.CELL_SIZE;
                            const tileY = (y + 0.5) * this.CELL_SIZE;
                            const tile = this.add.sprite(tileX, tileY, spriteKey);
                            tile.setDisplaySize(this.CELL_SIZE, this.CELL_SIZE);
                            this.mapLayer.add(tile);
                        }
                        mask <<= 1;
                    }
                }
            }
        };
        drawLayer(waterBinary, 'water', 1);
        drawLayer(brickBinary, 'brick', 2);
        drawLayer(steelBinary, 'steel', 3);
        this.mapLayer.clear(true, true);
        for (let y = 0; y < FIELD_HEIGHT; y++) {
            for (let x = 0; x < FIELD_WIDTH; x++) {
                let spriteKey = null;
                if (this.mapData[y][x] === 1) spriteKey = 'water';
                else if (this.mapData[y][x] === 2) spriteKey = 'brick';
                else if (this.mapData[y][x] === 3) spriteKey = 'steel';
                if (spriteKey) {
                    const tileX = (x + 0.5) * this.CELL_SIZE;
                    const tileY = (y + 0.5) * this.CELL_SIZE;
                    const tile = this.add.sprite(tileX, tileY, spriteKey);
                    tile.setDisplaySize(this.CELL_SIZE, this.CELL_SIZE);
                    this.mapLayer.add(tile);
                }
            }
        }
    }

    refreshMapLayer() {
        this.mapLayer.clear(true, true);
        for (let y = 0; y < FIELD_HEIGHT; y++) {
            for (let x = 0; x < FIELD_WIDTH; x++) {
                let spriteKey = null;
                if (this.mapData[y][x] === 1) spriteKey = 'water';
                else if (this.mapData[y][x] === 2) spriteKey = 'brick';
                else if (this.mapData[y][x] === 3) spriteKey = 'steel';
                if (spriteKey) {
                    const tileX = (x + 0.5) * this.CELL_SIZE;
                    const tileY = (y + 0.5) * this.CELL_SIZE;
                    const tile = this.add.sprite(tileX, tileY, spriteKey);
                    tile.setDisplaySize(this.CELL_SIZE, this.CELL_SIZE);
                    this.mapLayer.add(tile);
                }
            }
        }
    }

    fireBullet(fromX, fromY, dir, toX, toY) {
        // dir: 0=up, 1=right, 2=down, 3=left
        //
        // Design notes:
        //  - What moves is a small block (not a stretched line) with a fixed-length tail behind it
        //  - All bullets in one turn use the same fixed duration; once queued they advance on the
        //    same Phaser timeline, so every bullet reaches its target at the very same instant
        //  - Speed = distance / duration: an open path means a long distance, so the bullet covers
        //    more cells per tick and looks "fast"; a short path or one blocked by brick looks "slow"
        const startX = (fromX + 0.5) * this.CELL_SIZE;
        const startY = (fromY + 0.5) * this.CELL_SIZE;
        const endX = (toX + 0.5) * this.CELL_SIZE;
        const endY = (toY + 0.5) * this.CELL_SIZE;

        const cell = this.CELL_SIZE;
        const bulletSize = cell * 0.28;
        const trailLen = cell * 0.8; // tail is a fixed 0.8 cells, never stretched by distance -> no leftover line

        // The bullet block (yellow)
        const bullet = this.add.rectangle(startX, startY, bulletSize, bulletSize, 0xffeb3b);
        bullet.setDepth(20);

        // The tail graphics (yellow, semi-transparent)
        const trail = this.add.graphics();
        trail.setDepth(19);
        trail.lineStyle(bulletSize * 0.8, 0xffeb3b, 0.55);

        // Unit direction vector (used to place the tail)
        const ddx = endX - startX, ddy = endY - startY;
        const dist = Math.hypot(ddx, ddy) || 1;
        const ux = ddx / dist, uy = ddy / dist;

        const BULLET_DURATION_MS = (typeof this.bulletDurationMs === 'number' && this.bulletDurationMs > 0)
            ? this.bulletDurationMs
            : 200;

        const entry = { bullet, trail, tween: null };
        this.activeBullets.push(entry);

        entry.tween = this.tweens.add({
            targets: bullet,
            x: endX,
            y: endY,
            duration: BULLET_DURATION_MS,
            ease: 'Linear',
            onUpdate: () => {
                // Tail: extends trailLen backwards from the bullet's position
                trail.clear();
                trail.lineStyle(bulletSize * 0.8, 0xffeb3b, 0.55);
                trail.beginPath();
                trail.moveTo(bullet.x - ux * trailLen, bullet.y - uy * trailLen);
                trail.lineTo(bullet.x, bullet.y);
                trail.strokePath();
            },
            onComplete: () => {
                bullet.destroy();
                trail.destroy();
                const idx = this.activeBullets.indexOf(entry);
                if (idx >= 0) this.activeBullets.splice(idx, 1);
            }
        });
    }

    setBulletDuration(ms) {
        // Called by the replay speed control to set the bullet flight time in ms.
        // Bullets in one turn still arrive together (every tween uses the same duration).
        this.bulletDurationMs = Math.max(50, ms);
    }

    forceFinishAllBullets() {
        // Snap every in-flight bullet straight to its target and destroy it (no waiting for the duration).
        // Used when moving to the next turn or seeking in a replay, so nothing visually piles up.
        if (!this.activeBullets || this.activeBullets.length === 0) return;
        // Take a copy, because tween.complete() fires onComplete, which mutates activeBullets
        const list = this.activeBullets.slice();
        for (const entry of list) {
            if (entry.tween) entry.tween.complete();
        }
        // onComplete already spliced each entry, but reset it anyway to be safe
        this.activeBullets = [];
    }

    clearAllBullets() {
        // Destroy every in-flight bullet at once, without waiting for its tween (new game / scene reset).
        if (!this.activeBullets) return;
        for (const entry of this.activeBullets) {
            if (entry.tween) entry.tween.remove();
            if (entry.bullet && entry.bullet.scene) entry.bullet.destroy();
            if (entry.trail && entry.trail.scene) entry.trail.destroy();
        }
        this.activeBullets = [];
    }
}