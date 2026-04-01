/**
 * UI Controls: manages all sliders, buttons, and panels.
 * Emits events when parameters change.
 */

export class Controls {
    constructor() {
        this.listeners = {};
        this._currentEffect = null;
        this._init();
    }

    _init() {
        // Effect tabs
        document.querySelectorAll('.effect-tab').forEach(btn => {
            btn.addEventListener('click', () => this._selectEffect(btn.dataset.effect));
        });

        // All range sliders - emit 'params-changed' on input
        document.querySelectorAll('input[type="range"]').forEach(input => {
            const valDisplay = document.getElementById(`${input.id}-val`);
            input.addEventListener('input', () => {
                if (valDisplay) valDisplay.textContent = this._formatValue(input);
                this._emit('params-changed', this.getParams());
            });
            // Init display
            if (valDisplay) valDisplay.textContent = this._formatValue(input);
        });

        // All checkboxes
        document.querySelectorAll('input[type="checkbox"]').forEach(input => {
            input.addEventListener('change', () => this._emit('params-changed', this.getParams()));
        });

        // Min thickness
        const thicknessInput = document.getElementById('min-thickness');
        if (thicknessInput) {
            thicknessInput.addEventListener('input', () => {
                const display = document.getElementById('min-thickness-val');
                if (display) display.textContent = thicknessInput.value + ' mm';
                this._emit('params-changed', this.getParams());
            });
        }

        // Lock mode toggle
        const lockBtn = document.getElementById('lock-mode-btn');
        if (lockBtn) {
            lockBtn.addEventListener('click', () => {
                const active = lockBtn.classList.toggle('active');
                this._emit('lock-mode-changed', active);
                lockBtn.textContent = active ? '🔒 Lock Mode: ON' : '🔓 Lock Mode: OFF';
            });
        }

        // Clear locks
        document.getElementById('clear-locks-btn')?.addEventListener('click', () => {
            this._emit('clear-locks');
        });

        // Export buttons
        document.getElementById('export-step-btn')?.addEventListener('click', () => {
            this._emit('export', { format: 'step' });
        });
        document.getElementById('export-stl-btn')?.addEventListener('click', () => {
            this._emit('export', { format: 'stl' });
        });

        // Auto-detect ring bore button
        document.getElementById('auto-detect-bore-btn')?.addEventListener('click', () => {
            this._emit('auto-detect-bore');
        });
    }

    _selectEffect(effect) {
        this._currentEffect = effect;

        document.querySelectorAll('.effect-tab').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.effect === effect);
        });
        document.querySelectorAll('.effect-panel').forEach(panel => {
            panel.classList.toggle('hidden', panel.dataset.effect !== effect);
        });

        this._emit('params-changed', this.getParams());
    }

    _formatValue(input) {
        const v = parseFloat(input.value);
        const unit = input.dataset.unit || '';
        const decimals = input.dataset.decimals ? parseInt(input.dataset.decimals) : 1;
        return v.toFixed(decimals) + (unit ? ' ' + unit : '');
    }

    getEffect() {
        return this._currentEffect;
    }

    getParams() {
        const effect = this._currentEffect;
        const params = {};

        if (effect === 'polygonize') {
            params.triangle_size_mm = parseFloat(document.getElementById('tri-size')?.value ?? 2);
            params.uniform = document.getElementById('tri-uniform')?.checked ?? true;
            params.angular_deflection = parseFloat(document.getElementById('tri-angular')?.value ?? 0.5);
        } else if (effect === 'crystal') {
            params.facet_size_mm = parseFloat(document.getElementById('crystal-size')?.value ?? 3);
            params.sharpness = parseFloat(document.getElementById('crystal-sharpness')?.value ?? 0.5);
        } else if (effect === 'voronoi') {
            params.num_seeds = parseInt(document.getElementById('voronoi-seeds')?.value ?? 80);
            params.randomness = parseFloat(document.getElementById('voronoi-randomness')?.value ?? 0.5);
        } else if (effect === 'grid') {
            params.grid_size_mm = parseFloat(document.getElementById('grid-size')?.value ?? 2);
            params.rotation_deg = parseFloat(document.getElementById('grid-rotation')?.value ?? 0);
        }

        return {
            effect,
            params,
            min_thickness_mm: parseFloat(document.getElementById('min-thickness')?.value ?? 0.8),
        };
    }

    // ---------------------------------------------------------------------------
    // Event emitter
    // ---------------------------------------------------------------------------

    on(event, fn) {
        if (!this.listeners[event]) this.listeners[event] = [];
        this.listeners[event].push(fn);
    }

    _emit(event, data) {
        (this.listeners[event] || []).forEach(fn => fn(data));
    }
}
