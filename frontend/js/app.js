/**
 * Main application logic.
 * Wires together Viewer, Controls, and API.
 */

import { Viewer } from './viewer.js';
import { Controls } from './controls.js';
import {
    uploadStep,
    exportShape,
    connectPreviewWS,
    requestPreview,
    setPreviewCallback,
} from './api.js';

let viewer = null;
let controls = null;
let currentMeshId = null;
let lockModeActive = false;

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

window.addEventListener('DOMContentLoaded', () => {
    const container = document.getElementById('viewer-container');
    viewer = new Viewer(container);
    controls = new Controls();

    // File upload
    const dropzone = document.getElementById('dropzone');
    const fileInput = document.getElementById('file-input');

    // Label[for=file-input] handles click natively — no JS click handler needed.
    // Drag & drop:
    dropzone.addEventListener('dragover', (e) => { e.preventDefault(); dropzone.classList.add('drag-over'); });
    dropzone.addEventListener('dragleave', () => dropzone.classList.remove('drag-over'));
    dropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropzone.classList.remove('drag-over');
        const file = e.dataTransfer.files[0];
        if (file) handleFileUpload(file);
    });
    fileInput.addEventListener('change', () => {
        if (fileInput.files[0]) handleFileUpload(fileInput.files[0]);
    });

    // Controls events
    controls.on('params-changed', (data) => {
        if (!currentMeshId) return;
        triggerPreview(data);
    });

    controls.on('lock-mode-changed', (active) => {
        lockModeActive = active;
        document.getElementById('viewer-container').style.cursor = active ? 'crosshair' : 'default';
        setStatus(active ? 'Click faces to lock/unlock them' : '');
    });

    controls.on('clear-locks', () => {
        viewer.setLockedFaces([]);
        triggerPreview(controls.getParams());
        updateLockedCount(0);
    });

    controls.on('export', ({ format }) => handleExport(format));

    controls.on('auto-detect-bore', () => autoDetectBore());

    // Face click
    viewer.onFaceClick((faceId) => {
        if (!lockModeActive) return;
        viewer.toggleFaceLock(faceId);
        updateLockedCount(viewer.getLockedFaceIds().length);
        triggerPreview(controls.getParams());
    });

    // WebSocket
    setPreviewCallback((data) => {
        if (data.error) {
            setStatus('Preview error: ' + data.error, 'error');
            return;
        }
        viewer.updateMesh(data);
        updateThicknessStatus(data);
        hideLoading();
    });

    connectPreviewWS(
        (data) => {
            if (data.error) {
                setStatus('Preview error: ' + data.error, 'error');
                return;
            }
            viewer.updateMesh(data);
            updateThicknessStatus(data);
            hideLoading();
        },
        () => setStatus('Connected', 'ok'),
        () => setStatus('Reconnecting...', 'warn')
    );
});

// ---------------------------------------------------------------------------
// File upload
// ---------------------------------------------------------------------------

async function handleFileUpload(file) {
    setStatus('Uploading...', 'info');
    showLoading('Loading STEP file...');

    try {
        const result = await uploadStep(file);
        currentMeshId = result.mesh_id;

        viewer.loadMesh(result.mesh);

        document.getElementById('dropzone').classList.add('hidden');
        document.getElementById('main-ui').classList.remove('hidden');
        document.getElementById('filename-display').textContent = result.filename;
        document.getElementById('face-count').textContent = result.num_faces;

        setStatus(`Loaded: ${result.filename} (${result.num_faces} faces)`, 'ok');
        hideLoading();

        // Initial preview (no effect)
        triggerPreview(controls.getParams());
    } catch (err) {
        setStatus('Upload failed: ' + err.message, 'error');
        hideLoading();
    }
}

// ---------------------------------------------------------------------------
// Preview
// ---------------------------------------------------------------------------

function triggerPreview(data) {
    if (!currentMeshId) return;

    const { effect, params, min_thickness_mm } = data;
    showLoading('Processing...');

    requestPreview({
        mesh_id: currentMeshId,
        effect: effect || null,
        params: params || {},
        locked_faces: viewer.getLockedFaceIds(),
        min_thickness: min_thickness_mm,
    });
}

// ---------------------------------------------------------------------------
// Export
// ---------------------------------------------------------------------------

async function handleExport(format) {
    if (!currentMeshId) return;

    const { effect, params, min_thickness_mm } = controls.getParams();
    setStatus('Exporting...', 'info');
    showLoading('Generating ' + format.toUpperCase() + '...');

    try {
        const result = await exportShape({
            mesh_id: currentMeshId,
            locked_face_ids: viewer.getLockedFaceIds(),
            effect: effect || null,
            params: params || {},
            format,
            min_thickness_mm,
        });

        // Download file
        const url = URL.createObjectURL(result.blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = format === 'stl' ? 'ring_modified.stl' : 'ring_modified.step';
        a.click();
        URL.revokeObjectURL(url);

        // Show thickness result
        if (result.thicknessCheck) {
            const tc = result.thicknessCheck;
            if (tc.passes) {
                setStatus(`Export OK — min wall: ${tc.min_found_mm}mm`, 'ok');
            } else {
                setStatus(`Export done ⚠️ Thin walls detected! Min: ${tc.min_found_mm}mm`, 'warn');
            }
        } else {
            setStatus('Export complete', 'ok');
        }
    } catch (err) {
        setStatus('Export failed: ' + err.message, 'error');
    } finally {
        hideLoading();
    }
}

// ---------------------------------------------------------------------------
// Auto-detect bore (inner ring surface)
// ---------------------------------------------------------------------------

function autoDetectBore() {
    if (!currentMeshId) return;
    // Heuristic: the bore is the innermost cylindrical surface (smallest bounding box extent)
    // For now, tell user to manually select it
    lockModeActive = true;
    document.getElementById('lock-mode-btn').classList.add('active');
    document.getElementById('lock-mode-btn').textContent = '🔒 Lock Mode: ON';
    document.getElementById('viewer-container').style.cursor = 'crosshair';
    setStatus('Click the inner ring surface to protect it', 'info');
}

// ---------------------------------------------------------------------------
// UI helpers
// ---------------------------------------------------------------------------

function setStatus(msg, level = '') {
    const el = document.getElementById('status-bar');
    if (!el) return;
    el.textContent = msg;
    el.className = 'status-bar ' + level;
}

function showLoading(msg) {
    const el = document.getElementById('loading-overlay');
    if (!el) return;
    el.querySelector('.loading-text').textContent = msg;
    el.classList.remove('hidden');
}

function hideLoading() {
    document.getElementById('loading-overlay')?.classList.add('hidden');
}

function updateLockedCount(n) {
    const el = document.getElementById('locked-count');
    if (el) el.textContent = n;
}

function updateThicknessStatus(data) {
    const el = document.getElementById('thickness-status');
    if (!el) return;

    if (data.passes === undefined) {
        el.textContent = '—';
        el.className = '';
        return;
    }

    el.textContent = data.passes
        ? `✓ ${data.min_found_mm}mm`
        : `⚠ ${data.min_found_mm}mm`;
    el.className = data.passes ? 'ok' : 'warn';

    viewer.updateThinFaces(data.thin_triangle_indices || []);
}
