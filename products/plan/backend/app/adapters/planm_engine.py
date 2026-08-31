"""Thin process host for the Backend-owned PLANM execution service."""

from backend.app.modules.planm_execution.service import main


if __name__ == "__main__":
    raise SystemExit(main())
