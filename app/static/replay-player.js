/**
 * ReplayController — shared replay player UI used by all game pages
 * (Gomoku, Snake, Tank Battle).
 *
 * Owns what the three pages used to duplicate:
 *   - current frame index (0..maxIndex)
 *   - play/pause timer with speed control (0.5x / 1x / 2x / 4x)
 *   - transport buttons, slider, turn counter, status text
 *
 * The game page only supplies onRender(index), which must rebuild the
 * board state up to `index` (usually by replaying from frame 0).
 *
 * Expected DOM ids (all optional — missing elements are ignored, so this
 * also works on pages without replay UI):
 *   #btnFirst #btnPrev #btnPlayPause #btnNext #btnLast
 *   #replaySlider #replayStatus #replaySpeed
 *   + counter element: options.counterId (default: 'turnCounter2')
 */
class ReplayController {
    /**
     * @param {Object}   options
     * @param {Function} options.onRender          (index) => void, required
     * @param {number}   [options.baseIntervalMs]  interval at 1x speed, default 800
     * @param {string}    [options.counterId]       turn counter element id
     * @param {Function} [options.onIntervalChange] (intervalMs) => void, fired when
     *                                              the effective interval changes
     *                                              (speed switch / play start)
     */
    constructor({ onRender, baseIntervalMs = 800, counterId = 'turnCounter2', onIntervalChange = null }) {
        if (typeof onRender !== 'function') {
            throw new Error('ReplayController: onRender is required');
        }
        this.onRender = onRender;
        this.baseIntervalMs = baseIntervalMs;
        this.counterId = counterId;
        this.onIntervalChange = onIntervalChange;

        this.maxIndex = 0;
        this.index = 0;
        this.speed = 1;
        this.playing = false;
        this.timer = null;
        this.attached = false;
    }

    /** Bind DOM events. Call once after the DOM is ready. Idempotent. */
    attach() {
        if (this.attached) return;
        this.attached = true;

        const on = (id, evt, fn) => {
            const el = document.getElementById(id);
            if (el) el.addEventListener(evt, fn);
        };

        on('btnFirst', 'click', () => this.goto(0));
        on('btnPrev', 'click', () => this.step(-1));
        on('btnPlayPause', 'click', () => this.toggle());
        on('btnNext', 'click', () => this.step(1));
        on('btnLast', 'click', () => this.goto(this.maxIndex));
        on('replaySlider', 'input', (e) => this.goto(parseInt(e.target.value, 10)));
        on('replaySpeed', 'change', (e) => this.setSpeed(parseFloat(e.target.value) || 1));
    }

    /** Effective per-frame interval, derived from base speed and multiplier. */
    get intervalMs() {
        return Math.max(150, Math.round(this.baseIntervalMs / this.speed));
    }

    /**
     * Load a replay whose last frame index is `maxIndex`, render frame 0.
     *   - Gomoku: maxIndex = moves.length (states: empty board + n moves)
     *   - Snake/Tank: maxIndex = displays.length - 1 (displays[0] is the initial state)
     */
    load(maxIndex) {
        this.pause();
        this.maxIndex = Math.max(0, maxIndex || 0);
        const slider = document.getElementById('replaySlider');
        if (slider) slider.max = this.maxIndex;
        this.render(0);
    }

    setStatus(text) {
        const el = document.getElementById('replayStatus');
        if (el) el.textContent = text;
    }

    /** Render frame `index` (clamped) and sync the UI. */
    render(index) {
        this.index = Math.max(0, Math.min(this.maxIndex, index));
        this.onRender(this.index);
        this._syncUI();
    }

    play() {
        if (this.playing || this.maxIndex <= 0) return;
        if (this.index >= this.maxIndex) this.render(0); // restart from beginning
        this.playing = true;
        this._setPlayIcon(true);
        if (this.onIntervalChange) this.onIntervalChange(this.intervalMs);
        this.timer = setInterval(() => {
            if (this.index >= this.maxIndex) {
                this.pause();
                return;
            }
            this.render(this.index + 1);
        }, this.intervalMs);
    }

    pause() {
        this.playing = false;
        this._setPlayIcon(false);
        if (this.timer) {
            clearInterval(this.timer);
            this.timer = null;
        }
    }

    toggle() {
        this.playing ? this.pause() : this.play();
    }

    step(delta) {
        this.pause();
        this.render(this.index + delta);
    }

    goto(index) {
        this.pause();
        this.render(index);
    }

    setSpeed(speed) {
        this.speed = speed > 0 ? speed : 1;
        if (this.onIntervalChange) this.onIntervalChange(this.intervalMs);
        if (this.playing) { // restart timer with the new interval
            this.pause();
            this.play();
        }
    }

    _setPlayIcon(playing) {
        const btn = document.getElementById('btnPlayPause');
        if (btn) btn.innerHTML = playing ? '&#9646;&#9646;' : '&#9654;';
    }

    _syncUI() {
        const counter = document.getElementById(this.counterId);
        if (counter) counter.textContent = this.index + ' / ' + this.maxIndex;

        const slider = document.getElementById('replaySlider');
        if (slider) slider.value = this.index;

        const disable = (id, disabled) => {
            const btn = document.getElementById(id);
            if (btn) btn.disabled = disabled;
        };
        disable('btnFirst', this.index <= 0);
        disable('btnPrev', this.index <= 0);
        disable('btnNext', this.index >= this.maxIndex);
        disable('btnLast', this.index >= this.maxIndex);
    }
}
