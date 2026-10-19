// Continuous rating colors shared by Bot labels. Each label has one solid tone.
window.BotRating = (() => {
    const anchors = [
        [1300, 0.025, 250], // gray
        [1500, 0.160, 150], // green
        [1700, 0.170, 255], // blue
        [1900, 0.170, 305], // purple
        [2100, 0.170, 60],  // orange
        [2300, 0.180, 25]   // red
    ];
    function palette(rating) {
        if (typeof rating !== 'number' || !Number.isFinite(rating)) {
            return {background: '#f1f5f9', hover: '#e2e8f0', foreground: '#475569', border: '#e2e8f0'};
        }
        const value = Math.max(anchors[0][0], Math.min(anchors.at(-1)[0], rating));
        const right = anchors.findIndex(anchor => anchor[0] >= value);
        const lower = anchors[Math.max(0, right - 1)], upper = anchors[right];
        const t = upper[0] === lower[0] ? 0 : (value - lower[0]) / (upper[0] - lower[0]);
        const chroma = lower[1] + (upper[1] - lower[1]) * t;
        const hueDelta = ((upper[2] - lower[2] + 540) % 360) - 180;
        const hue = (lower[2] + hueDelta * t + 360) % 360;
        const color = (lightness, strength) => `oklch(${lightness} ${(chroma * strength).toFixed(5)} ${hue.toFixed(3)})`;
        return {background: color(0.96, 0.18), hover: color(0.925, 0.28),
                foreground: color(0.36, 0.65), border: color(0.87, 0.35)};
    }
    function apply(root) {
        root.querySelectorAll('.lm-bot-chip').forEach(label => {
            const raw = label.dataset.botRating;
            const rating = raw === '' || raw === undefined ? null : Number(raw);
            const colors = palette(rating);
            // Old browsers retain the neutral CSS fallback.
            if (CSS.supports('color', colors.background)) {
                for (const [key, value] of Object.entries(colors)) label.style.setProperty('--bot-' + key, value);
            }
        });
    }
    return {palette, apply};
})();
