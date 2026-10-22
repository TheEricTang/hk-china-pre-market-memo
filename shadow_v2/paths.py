"""All experimental private state lives outside this public repository."""
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]


def private_path(value: str | Path) -> Path:
    path = Path(value).expanduser().resolve()
    if path == REPOSITORY or REPOSITORY in path.parents:
        raise ValueError('Private state must be outside the public repository')
    return path


def private_directory(value: str | Path) -> Path:
    path = private_path(value)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path
