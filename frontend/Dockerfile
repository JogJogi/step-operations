FROM nginx:alpine

COPY . /usr/share/nginx/html/

# Simple nginx config with proper MIME types for JS modules
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
