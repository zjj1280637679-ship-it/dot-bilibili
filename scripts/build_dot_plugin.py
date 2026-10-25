#!/usr/bin/env python3
"""Build the public, skill-only upload archive; never package a repository tree."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MEMBERS = ('plugin.json', 'skills/bilibili/SKILL.md')
MAX_ARCHIVE_BYTES = 100_000_000


def validate(source):
    source = Path(source)
    if source.is_symlink() or not source.is_dir():
        raise ValueError('plugin source must be a real directory')
    found = set()
    for path in source.rglob('*'):
        if path.is_symlink():
            raise ValueError('symlinks are forbidden')
        if path.is_file():
            found.add(path.relative_to(source).as_posix())
        elif not path.is_dir():
            raise ValueError('special files are forbidden')
    if found != set(MEMBERS):
        raise ValueError('plugin must contain exactly the public allowlisted files')
    payload = {name: (source / name).read_bytes() for name in MEMBERS}
    if any(len(data) > 100_000 for data in payload.values()):
        raise ValueError('unexpectedly large plugin source')
    manifest = json.loads(payload['plugin.json'])
    if set(manifest) != {'$schema', 'name', 'version', 'description'}:
        raise ValueError('unexpected manifest fields: no native tools, MCP or hooks')
    if (manifest['$schema'] != 'https://agent-plugins.org/schemas/1.0.0/plugin.schema.json'
            or manifest['name'] != 'dot-bilibili'
            or not re.fullmatch(r'\d+\.\d+\.\d+', manifest['version'])
            or not isinstance(manifest['description'], str) or not manifest['description']):
        raise ValueError('invalid portable manifest')
    skill = payload[MEMBERS[1]].decode('utf-8')
    if not re.match(r'\A---\nname: bilibili\ndescription: [^\n]+\n---\n', skill):
        raise ValueError('invalid skill frontmatter')
    # Leak tripwires are additional checks, not a substitute for source review.
    all_text = '\n'.join(data.decode('utf-8') for data in payload.values())
    # Public standard locator is a convention, never actual binding contents.
    all_text = all_text.replace('/workspace/shared/dot-bilibili/host-binding.json', '')
    for pattern in (r'/workspace/', r'/home/', r'SESSDATA\s*[=:]',
                    r'bili_jct\s*[=:]', r'-----BEGIN .*PRIVATE KEY',
                    r'fr-[0-9a-f]{64}', r'"(?:account_id|access_token|password)"\s*:'):
        if re.search(pattern, all_text, re.I):
            raise ValueError('potential private material in public package')
    return payload


def build(source, output):
    payload = validate(source)
    output = Path(output)
    if output.resolve().is_relative_to(Path(source).resolve()):
        raise ValueError('archive must be outside plugin source')
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in MEMBERS:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, payload[name], compresslevel=9)
    if output.stat().st_size >= MAX_ARCHIVE_BYTES:
        output.unlink()
        raise ValueError('archive exceeds upload limit')
    return {'archive': str(output.resolve()), 'bytes': output.stat().st_size,
            'sha256': hashlib.sha256(output.read_bytes()).hexdigest(), 'members': list(MEMBERS)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'plugin')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/dot-bilibili-plugin.zip')
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.output), indent=2))


if __name__ == '__main__':
    main()
