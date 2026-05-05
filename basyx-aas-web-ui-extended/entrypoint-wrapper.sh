#!/bin/sh
set -e

# Generate the InfluxDB reverse-proxy location at runtime so the token
# never appears in a browser request (same-origin via nginx, no CORS).
mkdir -p /etc/nginx/conf.d

cat > /etc/nginx/conf.d/influxdb-proxy.conf <<NGINX_PROXY
location /influxdb/ {
    proxy_pass         http://influxdb:8086/;
    proxy_http_version 1.1;
    proxy_set_header   Connection       "";
    proxy_set_header   Host             influxdb;
    proxy_set_header   Authorization    "Token ${INFLUXDB_TOKEN}";
}
NGINX_PROXY

exec /usr/src/app/entrypoint.sh
