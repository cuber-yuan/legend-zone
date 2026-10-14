// Shared Tank Battle scene for live games and match replays.

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
        this.markLayer = null;
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

        // Actions the judge saw last turn, per side per tank: -1 stay, 0-3 move,
        // 4-7 fire. Two turns of firing in a row is illegal, so the human panel
        // needs this to disable buttons instead of letting a click lose the match.
        this.lastActions = [[-1, -1], [-1, -1]];
    }

    // --- Human control helpers (used by tank.html's control panel) ---

    tankAlive(side, tank) {
        return !!(this.localTanks[side * 2 + tank] && this.localTanks[side * 2 + tank].alive);
    }

    // Mirrors tank2_judge.cpp's ActionIsValid: the judge ends the match on the
    // first illegal action, so illegal ones are never offered to a human.
    actionLegal(side, tank, act) {
        if (act < -1 || act > 7) return false;
        if (!this.tankAlive(side, tank)) return true;
        if (act >= 4 && this.lastActions[side][tank] >= 4) return false;
        if (act === -1 || act >= 4) return true;
        if (!this.mapData) return false;
        const dx = [0, 1, 0, -1], dy = [-1, 0, 1, 0];
        const t = this.localTanks[side * 2 + tank];
        const x = t.x + dx[act], y = t.y + dy[act];
        if (x < 0 || x >= FIELD_WIDTH || y < 0 || y >= FIELD_HEIGHT) return false;
        // The judge keeps terrain, bases and tanks in one bitmask per cell and only
        // allows moving onto an empty one, so all three block. Two tanks can still
        // end up stacked, but only by both moving into the same empty cell on the
        // same turn - which is why this is checked against the current positions.
        if (this.mapData[y][x] !== 0) return false;
        if (this.localBases.some((b) => b.alive && b.x === x && b.y === y)) return false;
        return !this.localTanks.some((o) => o !== t && o.alive && o.x === x && o.y === y);
    }

    tankAt(pointerX, pointerY) {
        if (!this.CELL_SIZE) return null;
        const col = Math.floor(pointerX / this.CELL_SIZE);
        const row = Math.floor(pointerY / this.CELL_SIZE);
        for (let i = 0; i < this.localTanks.length; i++) {
            const t = this.localTanks[i];
            if (t.alive && t.x === col && t.y === row) return { side: Math.floor(i / 2), tank: i % 2 };
        }
        return null;
    }

    onTankPicked(handler) {
        if (this._pickBound) return;
        this._pickBound = true;
        this.input.on('pointerdown', (pointer) => {
            const hit = this.tankAt(pointer.x, pointer.y);
            if (hit) handler(hit.side, hit.tank);
        });
    }

    // Hover is reported only when the tank under the cursor changes, so the
    // control popover can open on a tank and stay open while the pointer walks
    // from the board onto the popover itself.
    onTankHover(enter, leave) {
        if (this._hoverBound) return;
        this._hoverBound = true;
        let current = null;
        const report = (pointer) => {
            const hit = this.tankAt(pointer.x, pointer.y);
            const key = hit ? hit.side + ':' + hit.tank : null;
            const oldKey = current ? current.side + ':' + current.tank : null;
            if (key === oldKey) return;
            current = hit;
            if (hit) enter(hit.side, hit.tank); else leave();
        };
        this.input.on('pointermove', report);
        this.input.on('pointerout', () => { current = null; leave(); });
    }

    // Corner brackets on the board marking the tanks whose order is already locked:
    // amber for a move, red for a shot, grey for a hold. The cluster only shows one
    // tank at a time, so this is how the outstanding one stays visible.
    setOrderMarks(marks) {
        if (!this.markLayer) return;
        this.orderMarks = marks || [];
        this.markLayer.clear(true, true);
        const colors = { move: 0xf59e0b, fire: 0xef4444, hold: 0x9ca3af };
        (marks || []).forEach((m) => {
            const t = this.localTanks[m.side * 2 + m.tank];
            if (!t || !t.alive) return;
            const s = this.CELL_SIZE;
            const x = t.x * s, y = t.y * s;
            const len = s * 0.28, pad = s * 0.07;
            const g = this.add.graphics();
            g.lineStyle(Math.max(2, s * 0.07), colors[m.kind] || colors.move, 1);
            [[x + pad, y + pad, 1, 1], [x + s - pad, y + pad, -1, 1],
             [x + pad, y + s - pad, 1, -1], [x + s - pad, y + s - pad, -1, -1]].forEach(([cx, cy, sx, sy]) => {
                g.beginPath();
                g.moveTo(cx, cy + sy * len);
                g.lineTo(cx, cy);
                g.lineTo(cx + sx * len, cy);
                g.strokePath();
            });
            g.setDepth(40);
            this.markLayer.add(g);
        });
    }

    buildTextures() {
        // Procedural textures stay crisp at every board size and require no asset requests.
        const g = this.make.graphics({ x: 0, y: 0, add: false });
        const save = key => { g.generateTexture(key, 128, 128); g.clear(); };
        const block = (color, x, y, w, h, radius = 8) => {
            g.fillStyle(color); g.fillRoundedRect(x, y, w, h, radius);
        };
        block(0x153755, 5, 8, 118, 116);
        block(0x52b1df, 5, 5, 118, 115);
        block(0x237eb4, 9, 9, 110, 107);
        g.lineStyle(2, 0xb4e7ff, 0.75);
        g.lineBetween(15, 12, 113, 12);
        for (let row = 0; row < 4; row++) {
            g.lineStyle(3, 0xc4efff, 0.7);
            g.beginPath();
            for (let x = 18; x <= 110; x += 4) {
                const y = 28 + row * 23 + Math.sin(x / 14 + row) * 3;
                if (x === 18) g.moveTo(x, y); else g.lineTo(x, y);
            }
            g.strokePath();
        }
        save('water');
        block(0x26342f, 5, 9, 118, 115);
        block(0x794a3d, 5, 5, 118, 115);
        for (let row = 0; row < 3; row++) {
            for (let col = -1; col < 3; col++) {
                const x = 9 + col * 57 + (row % 2 ? 28 : 0);
                const left = Math.max(9, x), right = Math.min(119, x + 53);
                if (right <= left) continue;
                block(0xb87960, left, 9 + row * 36, right - left, 31, 3);
                block(0xd29b7d, left + 2, 11 + row * 36, Math.max(1, right - left - 4), 5, 2);
            }
        }
        save('brick');
        block(0x1b2b2c, 5, 9, 118, 115);
        block(0x62717b, 5, 5, 118, 115);
        block(0xa0adb5, 9, 9, 110, 103);
        block(0x84949e, 18, 18, 92, 84, 5);
        g.lineStyle(2, 0xcbd5dc, 0.6); g.lineBetween(23, 23, 105, 23);
        [[15,15],[113,15],[15,106],[113,106]].forEach(([x,y]) => {
            g.fillStyle(0x52616d); g.fillCircle(x,y,3);
        });
        save('steel');
        for (const [name, color, light, dark] of [
            ['blue', 0x4198f5, 0x87c4ff, 0x2563a9],
            ['red', 0xf16c7b, 0xffadb6, 0xa94051]
        ]) {
            block(0x122523, 25, 34, 78, 80, 12);
            for (const x of [25, 85]) {
                block(0x182a2f, x, 30, 18, 77, 6);
                for (let y = 36; y < 102; y += 9) block(0x53646a, x + 3, y, 12, 4, 1);
            }
            block(dark, 42, 35, 44, 71, 9);
            block(color, 45, 35, 38, 65, 8);
            block(light, 49, 39, 30, 5, 2);
            g.fillStyle(dark); g.fillCircle(64, 73, 21);
            block(dark, 57, 12, 14, 57, 3);
            block(color, 59, 12, 10, 55, 3);
            block(light, 60, 15, 3, 44, 1);
            block(0x263e49, 56, 12, 16, 8, 2);
            g.fillStyle(color); g.fillCircle(64, 69, 19);
            g.lineStyle(2, light, 0.7); g.strokeCircle(64, 69, 15);
            block(dark, 58, 62, 12, 13, 3);
            block(light, 60, 64, 8, 3, 1);
            save('tank_' + name);
            block(0x172c29, 14, 20, 100, 97, 13);
            block(0x687a7c, 14, 14, 100, 96, 13);
            block(0x9eafaf, 20, 19, 88, 79, 10);
            block(0x475d63, 31, 31, 66, 55, 6);
            block(dark, 37, 36, 54, 44, 5);
            block(color, 42, 41, 44, 34, 4);
            g.lineStyle(4, light, 0.9);
            g.strokeRect(51, 47, 26, 21);
            g.lineBetween(64, 48, 64, 68);
            g.lineBetween(51, 57, 77, 57);
            save('base_' + name);
        }
        g.destroy();
    }

    create() {
        this.buildTextures();
        this.CELL_SIZE = this.scale.width / FIELD_WIDTH;
        this.groundLayer = this.add.graphics().setDepth(-10);
        this.mapLayer = this.add.group();
        this.baseLayer = this.add.group();
        this.tankLayer = this.add.group();
        this.markLayer = this.add.group();
        this.drawGround();
        this.waitingText = this.add.text(this.scale.width / 2, this.scale.height / 2, 'Waiting for match…', {
            fontFamily: 'system-ui, sans-serif', fontSize: '15px', color: '#c4d6ce', backgroundColor: '#233b34', padding: { x: 16, y: 10 }
        }).setOrigin(0.5);
    }

    drawGround() {
        const g = this.groundLayer, c = this.CELL_SIZE;
        g.clear();
        g.fillStyle(0x233b34); g.fillRect(0, 0, this.scale.width, this.scale.height);
        for (let y = 0; y < FIELD_HEIGHT; y++) {
            for (let x = 0; x < FIELD_WIDTH; x++) {
                g.fillStyle((x + y) % 2 ? 0x304a40 : 0x2d463d);
                g.fillRoundedRect(x * c + c * 0.025, y * c + c * 0.025, c * 0.95, c * 0.95, c * 0.045);
            }
        }
    }

    resizeBoard() {
        this.clearAllBullets();
        this.CELL_SIZE = this.scale.width / FIELD_WIDTH;
        this.drawGround();
        if (this.mapData) this.refreshMapLayer();
        this.tankLayer.clear(true, true);
        this.baseLayer.clear(true, true);
        this.renderTanksAndBases();
        this.setOrderMarks(this.orderMarks || []);
        if (this.waitingText) this.waitingText.setPosition(this.scale.width / 2, this.scale.height / 2);
    }

    updateFromState(state) {
        if (!state) return;

        // Init map and local state (every new game resets all state)
        if (state.brick && state.steel && state.water) {
            if (this.waitingText) { this.waitingText.destroy(); this.waitingText = null; }
            // New game: drop the previous game's in-flight bullets at once so none linger
            this.clearAllBullets();
            this.mapDrawn = false; // allow the map to be redrawn
            this.drawMap(state.brick, state.water, state.steel);
            this.mapDrawn = true;
            // Re-initialize local tanks and bases
            this.localTanks = INIT_TANKS.map(t => ({ ...t, dir: t.side === 0 ? 2 : 0 }));
            this.localBases = INIT_BASES.map(b => ({ ...b }));
            this.lastActions = [[-1, -1], [-1, -1]];
            this.turn = 1;
            this.tankLayer.clear(true, true);
            this.baseLayer.clear(true, true);
            this.setOrderMarks([]);
            this.renderTanksAndBases();
            return;
        }

        // Each turn only delivers both sides' actions
        if (state['0'] && state['1']) {
            this.lastActions = [state['0'].slice(0, 2), state['1'].slice(0, 2)];
            this.applyActions(state['0'], state['1']);
            this.turn += 1;
            this.tankLayer.clear(true, true);
            this.baseLayer.clear(true, true);
            this.renderTanksAndBases();
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
                tankSprite.setDisplaySize(this.CELL_SIZE * 0.94, this.CELL_SIZE * 0.94);
                tankSprite.setAngle((tank.dir || 0) * 90);
                this.tankLayer.add(tankSprite);
            }
        });
        // Render bases
        this.localBases.forEach(base => {
            if (base.alive) {
                const x = (base.x + 0.5) * this.CELL_SIZE;
                const y = (base.y + 0.5) * this.CELL_SIZE;
                const baseSprite = this.add.sprite(x, y, base.side === 0 ? 'base_blue' : 'base_red');
                baseSprite.setDisplaySize(this.CELL_SIZE * 0.92, this.CELL_SIZE * 0.92);
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
        // Resolve all moves first
        for (let i = 0; i < 4; i++) {
            const tank = tanks[i];
            if (!tank.alive) continue;
            const act = allActions[i];
            if (act >= 0 && act <= 7) tank.dir = act % 4;
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
        this.mapData = Array.from({length: FIELD_HEIGHT}, () => Array(FIELD_WIDTH).fill(0));
        for (const [binary, code] of [[waterBinary, 1], [brickBinary, 2], [steelBinary, 3]]) {
            for (let y = 0; y < FIELD_HEIGHT; y++) {
                for (let x = 0; x < FIELD_WIDTH; x++) {
                    if (binary[Math.floor(y / 3)] & (1 << ((y % 3) * FIELD_WIDTH + x))) this.mapData[y][x] = code;
                }
            }
        }
        this.refreshMapLayer();
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
        //  - A small projectile carries a short tapered trail behind it
        //  - All bullets in one turn use the same fixed duration; once queued they advance on the
        //    same Phaser timeline, so every bullet reaches its target at the very same instant
        //  - Speed = distance / duration: an open path means a long distance, so the bullet covers
        //    more cells per tick and looks "fast"; a short path or one blocked by brick looks "slow"
        const startX = (fromX + 0.5) * this.CELL_SIZE;
        const startY = (fromY + 0.5) * this.CELL_SIZE;
        const endX = (toX + 0.5) * this.CELL_SIZE;
        const endY = (toY + 0.5) * this.CELL_SIZE;

        const cell = this.CELL_SIZE;
        const bulletSize = cell * 0.15;
        const trailLen = cell * 0.8; // tail is a fixed 0.8 cells, never stretched by distance -> no leftover line

        // The bright projectile core
        const bullet = this.add.circle(startX, startY, bulletSize / 2, 0xffe6a3);
        bullet.setDepth(20);

        // The tail graphics (yellow, semi-transparent)
        const trail = this.add.graphics();
        trail.setDepth(19);

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
                trail.clear();
                const length = Math.min(trailLen, Math.hypot(bullet.x - startX, bullet.y - startY));
                for (let i = 0; i < 6; i++) {
                    const a = length * (1 - i / 6), b = length * (1 - (i + 1) / 6);
                    trail.lineStyle(bulletSize * (0.2 + i * 0.12), 0xfbbf24, 0.1 + i * 0.08);
                    trail.lineBetween(bullet.x - ux * a, bullet.y - uy * a, bullet.x - ux * b, bullet.y - uy * b);
                }
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
