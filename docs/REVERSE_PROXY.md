# ZettNAS Toolkit — Reverse Proxy & TLS Configuration Guide

This guide provides tested production configurations for exposing ZettNAS Toolkit through popular reverse proxies including **Nginx**, **Caddy**, **Traefik**, and **Nginx Proxy Manager**.

---

## 1. Critical Proxy Requirements

When proxying ZettNAS Toolkit, two items are strictly required:

1. **Disable Proxy Buffering on Server-Sent Events (SSE)**:
   The live telemetry stream (`/api/stats/stream`) pushes data every 2 seconds over a persistent HTTP connection. If your reverse proxy buffers responses, the dashboard will stall or appear disconnected.
2. **Forward Client Headers**:
   `X-Forwarded-For` and `X-Forwarded-Proto` are required for IP-based rate limiting on login attempts and secure cookie handling.
3. **Tell ZettNAS which proxy to believe**:
   ZettNAS only trusts `X-Forwarded-*` headers from addresses in `TRUSTED_PROXIES` (default `127.0.0.1,::1`). Set it to your proxy's address or subnet, e.g. `TRUSTED_PROXIES=172.18.0.0/16`, or login lockout and the Secure cookie flag will use the proxy's address instead of the client's.
4. **Keep the Host header** (or set `CSRF_TRUSTED_ORIGINS`):
   Changes made in the browser are only accepted when their `Origin` matches the host ZettNAS sees. Proxies that rewrite `Host` must send `X-Forwarded-Host`, or list the public URL in `CSRF_TRUSTED_ORIGINS=https://nas.example.com`.

---

## 2. Nginx Configuration

Save this block inside your Nginx server configuration (e.g. `/etc/nginx/conf.d/zettnas.conf` or in a SWAG site config):

```nginx
server {
    listen 443 ssl http2;
    server_name zettnas.yourdomain.com;

    # SSL certificates
    ssl_certificate     /etc/letsencrypt/live/zettnas.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/zettnas.yourdomain.com/privkey.pem;

    # Client body limit: Set to 0 (unlimited) or higher if using the File Explorer upload
    client_max_body_size 0;

    # Standard headers
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # General WebUI & REST API
    location / {
        proxy_pass http://192.168.1.100:8082;  # Replace with your NAS host IP
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # CRITICAL: Disable buffering for SSE telemetry stream
    location ~ ^/api/(v1/)?stats/stream {
        proxy_pass http://192.168.1.100:8082;  # Replace with your NAS host IP
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 86400s;
        chunked_transfer_encoding off;
    }
}
```

---

## 3. Caddyfile (Caddy v2)

Caddy automatically handles TLS certificate issuance and HTTP/2. Add this block to your `Caddyfile`:

```caddy
zettnas.yourdomain.com {
    # Increase or disable body limit for large file uploads
    request_body {
        max_size 10GB
    }

    # Proxy all traffic to ZettNAS Toolkit
    reverse_proxy 192.168.1.100:8082 {  # Replace with your NAS host IP
        # Flush responses immediately for SSE stream
        flush_interval -1
    }
}
```

### 3b. HTTPS on your LAN with a Caddy sidecar (no domain needed)

Without a proxy, ZettNAS is plain HTTP and passwords cross your network unencrypted. This Compose sidecar gives you `https://<nas-ip>:8443` with a certificate from Caddy's own local CA (`tls internal`); browsers show a warning until you trust that CA once (copy `caddy-data/caddy/pki/authorities/local/root.crt` to your devices).

```yaml
services:
  zettnas-https:
    image: caddy:2
    restart: unless-stopped
    network_mode: host
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - ./caddy-data:/data
```

`Caddyfile`:

```caddy
{
    auto_https disable_redirects
}

:8443 {
    tls internal
    request_body {
        max_size 10GB
    }
    reverse_proxy 127.0.0.1:8082 {
        flush_interval -1
    }
}
```

With `network_mode: host` Caddy connects from `127.0.0.1`, which is already in the default `TRUSTED_PROXIES`. Then stop publishing port 8082 to your LAN (or firewall it) so all access goes through HTTPS.

---

## 4. Traefik (Docker Labels)

If routing through Traefik v2/v3, add these labels to `docker-compose.yml`:

```yaml
services:
  zettnas-toolkit:
    # ... other configuration ...
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.zettnas.rule=Host(`zettnas.yourdomain.com`)"
      - "traefik.http.routers.zettnas.entrypoints=websecure"
      - "traefik.http.routers.zettnas.tls.certresolver=letsencrypt"
      - "traefik.http.services.zettnas.loadbalancer.server.port=8082"
      # Buffering middleware disabled to support SSE
      - "traefik.http.middlewares.zettnas-buffering.buffering.maxResponseBodyBytes=0"
      - "traefik.http.routers.zettnas.middlewares=zettnas-buffering"
```

---

## 5. Nginx Proxy Manager (NPM)

If using the Unraid **Nginx Proxy Manager** GUI:
1. **Details Tab**:
   - Forward Hostname: IP of your NAS (e.g. `192.168.1.100` or host Docker IP)
   - Forward Port: `8082`
   - Turn **ON**: *Cache Assets*, *Block Common Exploits*, *Websockets Support*
2. **SSL Tab**:
   - Select your SSL Certificate.
   - Turn **ON**: *Force SSL*, *HTTP/2 Support*, *HSTS Enabled*
3. **Advanced Tab** (Add this to the custom configuration box to disable SSE buffering):
   ```nginx
   location ~ ^/api/(v1/)?stats/stream {
       proxy_pass http://$server:$port;
       proxy_http_version 1.1;
       proxy_set_header Connection "";
       proxy_buffering off;
       proxy_cache off;
       proxy_read_timeout 86400s;
   }
   ```
