"""Initialize the isolated design ORM inside the Editor process."""
from __future__ import annotations

import os
import secrets
import threading

from filelock import FileLock

_lock = threading.Lock()
_ready = False


def ensure_design_runtime():
    global _ready
    with _lock:
        if _ready:
            return
        import django
        from django.conf import settings
        from django.core.management import call_command
        from backend.app.modules.design.generation.paths import data_root, backend_root

        directory = data_root()
        directory.mkdir(parents=True, exist_ok=True)
        database = os.environ.get('EDITOR_DESIGN_DATABASE', str(directory / 'execution.sqlite3'))
        from pathlib import Path
        Path(database).parent.mkdir(parents=True, exist_ok=True)
        if not settings.configured:
            settings.configure(
                SECRET_KEY=secrets.token_hex(32), DEBUG=False, USE_TZ=True,
                ALLOWED_HOSTS=['localhost', '127.0.0.1', 'testserver'],
                INSTALLED_APPS=['backend.app.adapters.design_storage.apps.DesignConfig'],
                DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': database,
                                      'OPTIONS': {'timeout': 30}}},
                DEFAULT_AUTO_FIELD='django.db.models.BigAutoField',
                ROOT_URLCONF='backend.app.api.design_runtime.urls',
                BASE_DIR=backend_root(),
                MAAS_SINGLE_EXECUTION_ROOT=directory / 'single-executions',
                MAAS_CREATIVE_PORTFOLIO_ROOT=directory / 'creative-portfolios',
                MAAS_PORTFOLIO_EVALUATION_ROOT=directory / 'portfolio-evaluations',
            )
        django.setup()
        from django.apps import apps
        if apps.get_app_config('design').name != 'backend.app.adapters.design_storage':
            raise RuntimeError('Design ORM is configured for a different application')
        active = settings.DATABASES['default']
        if active['ENGINE'] != 'django.db.backends.sqlite3' or Path(active['NAME']).resolve() != Path(database).resolve():
            raise RuntimeError('Design ORM is configured for a different database')
        # Several request threads/processes may encounter the first request together.
        with FileLock(str(database) + '.migrate.lock', timeout=60):
            call_command('migrate', 'design', interactive=False, verbosity=0)
        _ready = True
