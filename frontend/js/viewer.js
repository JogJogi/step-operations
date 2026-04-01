/**
 * Three.js 3D viewer for STEP mesh visualization.
 *
 * Features:
 * - Orbit/zoom/pan controls
 * - Face selection highlighting
 * - Thin-wall warning overlay (red faces)
 * - Locked face overlay (blue faces)
 */

import * as THREE from '/vendor/three.module.js';
import { OrbitControls } from '/vendor/OrbitControls.js';
import { MeshBVH, acceleratedRaycast } from '/vendor/three-mesh-bvh.module.js';

// Patch Three.js raycasting with BVH for performance
THREE.Mesh.prototype.raycast = acceleratedRaycast;

export class Viewer {
    constructor(container) {
        this.container = container;
        this.scene = null;
        this.camera = null;
        this.renderer = null;
        this.controls = null;
        this.mainMesh = null;
        this.overlayMesh = null;  // Locked + thin face highlights
        this.faceMap = {};         // triangle_index -> face_id
        this.lockedFaceIds = new Set();
        this.thinTriangleIds = new Set();

        this._onFaceClick = null;
        this._animFrameId = null;

        this._init();
    }

    _init() {
        const w = this.container.clientWidth;
        const h = this.container.clientHeight;

        // Scene
        this.scene = new THREE.Scene();
        this.scene.background = new THREE.Color(0x1a1a2e);

        // Camera
        this.camera = new THREE.PerspectiveCamera(45, w / h, 0.01, 1000);
        this.camera.position.set(0, 0, 30);

        // Renderer
        this.renderer = new THREE.WebGLRenderer({ antialias: true });
        this.renderer.setPixelRatio(window.devicePixelRatio);
        this.renderer.setSize(w, h);
        this.renderer.shadowMap.enabled = true;
        this.container.appendChild(this.renderer.domElement);

        // Lights
        const ambient = new THREE.AmbientLight(0xffffff, 0.4);
        this.scene.add(ambient);

        const key = new THREE.DirectionalLight(0xffffff, 1.2);
        key.position.set(10, 20, 15);
        this.scene.add(key);

        const fill = new THREE.DirectionalLight(0xaaccff, 0.5);
        fill.position.set(-10, -5, -10);
        this.scene.add(fill);

        const rim = new THREE.DirectionalLight(0xffffff, 0.3);
        rim.position.set(0, 10, -15);
        this.scene.add(rim);

        // Controls
        this.controls = new OrbitControls(this.camera, this.renderer.domElement);
        this.controls.enableDamping = true;
        this.controls.dampingFactor = 0.05;

        // Raycaster for face selection
        this.raycaster = new THREE.Raycaster();
        this.mouse = new THREE.Vector2();

        this.renderer.domElement.addEventListener('click', (e) => this._onCanvasClick(e));

        // Resize observer
        new ResizeObserver(() => this._onResize()).observe(this.container);

        this._animate();
    }

    _animate() {
        this._animFrameId = requestAnimationFrame(() => this._animate());
        this.controls.update();
        this.renderer.render(this.scene, this.camera);
    }

    _onResize() {
        const w = this.container.clientWidth;
        const h = this.container.clientHeight;
        this.camera.aspect = w / h;
        this.camera.updateProjectionMatrix();
        this.renderer.setSize(w, h);
    }

    /**
     * Load mesh data from backend JSON.
     *
     * meshData: { vertices: [...], indices: [...], normals: [...], face_map: {tri_idx: face_id} }
     */
    loadMesh(meshData) {
        // Remove old meshes
        if (this.mainMesh) {
            this.scene.remove(this.mainMesh);
            this.mainMesh.geometry.dispose();
            this.mainMesh.material.dispose();
        }
        if (this.overlayMesh) {
            this.scene.remove(this.overlayMesh);
            this.overlayMesh.geometry.dispose();
            this.overlayMesh.material.dispose();
        }

        this.faceMap = meshData.face_map || {};
        this.thinTriangleIds = new Set(meshData.thin_triangle_indices || []);

        const vertices = new Float32Array(meshData.vertices);
        const indices = new Uint32Array(meshData.indices);
        const normals = new Float32Array(meshData.normals || []);

        const geo = new THREE.BufferGeometry();
        geo.setAttribute('position', new THREE.BufferAttribute(vertices, 3));
        geo.setIndex(new THREE.BufferAttribute(indices, 1));
        if (normals.length > 0) {
            geo.setAttribute('normal', new THREE.BufferAttribute(normals, 3));
        } else {
            geo.computeVertexNormals();
        }

        // Build BVH for fast raycasting
        geo.boundsTree = new MeshBVH(geo);

        const mat = new THREE.MeshStandardMaterial({
            color: 0xc8a86b,        // Gold-ish metallic
            metalness: 0.8,
            roughness: 0.2,
            side: THREE.DoubleSide,
        });

        this.mainMesh = new THREE.Mesh(geo, mat);
        this.scene.add(this.mainMesh);

        // Fit camera to object
        const box = new THREE.Box3().setFromObject(this.mainMesh);
        const center = box.getCenter(new THREE.Vector3());
        const size = box.getSize(new THREE.Vector3());
        const maxDim = Math.max(size.x, size.y, size.z);
        this.controls.target.copy(center);
        this.camera.position.copy(center);
        this.camera.position.z += maxDim * 2.5;
        this.controls.update();

        // Build overlay for locked/thin faces
        this._rebuildOverlay();
    }

    /**
     * Update mesh geometry in-place (for live preview).
     */
    updateMesh(meshData) {
        this.faceMap = meshData.face_map || {};
        this.thinTriangleIds = new Set(meshData.thin_triangle_indices || []);

        if (!this.mainMesh) {
            this.loadMesh(meshData);
            return;
        }

        const geo = this.mainMesh.geometry;
        const vertices = new Float32Array(meshData.vertices);
        const indices = new Uint32Array(meshData.indices);
        const normals = new Float32Array(meshData.normals || []);

        geo.setAttribute('position', new THREE.BufferAttribute(vertices, 3));
        geo.setIndex(new THREE.BufferAttribute(indices, 1));
        if (normals.length > 0) {
            geo.setAttribute('normal', new THREE.BufferAttribute(normals, 3));
        } else {
            geo.computeVertexNormals();
        }
        geo.attributes.position.needsUpdate = true;

        // Rebuild BVH
        geo.boundsTree = new MeshBVH(geo);

        this._rebuildOverlay();
    }

    /**
     * Rebuild the overlay mesh showing locked (blue) and thin (red) faces.
     */
    _rebuildOverlay() {
        if (this.overlayMesh) {
            this.scene.remove(this.overlayMesh);
            this.overlayMesh.geometry.dispose();
            this.overlayMesh.material.dispose();
            this.overlayMesh = null;
        }

        if (!this.mainMesh) return;

        const geo = this.mainMesh.geometry;
        const indexAttr = geo.index;
        if (!indexAttr) return;

        const indices = indexAttr.array;
        const positions = geo.attributes.position.array;
        const numTris = indices.length / 3;

        // Collect overlay triangles
        const overlayPositions = [];
        const overlayColors = [];

        for (let i = 0; i < numTris; i++) {
            const faceId = this.faceMap[i];
            const isLocked = faceId && this.lockedFaceIds.has(faceId);
            const isThin = this.thinTriangleIds.has(i);

            if (!isLocked && !isThin) continue;

            const color = isLocked
                ? [0.2, 0.4, 1.0]   // Blue for locked
                : [1.0, 0.2, 0.1];  // Red for thin

            for (let j = 0; j < 3; j++) {
                const vi = indices[i * 3 + j] * 3;
                overlayPositions.push(positions[vi], positions[vi + 1], positions[vi + 2]);
                overlayColors.push(...color);
            }
        }

        if (overlayPositions.length === 0) return;

        const overlayGeo = new THREE.BufferGeometry();
        overlayGeo.setAttribute('position', new THREE.Float32BufferAttribute(overlayPositions, 3));
        overlayGeo.setAttribute('color', new THREE.Float32BufferAttribute(overlayColors, 3));

        const overlayMat = new THREE.MeshBasicMaterial({
            vertexColors: true,
            transparent: true,
            opacity: 0.5,
            side: THREE.DoubleSide,
            depthTest: false,
        });

        this.overlayMesh = new THREE.Mesh(overlayGeo, overlayMat);
        this.scene.add(this.overlayMesh);
    }

    /**
     * Handle canvas click for face selection.
     */
    _onCanvasClick(event) {
        if (!this.mainMesh || !this._onFaceClick) return;

        const rect = this.renderer.domElement.getBoundingClientRect();
        this.mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
        this.mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

        this.raycaster.setFromCamera(this.mouse, this.camera);
        const hits = this.raycaster.intersectObject(this.mainMesh);

        if (hits.length > 0) {
            const hit = hits[0];
            const triIndex = hit.faceIndex;
            const faceId = this.faceMap[triIndex];
            if (faceId) {
                this._onFaceClick(faceId, triIndex, event);
            }
        }
    }

    /**
     * Toggle locked state of a face.
     */
    toggleFaceLock(faceId) {
        if (this.lockedFaceIds.has(faceId)) {
            this.lockedFaceIds.delete(faceId);
        } else {
            this.lockedFaceIds.add(faceId);
        }
        this._rebuildOverlay();
    }

    setLockedFaces(faceIds) {
        this.lockedFaceIds = new Set(faceIds);
        this._rebuildOverlay();
    }

    getLockedFaceIds() {
        return [...this.lockedFaceIds];
    }

    updateThinFaces(triangleIndices) {
        this.thinTriangleIds = new Set(triangleIndices || []);
        this._rebuildOverlay();
    }

    onFaceClick(fn) {
        this._onFaceClick = fn;
    }

    destroy() {
        if (this._animFrameId) cancelAnimationFrame(this._animFrameId);
        this.renderer.dispose();
        this.container.removeChild(this.renderer.domElement);
    }
}
