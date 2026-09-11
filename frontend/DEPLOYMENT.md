# Frontend deployment

`npm run build` creates a static Vite application in `frontend/dist`. Serve that directory with a production web
server or CDN. `vite preview` is a local smoke-test server and is not a production server.

## Required routing

Apply routes in this order:

1. Send `/api/`, `/admin/`, and `/health/` to Django.
2. Serve Django's collected `/static/` files or route that path to the backend's static-file service.
3. Serve an existing frontend asset from `frontend/dist`.
4. Return `frontend/dist/index.html` for every remaining application route.

The final fallback is required because React Router owns paths such as `/runs/{id}` and `/review/{documentId}`.
Without it, opening or refreshing a deep link returns a web-server 404 before React starts.

## Required caching

| Resource                                           | Cache-Control                         | Reason                                                                                         |
| -------------------------------------------------- | ------------------------------------- | ---------------------------------------------------------------------------------------------- |
| `index.html` and SPA fallback responses            | `no-cache`                            | Browsers revalidate the application shell and receive current chunk names after a deployment.  |
| `/assets/*`                                        | `public, max-age=31536000, immutable` | Vite includes a content hash in each built asset name.                                         |
| Unhashed public files such as `favicon.svg`        | `no-cache`                            | Their URL can stay the same when their content changes.                                        |
| Django API, authentication, and document responses | Preserve backend headers              | These can contain user-specific or sensitive data and must never inherit static-asset caching. |

The application also handles Vite's `vite:preloadError` event. When an open tab requests a chunk removed by a new
deployment, it reloads once to obtain the current `index.html`. A one-minute session guard prevents a broken release
from causing a reload loop. Correct HTML caching remains necessary because the recovery starts from `index.html`.

## NGINX example

Replace the paths and upstream name with deployment values. TLS may terminate at NGINX or an approved upstream
application gateway.

```nginx
server {
    listen 443 ssl;
    server_name docai.example.internal;

    root /opt/docai/frontend/dist;

    location = /index.html {
        add_header Cache-Control "no-cache" always;
        try_files $uri =404;
    }

    location /assets/ {
        add_header Cache-Control "public, max-age=31536000, immutable" always;
        try_files $uri =404;
    }

    location = /favicon.svg {
        add_header Cache-Control "no-cache" always;
        try_files $uri =404;
    }

    location ~ ^/(api|admin|health)(/|$) {
        proxy_pass http://docai_django;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /static/ {
        alias /opt/docai/backend/staticfiles/;
        add_header Cache-Control "public, max-age=86400" always;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

Enable `DJANGO_TRUST_X_FORWARDED_PROTO=true` only when the trusted proxy strips client-supplied
`X-Forwarded-Proto`. Set `DOCAI_FRONTEND_URL` to the public frontend root so Django admin's **View site** link follows
the environment. A separate frontend origin also requires explicit `DOCAI_CORS_ORIGINS` and
`DOCAI_CSRF_TRUSTED` values.

## Release verification

```bash
cd frontend
npm ci
npm run lint
npm test
npm run build
npm run preview -- --host 127.0.0.1 --strictPort
```

Verify a deep link directly against the production web server, confirm that it returns the SPA, and inspect response
headers for `/index.html`, one `/assets/` file, and an authenticated API response before promoting the release.
