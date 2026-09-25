# DocAI command-line client

`docai` is a small, separately installable HTTP client for automation and interactive terminal use. It calls the
same versioned REST API as the web application; it does not import Django, connect to the database, or reimplement
workflow rules. The API remains the authorization and business-logic boundary.

## Install for this checkout

Prerequisites: Python 3.11+ and `uv`. From the repository root:

```bash
uv sync --project cli --group dev
uv run --project cli docai --help
uv run --project cli docai projects list
```

The `uv run` form is explicit and works without changing your shell configuration. The CLI targets Django at
`http://127.0.0.1:8000` by default, not Vite on port 5173. Override with `DOCAI_BASE_URL` or `--base-url`.

## Make `docai` available in zsh or bash

To run `docai projects list` directly from any directory, install the checkout as an editable uv tool. Editable
installation means code changes in this clone are immediately visible to the command:

```bash
# Run from the repository root.
uv tool install --editable ./cli
uv tool update-shell
```

`uv tool update-shell` adds uv's executable directory to common shell startup files. Open a new terminal, or reload
the startup file for the shell you are currently using. Do not source the Bash file from zsh (or the zsh file from
Bash): shell startup files contain shell-specific commands.

In **zsh**, run:

```zsh
source ~/.zshrc
```

In **bash**, run:

```bash
source ~/.bashrc
```

Then verify that the command is on PATH:

```bash
command -v docai
docai --help
```

If the command is still not found, inspect the directory uv uses and add it to the appropriate shell config:

```bash
uv tool dir --bin
```

For **zsh**, add this line once to `~/.zshrc`:

```bash
export PATH="$(uv tool dir --bin):$PATH"
```

On macOS, if Terminal starts bash as a login shell and does not read `.bashrc`, make `~/.bash_profile` load it:

```bash
[[ -f ~/.bashrc ]] && source ~/.bashrc
```

You can instead copy the printed path from `uv tool dir --bin` into `PATH`. Do not add `cli/.venv/bin` to `PATH`:
that environment is project-local and can disappear when the checkout is removed. To uninstall the tool later, run
`uv tool uninstall docai-cli`.

PowerShell uses the same package commands with Windows paths:

```powershell
uv tool install --editable .\cli
uv tool update-shell
docai --help
```

If Windows still cannot find `docai`, run `uv tool dir --bin` and add that directory to your **user** `Path` in
Windows Environment Variables, then open a new PowerShell window.

For an approved package index, install the published package as a tool instead:

```bash
uv tool install docai-cli
```

## Authentication and connection settings

The client starts a short-lived Django session for each command by default and attempts logout afterward. It does not
save cookies. Supply the username as `DOCAI_USERNAME`; the password comes from `DOCAI_PASSWORD`, hidden terminal
prompting, or one line on stdin with `--password-stdin`. There is intentionally no password command-line argument.
Non-interactive runs fail instead of prompting when no password source is configured.

For local interactive use, set a username and let the CLI prompt for the password without echoing it:

```bash
export DOCAI_USERNAME=admin
docai projects list
```

The Django API must be running at the configured base URL. The first authenticated command prompts for the password;
`docai --help` does not contact the API and does not require credentials.

PowerShell equivalent:

```powershell
$env:DOCAI_USERNAME = "admin"
docai projects list
```

For service automation, HTTP Basic authentication can be simpler when the deployment has explicitly enabled it.
Set `DOCAI_AUTH=basic`, `DOCAI_USERNAME`, and `DOCAI_PASSWORD`; use this only with HTTPS. Basic authentication is
disabled by default on deployed settings. This client boundary can later use an OIDC token provider without changing
the command-to-API contract.

| Setting | Purpose |
| --- | --- |
| `DOCAI_BASE_URL` | Django origin, for example `https://docai.example`; defaults to local port 8000 |
| `DOCAI_AUTH` | `session` (default) or `basic` |
| `DOCAI_USERNAME`, `DOCAI_PASSWORD` | Current inbound API credentials |
| `HTTPS_PROXY`, `HTTP_PROXY`, `NO_PROXY` | Outbound client proxy settings |
| `REQUESTS_CA_BUNDLE` | Optional PEM bundle for institutional TLS inspection |

TLS verification remains enabled. The client ignores `.netrc` credentials so an unrelated machine account cannot be
sent to DocAI; proxy variables and an explicit CA bundle remain supported.

## Common workflows

Check the service, discover projects and approved workflows, and inspect a callable contract:

```bash
docai health
docai projects list
docai datasets list --project PROJECT_UUID
docai workflows list --project PROJECT_UUID --status approved
docai workflows contract WORKFLOW_UUID
```

Upload documents first, then submit their accepted IDs. The API reports partial acceptance and rejection details; do
not invoke rejected files. `--json` emits one machine-readable object, so an automation can preserve IDs and errors:

```bash
docai documents upload --dataset DATASET_UUID ./w2-a.pdf ./w2-b.pdf --json
docai documents list --dataset DATASET_UUID --json
docai runs submit --workflow WORKFLOW_UUID --dataset DATASET_UUID \
  --document-id DOCUMENT_UUID --name "September W-2 batch" --client-reference payroll-1042
docai runs wait RUN_UUID --timeout 300 --json
docai runs export RUN_UUID --format json --output results.json
```

For an interactive status display and a short completion summary, omit `--json` from `runs wait`.

`runs submit` returns an asynchronous run handle and the `Idempotency-Key`. Save that key with the caller's job
record before retrying an uncertain submission. Reuse it only with the same workflow, dataset, selected documents,
name, and client reference. A changed request under that key is a conflict. The CLI does not blindly retry writes.

Inspect detailed progress, request cancellation, retry failed items, or list review work:

```bash
docai runs progress RUN_UUID
docai runs cancel RUN_UUID
docai runs retry RUN_UUID
docai review list --run RUN_UUID
```

For shell pipelines, `--id-only` prints full UUIDs one per line. Lists accept `--page` and `--limit` (1–200);
`--all` follows pagination up to 1,000 pages. Reaching the cap is an error; `--json` includes the partial records
in `data` so automation can recover them.

## Output and errors

All successful command data goes to stdout. Human progress and diagnostics go to stderr. `--json` works before or
after the command, writes exactly one compact JSON object to stdout, and keeps progress off that stream. `NO_COLOR`
or `--no-color` disables ANSI colors; `FORCE_COLOR=1` opts into color in a terminal unless `--no-color` is set.
Human list tables show useful columns for each resource and keep full identifiers. Optional columns drop as the
terminal narrows; very narrow terminals and pipes use tab-separated rows. Human detail responses use readable,
indented JSON with local timestamps unless `--utc` is selected. Agent JSON retains the API's original timestamp
precision and values. Command-argument errors also use the JSON envelope when `--json` is present and exit with code 2.

On an interactive terminal, `runs wait` shows one transient status line on stderr. It uses the run's actual
document-item counts and stage; a single-document run stays a spinner until that item finishes. A completed human
wait prints the status, item and review counts, and an appropriate next command. `--json` still returns the full,
unchanged results manifest as one object. Without a terminal, human wait logs only changed states instead of
repeating every poll. Upload and export show byte-transfer progress on interactive stderr, labeled as sending or
receiving; those bytes do not indicate OCR or extraction progress. If an export omits a trustworthy content length,
the CLI shows bytes received without a percentage. No animation appears in `--json` or redirected output. These
displays use terminal-default foreground/background colors so they remain readable with dark or light themes.

| Exit | Meaning |
| ---: | --- |
| 0 | Success |
| 2 | CLI usage or argument error |
| 3 | API validation, conflict, or partial upload rejection |
| 4 | Authentication or permission failure |
| 5 | Resource not found |
| 6 | API server or response failure |
| 7 | Request or polling timeout; a submitted operation may still be running |
| 8 | Network/transport failure; retry only when the operation's idempotency contract allows it |

API errors include the stable error code and trace ID when supplied. `--debug` adds sanitized API details; it never
prints request headers or credentials. On a partial upload failure, accepted documents, reused IDs, and rejected
file reasons appear in the human error output; the same details remain in the JSON `data` property even though the
command returns exit code 3.

The root `--request-timeout` controls each network request. `runs wait --timeout` separately controls how long the
CLI polls, so an HTTP timeout cannot silently extend the overall wait period. For exports, no-clobber mode publishes
the completed temporary file atomically; `--force` replaces an existing destination.

## Command reference

The listed command names are checked against the Typer command tree by the CLI tests. Backend
authorization remains authoritative for each API operation.

| Command | API operation | Typical permission |
| --- | --- | --- |
| `docai health` | `GET /health/ready/` | Public readiness |
| `docai auth status` | `GET /api/v1/me/` | Any DocAI role |
| `docai projects list` | `GET /api/v1/projects/` | Any DocAI role |
| `docai datasets list` | `GET /api/v1/datasets/` | Any DocAI role |
| `docai workflows list` | `GET /api/v1/workflows/` | Any DocAI role |
| `docai workflows contract UUID` | `GET /api/v1/workflows/{id}/contract/` | Authorized content reader |
| `docai documents list` | `GET /api/v1/documents/` | Any DocAI role; values may be masked |
| `docai documents upload` | `POST /api/v1/datasets/{id}/upload/` | Operator |
| `docai runs submit` | `POST /api/v1/workflows/{id}/invoke/` | Operator |
| `docai runs list/show/progress` | Run GET resources | Any DocAI role; content remains role-controlled |
| `docai runs wait` | `GET /api/v1/runs/{id}/results/` | Reviewer, operator, or approver |
| `docai runs cancel/retry` | Run action POSTs | Operator |
| `docai runs export` | `GET /api/v1/runs/{id}/export/{format}/` | Content reader |
| `docai review list` | `GET /api/v1/fields/?review_status=needs_review` | Content reader |

The server remains authoritative for roles and dataset/project access. This is a curated subset, not a generated
OpenAPI-to-command mirror. See [`INTEGRATION.md`](INTEGRATION.md) for the full API contract and retry semantics.
