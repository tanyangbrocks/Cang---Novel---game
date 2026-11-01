"""Read-only, fingerprint-checked canon lookup by original page ID."""
import argparse
import hashlib
import json
import re
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('search', 'read', 'verify'))
    parser.add_argument('query', nargs='?', default='')
    parser.add_argument('--source', type=Path)
    parser.add_argument('--offset', type=int, default=0)
    parser.add_argument('--limit', type=int, default=100)
    args = parser.parse_args()
    manifest = json.loads((PACKAGE / 'assets/canon-manifest.json').read_text(encoding='utf-8-sig'))
    source = args.source or (PACKAGE / manifest['source_path'])
    raw = source.read_bytes()
    if hashlib.sha256(raw).hexdigest().upper() != manifest['sha256']:
        raise ValueError('正典來源已變更，請核對版本並重建索引，不使用過期行號')
    lines = raw.decode('utf-8-sig').splitlines()
    if args.command == 'verify':
        result = {'valid': True, 'pages': len(manifest['pages']), 'lines': len(lines), 'source': str(source)}
    else:
        query = args.query.strip()
        if not query:
            raise ValueError('請指定關鍵字或來源ID')
        hits = []
        for page in manifest['pages']:
            if page['status'] == 'disabled':
                continue
            text = '\n'.join(lines[page['start'] - 1:page['end']])
            if query.lower() in text.lower() or query == page['id']:
                hits.append(page)
        if args.command == 'search':
            result = {'matches': hits, 'note': '標題及內容搜尋；適用前須讀作者裁定，不憑命中片段判定'}
        else:
            exact = [p for p in hits if p['id'] == query or p['title'] == query]
            if len(exact) != 1:
                raise ValueError('read需唯一來源ID或唯一完整篇名；停用篇目不供使用')
            page = exact[0]
            if not 1 <= args.limit <= 200 or args.offset < 0:
                raise ValueError('limit限1～200，offset須非負')
            a = min(page['end'], page['start'] - 1 + args.offset)
            b = min(page['end'], a + args.limit)
            exclusions = manifest.get('excluded_ranges', [])
            output = []
            for i in range(a, b):
                if any(r['start'] <= i + 1 <= r['end'] for r in exclusions):
                    output.append(f'{i + 1}: [此處依作者裁定／最小內容界線不採用，原文保留]')
                else:
                    output.append(f'{i + 1}: {lines[i]}')
            result = {'page': page, 'lines': output, 'next_offset': b - page['start'] + 1 if b < page['end'] else None,
                      'decisions': 'references/author-decisions.md'}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False))
        raise SystemExit(1)
