"""Explicit local snapshot, restore and retention simulation operations."""
import json
import sqlite3
import sys
from pathlib import Path

from .automation_cli import _private_home
from .storage import backup_bundle, verify_bundle, restore_bundle, inventory
from .workflow_contracts import WorkflowError


def add_storage_parsers(sub):
    commands = sub.add_parser('storage', help='Private whole-store backup and non-destructive diagnostics').add_subparsers(dest='storage_command', required=True)
    backup = commands.add_parser('backup')
    backup.add_argument('--output', type=Path, required=True)
    backup.add_argument('--config', type=Path)
    verify = commands.add_parser('verify-backup')
    verify.add_argument('directory', type=Path)
    restore = commands.add_parser('restore')
    restore.add_argument('--source', type=Path, required=True)
    restore.add_argument('--output', type=Path, required=True)
    diagnose = commands.add_parser('inventory')
    diagnose.add_argument('--retention-days', type=int, default=90)
    diagnose.add_argument('--keep-backups', type=int, default=7)


def dispatch_storage(args):
    try:
        if args.storage_command == 'backup':
            manifest = backup_bundle(_private_home(), args.output, config=args.config)
            result = {'verified': True, 'files': len(manifest['files']),
                      'created_at': manifest['created_at'], 'submitted': False}
        elif args.storage_command == 'verify-backup':
            manifest = verify_bundle(args.directory)
            result = {'verified': True, 'files': len(manifest['files']),
                      'created_at': manifest['created_at'], 'schema_version': manifest['schema_version']}
        elif args.storage_command == 'restore':
            result = restore_bundle(args.source, args.output)
        else:
            result = inventory(_private_home(), retention_days=args.retention_days,
                               keep_backups=args.keep_backups)
        print(json.dumps(result, ensure_ascii=True, allow_nan=False))
        return 0
    except WorkflowError as error:
        print(json.dumps({'event': 'storage_error', 'code': error.code}), file=sys.stderr)
        return 3 if error.code == 'run_locked' else 2
    except (OSError, ValueError, TypeError, sqlite3.Error):
        print(json.dumps({'event': 'storage_error', 'code': 'storage_operation_failed'}), file=sys.stderr)
        return 2
