# Frontend deployment

`npm run build` creates a static Vite application in `frontend/dist`. Serve that directory with a production web
server or CDN. `vite preview` is a local smoke-test server and is not a production server.

## Page title configuration

Set these public **build-time** values in the build environment or Vite `.env` files before building:

```dotenv
# Local development (also the default when these values are absent)
VITE_DEPLOYMENT_ENV=dev
VITE_APPLICATION_NAME=Document AI
```

```bash
# Production: explicitly select prod (production is also accepted).
VITE_DEPLOYMENT_ENV=prod VITE_APPLICATION_NAME="Document AI" npm run build
# UAT: an optimized build still has the [UAT] prefix.
VITE_DEPLOYMENT_ENV=uat VITE_APPLICATION_NAME="Document AI" npm run build
```

PowerShell equivalent (set `uat` instead of `prod` for UAT):

```powershell
$env:VITE_DEPLOYMENT_ENV = "prod"
$env:VITE_APPLICATION_NAME = "Document AI"
npm run build
```

The application name defaults to `Document AI`; blank values use that default. Environment labels
are trimmed and uppercased. Missing/blank environments default to `DEV`, including optimized builds;
`prod` and `production` omit the prefix, while other explicit labels such as `uat`, `qa`, and `rnd`
produce `[UAT]`, `[QA]`, and `[RND]`. Never infer deployment identity from Vite's optimization mode.
Changing Django environment values or changing a server's environment after building does not change
these static assets: rebuild for each deployment environment or application-name change. Do not put
secrets or record/customer information in these public values.

`src/app/page-title-config.ts` provides the shared configuration for React and Vite's HTML transform.
The source HTML has a nonempty `Document AI` fallback; the transform safely escapes and substitutes
the configured application name for both development and built HTML. React then supplies the route
label, for example `Review Queue | Document AI` or `[UAT] Review Queue | Document AI`, before session
and page data loading finish. No additional API request is involved.

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

## Institutional Teams check — pending manual validation

**Not performed in this development environment.** This check requires the institution's actual
browser and Teams client and an authenticated user. Automated browser tests validate page titles,
not Teams formatting or preview cards.

1. Open `/review` in the intended deployment and confirm its exact browser title; also open a deep
   document link and refresh it to confirm `Extraction Results | Document AI` (with the configured
   nonproduction prefix when applicable).
2. Record the original destination URL. Copy the address using the institution's workflow that
   supports formatted hyperlinks, then paste normally into a Teams message draft.
3. Record browser name/version, Teams client/version, deployment, copy workflow, expected browser
   title, displayed hyperlink text, and whether the destination URL is unchanged. Inspect the link
   destination; do not send the message merely to perform this check.
4. If the workflow pastes only a plain URL, record that client/workflow limitation. Do not treat it
   as an application title failure or add Teams integrations, preview tags, or a Copy Link button.

| Check | Result |
| --- | --- |
| Browser and Teams client/version | Pending institutional check |
| Deployment and copy workflow | Pending institutional check |
| Browser title and pasted link text match | Not tested |
| Destination URL unchanged | Not tested |

Application acceptance depends on correct `document.title`; title-based pasting is a client-dependent
integration check. Run the focused automated navigation/privacy suite with
`npm --prefix e2e test -- page-titles.spec.ts`. Set `VITE_DEPLOYMENT_ENV=prod` or `uat` on that command
to exercise a rebuilt bundle for each environment. Use the same title configuration when pointing
these tests at already-built assets via `PLAYWRIGHT_BASE_URL`.
