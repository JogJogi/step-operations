FROM nginx:alpine

COPY . /usr/share/nginx/html/
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Vendor Three.js dependencies locally so no CDN needed at runtime
RUN apk add --no-cache wget && \
    mkdir -p /usr/share/nginx/html/vendor && \
    wget -q -O /usr/share/nginx/html/vendor/three.module.js \
        'https://cdn.jsdelivr.net/npm/three@0.168.0/build/three.module.js' && \
    wget -q -O /usr/share/nginx/html/vendor/OrbitControls.js \
        'https://cdn.jsdelivr.net/npm/three@0.168.0/examples/jsm/controls/OrbitControls.js' && \
    wget -q -O /usr/share/nginx/html/vendor/three-mesh-bvh.module.js \
        'https://cdn.jsdelivr.net/npm/three-mesh-bvh@0.7.8/build/index.module.js' && \
    apk del wget

EXPOSE 80
