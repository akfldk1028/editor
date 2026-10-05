# Native backend environment

Use Python 3.11 or newer and create an isolated environment in the Editor repository.
The backend dependencies, including AutoGen model providers and MCP, are declared
in `pyproject.toml`.

Windows PowerShell, from the repository root:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e .
.venv/Scripts/python.exe -m pip check
```

On macOS/Linux use `.venv/bin/python` for the last two commands.

If this installation already uses the Graph2Plan reference model, its inference
dependencies are also required to preserve that function:

```powershell
.venv/Scripts/python.exe -m pip install -e ".[design-reference-models]"
```

This installs the Python inference dependencies. It does not replace or download
the existing model artifact in `runtime/editor/design/reference-models/graph2plan`.

The native development launcher selects `EDITOR_PYTHON` when explicitly configured,
otherwise the repository's `.venv/Scripts/python.exe` on Windows or `.venv/bin/python`
on other platforms. It falls back to `python` only when the local interpreter does
not exist. An existing environment still needs the dependency installation above.
Shared agents retain their own environments and service lifecycle.

Model-provider imports establish dependency readiness. Real model calls additionally
need the provider's configured credentials and service availability. Keep credentials
in the process environment or private configuration, never in committed templates.
