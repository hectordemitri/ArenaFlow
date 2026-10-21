from io import StringIO
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from arenasystem.checks import production_readiness


class BackupAndDeploymentTests(SimpleTestCase):
    def test_sqlite_backup_restores_data_and_never_overwrites_destination(self):
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder) / 'source.sqlite3', Path(folder) / 'backup.sqlite3'
            with closing(sqlite3.connect(source)) as db:
                db.execute('CREATE TABLE arena (id integer, nome text)')
                db.execute("INSERT INTO arena VALUES (1, 'Arena A')")
                db.commit()
            database = SimpleNamespace(settings_dict={'ENGINE': 'django.db.backends.sqlite3', 'NAME': str(source)})
            with patch('saas_ops.management.commands.backup_database.connections', {'default': database}):
                call_command('backup_database', output=str(target), stdout=StringIO())
                with self.assertRaises(CommandError):
                    call_command('backup_database', output=str(target), stdout=StringIO())
            with closing(sqlite3.connect(target)) as restored:
                self.assertEqual(restored.execute('SELECT nome FROM arena').fetchone()[0], 'Arena A')
                self.assertEqual(restored.execute('PRAGMA integrity_check').fetchone()[0], 'ok')

    @override_settings(DEBUG=False, APP_ENCRYPTION_KEYS=[], CACHE_REDIS_URL='', MEDIA_STORAGE_BUCKET='',
                       DEMO_MODE=True, SUPERADMIN_REQUIRE_MFA=False)
    def test_production_check_rejects_incomplete_environment(self):
        ids = {issue.id for issue in production_readiness(None)}
        self.assertTrue({'arenaflow.E001', 'arenaflow.E002', 'arenaflow.E003', 'arenaflow.E004', 'arenaflow.E005'} <= ids)
