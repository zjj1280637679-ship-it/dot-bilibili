#!/usr/bin/env python3
"""Offline fixed-source composition; emits one self-contained DOM function.

No browser access. No input code, filenames, selectors, or runtime authority.
The trusted host passes only {kind, limit} to the resulting evaluation function.
"""
import hashlib
from pathlib import Path

PINNED_SHA256 = {'host_capture_recipes.js': '1cdaa1666863524647f1fd8dcc5a3e88010429820067752c6bac331a8b14b64a', 'search_card_variant_v2.js': '88a192625c7d67115f2746f411adfeade878b5f377cb399813d8a670bd0143bb', 'host_capture_recipes_v2.js': '17325b7e0d8687b93354c56dc0457aba6c3d1cf776766c8d919581bb5dafd422'}


def compose():
    root = Path(__file__).resolve().parent
    sources = []
    for name, expected in PINNED_SHA256.items():
        raw = (root / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('capture_recipe_hash_mismatch')
        sources.append(raw.decode('utf-8'))
    # Shadow CommonJS names locally: fixed source exports cannot mutate globals.
    return ('(args) => { const module = undefined; const require = undefined;\n'
            + '\n'.join(sources)
            + '\nreturn HOST_CAPTURE_RECIPES_V2.capture(args);\n}')


if __name__ == '__main__':
    print(compose())
