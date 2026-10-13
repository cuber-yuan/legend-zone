// Drawing shared by live games and replays; all coordinates stay in board-cell space.
window.BoardGameRenderer = (() => {
    function stone(g, cx, cy, radius, isBlack) {
        g.fillStyle(0x684a2e, 0.22);
        g.fillEllipse(cx + radius * 0.08, cy + radius * 0.18, radius * 2.06, radius * 1.94);
        const from = isBlack ? [21, 29, 41] : [214, 223, 231];
        const to = isBlack ? [87, 101, 119] : [255, 255, 255];
        for (let i = 0; i <= 20; i++) {
            const t = i / 20;
            const rgb = from.map((v, j) => Math.round(v + (to[j] - v) * t));
            g.fillStyle((rgb[0] << 16) | (rgb[1] << 8) | rgb[2]);
            g.fillCircle(cx - radius * 0.24 * t, cy - radius * 0.28 * t, radius * (1 - t * 0.75));
        }
        g.lineStyle(Math.max(0.7, radius * 0.04), isBlack ? 0x152033 : 0xb5bec5, 0.7);
        g.strokeCircle(cx, cy, radius);
    }

    function gomoku(g, board, lastMove, size, width) {
        const cell = width / size;
        g.fillStyle(0xefd4a7); g.fillRect(0, 0, width, width);
        // Restrained wood grain: deterministic so replay seeks do not change the surface.
        g.lineStyle(1, 0x9b6c38, 0.055);
        for (let row = 0; row < 70; row++) {
            const y = width * row / 70;
            g.beginPath();
            for (let x = 0; x <= width; x += width / 24) {
                const py = y + Math.sin(x / width * 8 + row) * cell * 0.04;
                if (x === 0) g.moveTo(x, py); else g.lineTo(x, py);
            }
            g.strokePath();
        }
        g.lineStyle(Math.max(0.8, cell * 0.023), 0x785d3e, 0.5);
        for (let i = 0; i < size; i++) {
            const pos = (i + 0.5) * cell;
            g.lineBetween(cell / 2, pos, width - cell / 2, pos);
            g.lineBetween(pos, cell / 2, pos, width - cell / 2);
        }
        g.lineStyle(Math.max(1, cell * 0.03), 0x785d3e, 0.65);
        g.strokeRect(cell / 2, cell / 2, width - cell, width - cell);
        g.fillStyle(0x785d3e, 0.85);
        for (const [x, y] of [[3,3],[3,11],[7,7],[11,3],[11,11]]) g.fillCircle((x + 0.5) * cell, (y + 0.5) * cell, cell * 0.075);
        for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
            if (board[y][x]) stone(g, (x + 0.5) * cell, (y + 0.5) * cell, cell * 0.42, board[y][x] === 1);
        }
        if (lastMove) {
            const x = (lastMove.x + 0.5) * cell, y = (lastMove.y + 0.5) * cell;
            g.fillStyle(0xd99c35); g.fillCircle(x, y, cell * 0.085);
            g.lineStyle(Math.max(0.7, cell * 0.025), 0x805a22, 0.8); g.strokeCircle(x, y, cell * 0.085);
        }
    }

    function roundedLine(g, x1, y1, x2, y2, width, color) {
        g.lineStyle(width, color); g.lineBetween(x1, y1, x2, y2);
        g.fillStyle(color); g.fillCircle(x1, y1, width / 2); g.fillCircle(x2, y2, width / 2);
    }

    function tictactoe(g, board, lastMove, size, width) {
        const cell = width / size;
        g.fillStyle(0xe8eef5); g.fillRect(0, 0, width, width);
        for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
            const left = (x + 0.055) * cell, top = (y + 0.055) * cell;
            const tileSize = cell * 0.89, radius = cell * 0.1;
            const last = lastMove && lastMove.x === x && lastMove.y === y;
            g.fillStyle(0xcdd8e5); g.fillRoundedRect(left, top + cell * 0.025, tileSize, tileSize, radius);
            g.fillStyle(last ? 0xeff6ff : 0xfafcff); g.fillRoundedRect(left, top, tileSize, tileSize, radius);
            g.lineStyle(Math.max(1, cell * 0.01), last ? 0x93c5fd : 0xffffff, 0.9);
            g.strokeRoundedRect(left, top, tileSize, tileSize, radius);
            const cx = (x + 0.5) * cell, cy = (y + 0.5) * cell;
            const lineWidth = cell * 0.065, arm = cell * 0.21;
            if (board[y][x] === 1) {
                roundedLine(g, cx - arm, cy - arm + cell * 0.025, cx + arm, cy + arm + cell * 0.025, lineWidth, 0x2563a9);
                roundedLine(g, cx + arm, cy - arm + cell * 0.025, cx - arm, cy + arm + cell * 0.025, lineWidth, 0x2563a9);
                roundedLine(g, cx - arm, cy - arm, cx + arm, cy + arm, lineWidth, 0x4198f5);
                roundedLine(g, cx + arm, cy - arm, cx - arm, cy + arm, lineWidth, 0x4198f5);
            } else if (board[y][x] === 2) {
                g.lineStyle(lineWidth, 0xc45767); g.strokeCircle(cx, cy + cell * 0.025, cell * 0.245);
                g.lineStyle(lineWidth, 0xf16c7b); g.strokeCircle(cx, cy, cell * 0.245);
            }
        }
    }

    return { draw({ graphics, variant, board, lastMove, size, width }) {
        graphics.clear();
        (variant === 'gomoku' ? gomoku : tictactoe)(graphics, board, lastMove, size, width);
    }};
})();
