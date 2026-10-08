// This script is loaded by tank.html after the Phaser game object is created.
// The 'mainScene' variable is globally available and points to the main Phaser scene.

const FIELD_WIDTH = 9, FIELD_HEIGHT = 9;
const INIT_TANKS = [
    { x: 2, y: 0, side: 0, alive: true }, // 蓝0
    { x: 6, y: 0, side: 0, alive: true }, // 蓝1
    { x: 6, y: 8, side: 1, alive: true }, // 红0
    { x: 2, y: 8, side: 1, alive: true }, // 红1
];
const INIT_BASES = [
    { x: 4, y: 0, side: 0, alive: true }, // 蓝基地
    { x: 4, y: 8, side: 1, alive: true }, // 红基地
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

        // 飞行中的子弹（用于切回合 / 重置时强制清理，避免残留）
        this.activeBullets = [];
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

        // 初始化地图和本地状态（每次新游戏都要重置所有状态）
        if (state.brick && state.steel && state.water) {
            // 新游戏：立刻清掉上一局的飞行中子弹，避免残留
            this.clearAllBullets();
            this.mapDrawn = false; // 允许重新绘制地图
            this.drawMap(state.brick, state.water, state.steel);
            this.mapDrawn = true;
            // 重新初始化本地坦克和基地
            this.localTanks = INIT_TANKS.map(t => ({ ...t }));
            this.localBases = INIT_BASES.map(b => ({ ...b }));
            this.turn = 1;
            this.tankLayer.clear(true, true);
            this.baseLayer.clear(true, true);
            this.renderTanksAndBases();
            // 更新回合数显示
            const turnCounter = document.getElementById('turnCounter');
            if (turnCounter) {
                turnCounter.textContent = `Turn: ${this.turn}`;
            }
            return;
        }

        // 每回合只收到双方行动
        if (state['0'] && state['1']) {
            this.applyActions(state['0'], state['1']);
            this.turn += 1;
            this.tankLayer.clear(true, true);
            this.baseLayer.clear(true, true);
            this.renderTanksAndBases();
            // 更新回合数显示
            const turnCounter = document.getElementById('turnCounter');
            if (turnCounter) {
                turnCounter.textContent = `Turn: ${this.turn}`;
            }
            return;
        }
    }

    renderTanksAndBases() {
        // 渲染坦克
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
        // 渲染基地
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
        // 切到下一回合：把上一回合没飞完的子弹立刻飞到终点并销毁，
        // 这样本回合的子弹能在干净的画布上起飞，不会与旧子弹视觉叠加。
        this.forceFinishAllBullets();

        // 坦克行动顺序：蓝0、蓝1、红0、红1
        const dx = [0, 1, 0, -1], dy = [-1, 0, 1, 0];
        const tanks = this.localTanks;
        const bases = this.localBases;
        const allActions = [actions0[0], actions0[1], actions1[0], actions1[1]];

        // 1. 处理移动
        // 记录原位置
        const origPos = tanks.map(t => ({ x: t.x, y: t.y, alive: t.alive }));

        // 先处理所有移动
        for (let i = 0; i < 4; i++) {
            const tank = tanks[i];
            if (!tank.alive) continue;
            const act = allActions[i];
            if (act >= 0 && act <= 3) { // 移动
                const nx = tank.x + dx[act], ny = tank.y + dy[act];
                // 边界检测
                if (nx < 0 || nx >= FIELD_WIDTH || ny < 0 || ny >= FIELD_HEIGHT) {
                    tank.alive = false; // 越界死亡
                    continue;
                }
                // 不能移动到水、钢、砖
                if (this.mapData[ny][nx] && this.mapData[ny][nx] !== 0) {
                    tank.alive = false; // 撞障碍死亡
                    continue;
                }
                tank.x = nx;
                tank.y = ny;
            }
            // Stay 或射击不动
        }

        // 3. 处理射击（严格模拟 Tank2 规则）
        let bulletHits = []; // {x, y, type, shooter, dir, target?}
        for (let i = 0; i < 4; i++) {
            const tank = tanks[i];
            if (!tank.alive) continue;
            const act = allActions[i];
            if (act >= 4 && act <= 7) { // 射击
                const dir = act % 4;
                let x = tank.x, y = tank.y;
                while (true) {
                    x += dx[dir];
                    y += dy[dir];
                    if (x < 0 || x >= FIELD_WIDTH || y < 0 || y >= FIELD_HEIGHT) {
                        bulletHits.push({x, y, type: 'out', shooter: i, dir});
                        break;
                    }
                    if (this.mapData[y][x] === 3) { // 钢
                        bulletHits.push({x, y, type: 'steel', shooter: i, dir});
                        break;
                    }
                    if (this.mapData[y][x] === 2) { // 砖
                        bulletHits.push({x, y, type: 'brick', shooter: i, dir});
                        break;
                    }
                    // 检查是否击中坦克
                    let hitTank = false;
                    for (let j = 0; j < 4; j++) {
                        if (tanks[j].alive && tanks[j].x === x && tanks[j].y === y) {
                            // 新增：对射判断
                            const theirAction = allActions[j];
                            const theirDir = theirAction % 4;
                            // 如果对方也反向射击，则子弹抵消
                            if (theirAction >= 4 && theirAction <= 7 && (dir + 2) % 4 === theirDir) {
                                // 记录一个抵消事件，用于动画
                                bulletHits.push({x, y, type: 'cancel', shooter: i, dir});
                            } else {
                                // 否则正常命中
                                bulletHits.push({x, y, type: 'tank', shooter: i, dir, target: j});
                            }
                            hitTank = true;
                            break;
                        }
                    }
                    if (hitTank) break;
                    // 击中基地
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

        // 统计所有被击中的砖块（只摧毁一次）
        let bricksToDestroy = new Set();
        bulletHits.forEach(hit => {
            if (hit.type === 'brick') bricksToDestroy.add(`${hit.x},${hit.y}`);
        });

        // 播放所有子弹动画（命中砖块的都停在砖块前，不会穿透）
        bulletHits.forEach(hit => {
            // 计算动画终点
            let endX = hit.x, endY = hit.y;
            if (hit.type === 'brick' || hit.type === 'steel') {
                // 子弹停在砖块/钢块前一格
                endX -= dx[hit.dir];
                endY -= dy[hit.dir];
            }
            // 其余类型（坦克/基地/越界）停在命中点
            this.fireBullet(tanks[hit.shooter].x, tanks[hit.shooter].y, hit.dir, endX, endY);
        });

        // 统一处理命中效果
        bricksToDestroy.forEach(key => {
            const [x, y] = key.split(',').map(Number);
            this.mapData[y][x] = 0;
        });

        // 处理坦克和基地被击毁
        bulletHits.forEach(hit => {
            // 只有类型为 'tank' 的命中才会摧毁坦克
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
                            this.mapData[y][x] = code; // 1=水,2=砖,3=钢
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
        // dir: 0=上, 1=右, 2=下, 3=左
        //
        // 设计要点：
        //  - 移动的是一个小方块（不是拉长的线段），后方跟一段固定长度的尾巴
        //  - 同一回合所有子弹使用同一个固定 duration，add 到 tween 队列后
        //    Phaser 会在同一时间轴上推进，因此所有子弹在同一刻同时到达终点
        //  - 速度 = 距离 / duration：路径空 → 距离远 → 单位时间移动距离大 → 视觉上"快"；
        //    路径短 / 被砖块挡 → 距离近 → 视觉上"慢"
        const startX = (fromX + 0.5) * this.CELL_SIZE;
        const startY = (fromY + 0.5) * this.CELL_SIZE;
        const endX = (toX + 0.5) * this.CELL_SIZE;
        const endY = (toY + 0.5) * this.CELL_SIZE;

        const cell = this.CELL_SIZE;
        const bulletSize = cell * 0.28;
        const trailLen = cell * 0.8; // 尾巴固定 0.8 格，不随距离拉长 → 没有"残留线"

        // 子弹方块（黄）
        const bullet = this.add.rectangle(startX, startY, bulletSize, bulletSize, 0xffeb3b);
        bullet.setDepth(20);

        // 尾巴 graphics（黄、半透明）
        const trail = this.add.graphics();
        trail.setDepth(19);
        trail.lineStyle(bulletSize * 0.8, 0xffeb3b, 0.55);

        // 方向单位向量（用于尾巴定位）
        const ddx = endX - startX, ddy = endY - startY;
        const dist = Math.hypot(ddx, ddy) || 1;
        const ux = ddx / dist, uy = ddy / dist;

        const BULLET_DURATION_MS = 200; // 同一回合所有子弹同步到达

        const entry = { bullet, trail, tween: null };
        this.activeBullets.push(entry);

        entry.tween = this.tweens.add({
            targets: bullet,
            x: endX,
            y: endY,
            duration: BULLET_DURATION_MS,
            ease: 'Linear',
            onUpdate: () => {
                // 尾巴：从子弹位置往反方向延伸 trailLen
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

    forceFinishAllBullets() {
        // 把所有飞行中的子弹立刻飞到终点并销毁（不等待 duration 走完）。
        // 用于：切到下一回合、replay 跳步等场景，避免视觉叠加。
        if (!this.activeBullets || this.activeBullets.length === 0) return;
        // 拷贝，因为 tween.complete() 会触发 onComplete 修改 activeBullets
        const list = this.activeBullets.slice();
        for (const entry of list) {
            if (entry.tween) entry.tween.complete();
        }
        // onComplete 已逐个 splice，但保险起见
        this.activeBullets = [];
    }

    clearAllBullets() {
        // 立即销毁所有飞行中的子弹，不等 tween 完成（用于新游戏 / 场景重置）。
        if (!this.activeBullets) return;
        for (const entry of this.activeBullets) {
            if (entry.tween) entry.tween.remove();
            if (entry.bullet && entry.bullet.scene) entry.bullet.destroy();
            if (entry.trail && entry.trail.scene) entry.trail.destroy();
        }
        this.activeBullets = [];
    }
}