# DocAI CLI

This package is an HTTP-only client for DocAI. It does not import Django or connect to the application database.
See the repository [CLI guide](../CLI.md) for authentication, shell setup, command examples, exit codes, and the
API boundary. The executable is named `docai`.

From this checkout, the repeatable project-scoped form is:

```bash
uv run --project cli docai --help
```

To make `docai` available directly in zsh or bash, install this checkout as an editable uv tool and add uv's tool
executable directory to `PATH`:

```bash
uv tool install --editable ./cli
uv tool update-shell
```

Start a new shell (or reload the relevant configuration), then verify `command -v docai` and `docai --help`.
