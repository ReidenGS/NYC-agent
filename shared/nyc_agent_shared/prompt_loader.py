from __future__ import annotations

from functools import lru_cache
from pathlib import Path


def _prompt_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / 'prompts'
        if candidate.exists():
            return candidate
    return Path.cwd() / 'shared' / 'prompts'


@lru_cache(maxsize=128)
def load_prompt(name: str) -> str:
    safe = name.strip().strip('/')
    path = _prompt_root() / safe
    if not path.is_file():
        raise FileNotFoundError(f'prompt not found: {safe}')
    return path.read_text(encoding='utf-8')


def list_prompts() -> list[str]:
    root = _prompt_root()
    if not root.exists():
        return []
    return sorted(str(p.relative_to(root)) for p in root.rglob('*.txt'))
