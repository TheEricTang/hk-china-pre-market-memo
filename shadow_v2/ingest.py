"""Import explicitly supplied public archive history without embeddings or inferred feedback."""
import argparse
import os
import re
from contextlib import nullcontext
from pathlib import Path
from .models import parse_edition
from .store import Store
from .paths import private_path
from .supabase_store import SupabaseStore


def edition_limit(value):
    value = int(value)
    if not 1 <= value <= 1000:
        raise argparse.ArgumentTypeError('max-editions must be between 1 and 1000')
    return value


def selected_editions(archive, max_editions, source_version=''):
    """Newest N filenames, registered oldest first; no publication/adoption inference."""
    if not archive.is_dir():
        raise ValueError('public archive directory does not exist')
    paths = sorted(path for path in archive.glob('memo-????-??-??.md')
                   if re.fullmatch(r'memo-\d{4}-\d{2}-\d{2}\.md', path.name))[-max_editions:]
    editions = []
    # Validate the whole selected batch before issuing any backend writes.
    for path in paths:
        with path.open('rb') as source:
            content = source.read(2_000_001)
        if len(content) > 2_000_000:
            raise ValueError('archive edition exceeds size limit')
        edition = parse_edition(content.decode('utf-8'), path.stem.removeprefix('memo-'), source_version)
        if not edition['items']:
            raise ValueError('archive edition has no items')
        editions.append(edition)
    return editions


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--public-archive', required=True, type=Path)
    backend = p.add_mutually_exclusive_group(required=True)
    backend.add_argument('--store', type=Path, help='private SQLite path outside the public repository')
    backend.add_argument('--cloud', action='store_true', help='dedicated V2_BACKEND_URL using scoped V2_CI_TOKEN')
    p.add_argument('--max-editions', type=edition_limit, default=100,
                   help='import newest N dated files, oldest first (1..1000; default 100)')
    p.add_argument('--source-version', default='')
    args = p.parse_args()
    archive = args.public_archive.expanduser().resolve()
    destination = None
    if args.store is not None:
        destination = private_path(args.store)
        if archive == destination or archive in destination.parents:
            p.error('private store must be outside public archive')
    editions = selected_editions(archive, args.max_editions, args.source_version)
    context = (nullcontext(SupabaseStore(os.environ['V2_BACKEND_URL'], os.environ['V2_CI_TOKEN']))
               if args.cloud else Store(str(destination)))
    with context as store:
        for edition in editions:
            store.register_edition(edition)
    print(f'Imported {len(editions)} public archive editions; no embeddings or feedback created. '
          'Archive dates do not verify publication timing or adoption.')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('Public archive import failed; inspect private inputs/backend configuration. Safe to retry completed editions.')
        raise SystemExit(2)
