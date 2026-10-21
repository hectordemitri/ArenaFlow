import hashlib
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
from contextlib import closing

from django.conf import settings
from django.core.files import File
from django.core.files.storage import storages
from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.utils import timezone


class Command(BaseCommand):
    help = 'Cria backup consistente; --upload usa o storage privado de backups.'

    def add_arguments(self, parser):
        parser.add_argument('--output', help='Novo arquivo local (nunca sobrescreve).')
        parser.add_argument('--upload', action='store_true')

    def handle(self, *args, **options):
        if not options['output'] and not options['upload']:
            raise CommandError('Informe --output ou --upload.')
        db = connections['default'].settings_dict
        name = f"database-{timezone.now():%Y%m%dT%H%M%S%f}.backup"
        with tempfile.TemporaryDirectory(prefix='arenaflow-backup-') as temporary:
            output = Path(options['output']).resolve() if options['output'] else Path(temporary) / name
            output.parent.mkdir(parents=True, exist_ok=True)
            if output.exists():
                raise CommandError('O arquivo de destino ja existe.')
            if db['ENGINE'].endswith('sqlite3'):
                with closing(sqlite3.connect(db['NAME'])) as source, closing(sqlite3.connect(output)) as target:
                    source.backup(target)
                    target.commit()
                    if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise CommandError('Backup SQLite nao passou na verificacao.')
            elif db['ENGINE'].endswith('postgresql'):
                env = {**os.environ, 'PGHOST': db.get('HOST') or '', 'PGPORT': str(db.get('PORT') or '5432'),
                       'PGUSER': db.get('USER') or '', 'PGPASSWORD': db.get('PASSWORD') or '',
                       'PGDATABASE': db['NAME'], 'PGSSLMODE': db.get('OPTIONS', {}).get('sslmode', 'prefer')}
                try:
                    subprocess.run(['pg_dump', '--format=custom', '--no-owner', '--no-acl', '--file', str(output)],
                                   env=env, check=True, capture_output=True, timeout=600)
                except (OSError, subprocess.SubprocessError) as exc:
                    raise CommandError('pg_dump falhou. Verifique o cliente PostgreSQL e a conexao do backup.') from exc
            else:
                raise CommandError('Banco nao suportado.')
            with output.open('rb') as handle:
                checksum = hashlib.file_digest(handle, 'sha256').hexdigest()
            if options['upload']:
                if not settings.BACKUP_STORAGE_BUCKET:
                    raise CommandError('Configure BACKUP_STORAGE_BUCKET antes do upload.')
                with output.open('rb') as handle:
                    stored = storages['backups'].save(f'database/{name}', File(handle))
                self.stdout.write(f'Backup privado: {stored}; sha256={checksum}')
            else:
                self.stdout.write(f'Backup criado: {output}; sha256={checksum}')
