/**
 * API communication: REST + WebSocket.
 */

const API_BASE = '';  // relative URLs — nginx proxies /api/ and /ws/ to backend

const WS_BASE = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`;

let ws = null;
let wsReconnectTimer = null;
let pendingPreview = null;
let debounceTimer = null;

export async function uploadStep(file) {
    const formData = new FormData();
    formData.append('file', file);

    const res = await fetch(`${API_BASE}/api/upload`, {
        method: 'POST',
        body: formData,
    });

    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || 'Upload failed');
    }

    return res.json();
}

export async function exportShape(request) {
    const res = await fetch(`${API_BASE}/api/export`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
    });

    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || 'Export failed');
    }

    const thicknessHeader = res.headers.get('X-Thickness-Check');
    const blob = await res.blob();

    return {
        blob,
        thicknessCheck: thicknessHeader ? JSON.parse(thicknessHeader) : null,
        contentType: res.headers.get('Content-Type'),
    };
}

// ---------------------------------------------------------------------------
// WebSocket preview
// ---------------------------------------------------------------------------

export function connectPreviewWS(onMessage, onOpen, onClose) {
    if (ws && ws.readyState === WebSocket.OPEN) return;

    ws = new WebSocket(`${WS_BASE}/ws/preview`);

    ws.onopen = () => {
        console.log('[WS] Connected');
        if (onOpen) onOpen();
        // Send any pending preview
        if (pendingPreview) {
            ws.send(JSON.stringify(pendingPreview));
            pendingPreview = null;
        }
    };

    ws.onmessage = (evt) => {
        try {
            const data = JSON.parse(evt.data);
            if (onMessage) onMessage(data);
        } catch (e) {
            console.error('[WS] Parse error', e);
        }
    };

    ws.onclose = () => {
        console.log('[WS] Disconnected');
        ws = null;
        if (onClose) onClose();
        // Reconnect after 2 seconds
        wsReconnectTimer = setTimeout(() => connectPreviewWS(onMessage, onOpen, onClose), 2000);
    };

    ws.onerror = (e) => {
        console.error('[WS] Error', e);
    };
}

export function disconnectPreviewWS() {
    if (wsReconnectTimer) clearTimeout(wsReconnectTimer);
    if (ws) {
        ws.onclose = null;
        ws.close();
        ws = null;
    }
}

/**
 * Send a preview request with 400ms debounce.
 */
export function requestPreview(params) {
    if (debounceTimer) clearTimeout(debounceTimer);

    debounceTimer = setTimeout(() => {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify(params));
        } else {
            pendingPreview = params;
            connectPreviewWS(
                (data) => window._previewCallback && window._previewCallback(data),
                null,
                null
            );
        }
    }, 400);
}

export function setPreviewCallback(fn) {
    window._previewCallback = fn;
}
