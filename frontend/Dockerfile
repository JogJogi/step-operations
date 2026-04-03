FROM nginx:alpine

# Download Three.js UMD build + OrbitControls at build time (no CDN needed at runtime)
RUN apk add --no-cache wget && \
    mkdir -p /tmp/vendor && \
    wget -q -O /tmp/vendor/three.min.js \
        'https://cdn.jsdelivr.net/npm/three@0.168.0/build/three.min.js' && \
    wget -q -O /tmp/vendor/OrbitControls.js \
        'https://cdn.jsdelivr.net/npm/three@0.168.0/examples/js/controls/OrbitControls.js' && \
    apk del wget

COPY . /usr/share/nginx/html/
RUN mkdir -p /usr/share/nginx/html/vendor && \
    mv /tmp/vendor/three.min.js /usr/share/nginx/html/vendor/ && \
    mv /tmp/vendor/OrbitControls.js /usr/share/nginx/html/vendor/

COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
