#!/usr/bin/env python3
"""Opt-in fixed v3 closure; v1/v2 artifacts and their historical hashes unchanged."""
import hashlib
from pathlib import Path

PINNED_SHA256 = {'host_capture_recipes.js': '1cdaa1666863524647f1fd8dcc5a3e88010429820067752c6bac331a8b14b64a', 'search_card_variant_v2.js': '88a192625c7d67115f2746f411adfeade878b5f377cb399813d8a670bd0143bb', 'search_card_scope_v3.js': 'a995cd995de75cebd851424443c74fc60e3079edc2686ab1fac8523357c07e3a', 'host_capture_recipes_v3.js': '659086195a5d5646046db1332e285c7dda8127301a43fb0bb64591e1ea8a7967'}


def compose():
    root = Path(__file__).resolve().parent
    sources = []
    for name, expected in PINNED_SHA256.items():
        raw = (root / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('capture_recipe_hash_mismatch')
        sources.append(raw.decode('utf-8'))
    return ('(args) => { const module = undefined; const require = undefined;\n'
            + '\n'.join(sources)
            + '\nreturn HOST_CAPTURE_RECIPES_V3.capture(args);\n}')


if __name__ == '__main__':
    print(compose())
