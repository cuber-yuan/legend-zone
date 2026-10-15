// Introduction pages use the existing game renderer/controller, without controls.
(() => {
    const element = document.getElementById('gameDemoData');
    if (!element) return;
    const demo = JSON.parse(element.textContent);
    let started = false;
    const start = () => {
        if (typeof phaserGame === 'undefined' || !phaserGame?.scene.scenes.some(scene => scene.sys.isActive())) {
            requestAnimationFrame(start);
            return;
        }
        replayController.demo = true;
        startReplay(demo.frames, demo.winner);
        started = true;
        if (document.hidden) replayController.pause();
    };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once: true });
    else start();
    // Pause background work; resume the same cached replay when the tab returns.
    document.addEventListener('visibilitychange', () => {
        if (!started) return;
        if (document.hidden) replayController.pause();
        else replayController.play();
    });
    window.addEventListener('pagehide', () => replayController.pause());
    window.addEventListener('pageshow', () => {
        if (started && !document.hidden) replayController.play();
    });
})();
