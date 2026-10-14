/* Load the public match trace on first expansion; replay from local memory. */
(() => {
    class ReplayDebugPanel {
        constructor(element) {
            this.root = element;
            this.replay = element.closest('#replayControls');
            this.actor = 'player_1';
            this.manifest = null;
            this.cache = new Map();
            this.failedTurn = null;
            this.frame = Number(this.replay.dataset.frame || 0);
            this.generation = 0;
            this.abort = null;
            this.pending = null;
            this.el('[data-debug-toggle]').addEventListener('click', () => {
                const enabled = !this.enabled;
                this.el('[data-debug-toggle]').setAttribute('aria-expanded', String(enabled));
                this.el('[data-debug-panel]').hidden = !enabled;
                if (enabled) this.refresh();
                else {
                    this.generation++;
                    this.abort?.abort();
                    this.pending = null;
                    if (this.manifest?.status === 'recording') {
                        this.manifest = null;
                        this.cache.clear();
                    }
                    this.el('[data-debug-panel]').removeAttribute('aria-busy');
                    this.el('[data-debug-failure]').hidden = true;
                }
            });
            this.replay.addEventListener('replay:frame', event => {
                // Canvas resize can redraw the same frame. Keep the selected failure visible.
                if (event.detail.index === this.frame) return;
                this.frame = event.detail.index;
                this.failedTurn = null;
                if (this.enabled) this.refresh();
            });
            this.el('[data-debug-failure]').addEventListener('click', () => {
                if (this.manifest?.failure_turn == null) return;
                const index = Math.min(this.manifest.frame_count, Number(this.replay.dataset.maxFrame || 0));
                this.replay.dispatchEvent(new CustomEvent('replay:seek', { detail: { index } }));
                this.failedTurn = this.manifest.failure_turn;
                this.selectFailureActor = true;
                this.refresh();
            });
            element.querySelectorAll('[data-debug-actor]').forEach(tab => tab.addEventListener('click', () => {
                this.actor = tab.dataset.debugActor;
                this.selectFailureActor = false;
                this.refresh();
            }));
            this.el('.rd-tabs').addEventListener('keydown', e => {
                if (!['ArrowLeft', 'ArrowRight'].includes(e.key)) return;
                e.preventDefault();
                e.stopPropagation();
                const tabs = [...element.querySelectorAll('[data-debug-actor]')];
                const selected = tabs.findIndex(tab => tab.dataset.debugActor === this.actor);
                const next = tabs[(selected + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
                next.click(); next.focus();
            });
        }

        el(selector) { return this.root.querySelector(selector); }
        get enabled() { return this.el('[data-debug-toggle]').getAttribute('aria-expanded') === 'true'; }

        async request(url, signal) {
            const response = await fetch(url, { signal, cache: 'no-store' });
            if (!response.ok) throw new Error('Unable to load debug records.');
            return response.json();
        }

        async loadSnapshot() {
            if (!this.pending) {
                const controller = new AbortController();
                this.abort = controller;
                const url = new URL(this.root.dataset.url, window.location.href);
                url.searchParams.set('all', '1');
                const pending = this.request(url, controller.signal).then(snapshot => {
                    if (controller.signal.aborted) return;
                    const cache = new Map();
                    for (const event of snapshot.events || []) {
                        if (!cache.has(event.turn)) cache.set(event.turn, []);
                        cache.get(event.turn).push(event);
                    }
                    this.cache = cache;
                    this.manifest = snapshot;
                }).finally(() => {
                    if (this.pending === pending) this.pending = null;
                });
                this.pending = pending;
            }
            return this.pending;
        }

        async refresh() {
            const generation = ++this.generation;
            const turn = this.failedTurn ?? Number(this.replay.dataset.frame || 0);
            // Keep a coherent snapshot visible until the next round is ready.
            // Even cached reads must not briefly collapse the log or flash a loading label.
            this.el('[data-debug-panel]').setAttribute('aria-busy', 'true');
            if (this.el('[data-debug-content]').hidden) {
                this.el('[data-debug-notice]').textContent = 'Loading debug records…';
            }
            try {
                // Frame/tab changes share the initial request rather than restarting it.
                if (!this.manifest) await this.loadSnapshot();
                if (generation !== this.generation || !this.enabled) return;
                const manifest = this.manifest;
                if (!manifest.available) {
                    this.el('[data-debug-content]').hidden = true;
                    this.el('[data-debug-notice]').textContent = 'No debug records were captured for this match.';
                    this.el('[data-debug-failure]').hidden = true;
                    return;
                }
                const records = this.cache.get(turn) || [];
                if (this.selectFailureActor) {
                    const visibleActors = [...this.root.querySelectorAll('[data-debug-actor]')].map(tab => tab.dataset.debugActor);
                    this.actor = records.find(record => record.status !== 'success' && visibleActors.includes(record.actor))?.actor || this.actor;
                    this.selectFailureActor = false;
                }
                this.render(turn, records);
            } catch (error) {
                if (generation !== this.generation || error.name === 'AbortError') return;
                this.manifest = null;
                this.el('[data-debug-content]').hidden = true;
                this.el('[data-debug-notice]').textContent = 'Could not load debug records. Toggle Debug mode off and on to retry.';
                this.el('[data-debug-failure]').hidden = true;
            } finally {
                if (generation === this.generation) this.el('[data-debug-panel]').removeAttribute('aria-busy');
            }
        }

        render(turn, records) {
            const manifest = this.manifest;
            const notes = [];
            if (manifest.truncated) notes.push('Some data was truncated at the recording size limit.');
            if (manifest.incomplete) notes.push('Recording is incomplete. Some events may be missing.');
            if (manifest.error) notes.push(manifest.error);
            this.el('[data-debug-notice]').textContent = notes.join(' ');
            this.el('[data-debug-content]').hidden = false;
            const failure = this.el('[data-debug-failure]');
            failure.hidden = manifest.failure_turn == null;
            failure.textContent = manifest.failure_turn === 0 ? 'Setup failed' : `Round ${manifest.failure_turn} · failed`;
            failure.setAttribute('aria-pressed', String(this.failedTurn != null));
            this.el('[data-debug-title]').textContent = this.failedTurn != null
                ? turn === 0 ? 'Setup failed' : `Round ${turn} · failed`
                : turn === 0 ? 'Initial state' : `Round ${turn}`;
            this.el('[data-debug-frame]').textContent = this.failedTurn != null
                ? `Board remains at frame ${manifest.frame_count}` : 'Synced with replay';
            const names = [...document.querySelectorAll('.match-player-name')].map(node => node.textContent);
            this.root.querySelectorAll('[data-debug-actor]').forEach(tab => {
                const actor = tab.dataset.debugActor;
                tab.textContent = actor === 'judge' ? 'Judge' : names[Number(actor.slice(-1)) - 1] || `Player ${actor.slice(-1)}`;
                tab.title = tab.textContent;
                tab.setAttribute('aria-selected', String(actor === this.actor));
                tab.tabIndex = actor === this.actor ? 0 : -1;
                if (actor === this.actor) this.el('[role="tabpanel"]').setAttribute('aria-labelledby', tab.id);
            });
            const event = records.filter(record => record.actor === this.actor).at(-1);
            const empty = this.el('[data-debug-empty]');
            empty.hidden = !!event || !manifest.incomplete;
            this.el('[data-debug-fields]').hidden = false;
            this.el('[data-debug-stderr-section]').hidden = !event || ['python_judge', 'human'].includes(event.kind);
            this.el('[data-debug-diagnostic]').hidden = !event?.diagnostic;
            this.el('[data-debug-diagnostic]').textContent = event?.diagnostic || '';
            const status = this.el('[data-debug-status]');
            if (!event) {
                status.textContent = manifest.incomplete ? 'Unavailable' : 'Not active';
                status.classList.remove('rd-error');
                status.classList.add('rd-inactive');
                empty.textContent = manifest.incomplete ? 'No event is available for this player.' : '';
                this.el('[data-debug-duration]').textContent = '— ms';
                this.el('[data-debug-exit]').textContent = 'Exit code —';
                this.el('[data-debug-input-label]').textContent = 'Input · stdin';
                this.el('[data-debug-output-label]').textContent = 'Output · stdout (raw)';
                this.el('[data-debug-input]').textContent = '';
                this.el('[data-debug-output]').textContent = '';
                this.el('[data-debug-stderr]').textContent = '';
                this.el('[data-debug-stderr-state]').textContent = '';
                this.root.querySelectorAll('[data-debug-cut]').forEach(node => { node.hidden = true; });
                return;
            }
            const labels = { success: 'Success', timeout: 'Timed out', protocol_error: 'Invalid output',
                runtime_error: 'Runtime error', compile_error: 'Compilation failed', execution_error: 'Execution error', invalid_move: 'Illegal move' };
            status.textContent = labels[event.status] || event.status;
            status.classList.remove('rd-inactive');
            status.classList.toggle('rd-error', event.status !== 'success');
            this.el('[data-debug-duration]').textContent = event.duration_ms == null ? '' : `${Number(event.duration_ms).toFixed(1)} ms`;
            this.el('[data-debug-exit]').textContent = event.kind === 'python_judge' ? 'Python judge' : event.kind === 'human'
                ? 'Human action' : event.exit_code != null ? `Exit code ${event.exit_code}` : event.status === 'timeout' ? 'Terminated' : '';
            this.el('[data-debug-input-label]').textContent = event.kind === 'python_judge' ? 'Input · decision context' : event.kind === 'human' ? 'Input · game state' : 'Input · stdin';
            this.el('[data-debug-output-label]').textContent = event.kind === 'python_judge' ? 'Output · decision result' : event.kind === 'human' ? 'Output · action' : 'Output · stdout (raw)';
            this.el('[data-debug-input]').textContent = this.format(event.input, event.kind === 'python_judge');
            this.el('[data-debug-output]').textContent = this.format(event.stdout, event.kind === 'python_judge');
            this.el('[data-debug-stderr]').textContent = event.stderr || '(empty)';
            this.el('[data-debug-stderr-state]').textContent = event.stderr ? '· captured' : '· empty';
            this.root.querySelectorAll('[data-debug-cut]').forEach(node => {
                node.hidden = !event.truncated_fields?.includes(node.dataset.debugCut);
            });
            if (event.limit_reached) {
                this.el('[data-debug-input]').textContent = '(Not stored: match recording limit reached.)';
                this.el('[data-debug-output]').textContent = '(Not stored: match recording limit reached.)';
            }
        }

        format(value, pretty) {
            if (!value) return '(empty)';
            if (!pretty) return value;
            try { return JSON.stringify(JSON.parse(value), null, 2); }
            catch { return value; }
        }
    }

    function init() {
        document.querySelectorAll('[data-replay-debug]').forEach(root => {
            if (root.dataset.ready) return;
            root.dataset.ready = 'true';
            new ReplayDebugPanel(root);
        });
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
    else init();
})();
