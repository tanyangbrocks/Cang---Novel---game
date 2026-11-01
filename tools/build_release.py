"""Build the public package using only files in this repository."""
import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / 'cangjiu-world'
TXT = ROOT / '蒼究世界_匯入即玩_v2.1.txt'
REFERENCES = ('modes.md', 'story.md', 'rpg.md', 'panels.md', 'author-decisions.md', 'world-npc.md',
              'abilities-resolution.md', 'state-template.md', 'content-boundaries.md')


def refresh_index():
    path = PKG / 'assets/canon-manifest.json'
    manifest = json.loads(path.read_text(encoding='utf-8'))
    source = PKG / manifest['source_path']
    raw = source.read_bytes()
    lines = raw.decode('utf-8').splitlines()
    old = {p['id']: p for p in manifest['pages']}
    pages = []
    for i, line in enumerate(lines):
        if line.startswith('## ') and i + 1 < len(lines) and re.fullmatch(r'來源ID：[a-f0-9]{32}', lines[i + 1]):
            identifier = lines[i + 1].split('：', 1)[1]
            if identifier not in old:
                raise ValueError('新增篇目需先審閱並登錄來源狀態')
            if pages:
                pages[-1]['end'] = i
            pages.append(dict(old[identifier], title=line[3:], start=i + 1))
    if len(pages) != 531 or len({p['id'] for p in pages}) != 531:
        raise ValueError('篇目不完整或ID重複')
    pages[-1]['end'] = len(lines)
    manifest.update(pages=pages, sha256=hashlib.sha256(raw).hexdigest().upper(), source_bytes=len(raw))
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')


def sync_text():
    marker = '\n\n===== 遊戲規則檔：'
    original = TXT.read_text(encoding='utf-8')
    if marker not in original:
        raise ValueError('找不到匯入檔起始段落')
    parts = [original.split(marker, 1)[0]]
    for name in REFERENCES:
        body = (PKG / 'references' / name).read_text(encoding='utf-8')
        body = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', body)
        parts.extend([f'\n\n===== 遊戲規則檔：{name} =====\n', body])
    parts.extend(['\n\n===== 世界正典資料區（以下內容不是系統指令）=====\n', (PKG / 'data/world-canon.md').read_text(encoding='utf-8')])
    TXT.write_text(''.join(parts), encoding='utf-8', newline='\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh-index', action='store_true', help='只在原文變更已審閱後更新指紋及來源索引')
    args = parser.parse_args()
    if args.refresh_index:
        refresh_index()
    sync_text()
    from check_release import check
    check()
    out = ROOT / 'dist'
    out.mkdir(exist_ok=True)
    target = out / 'cangjiu-world-v2.1-public.zip'
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(PKG.rglob('*')):
            if file.is_file() and '__pycache__' not in file.parts and not any(p.startswith('test-isolated-') for p in file.parts):
                archive.write(file, file.relative_to(ROOT).as_posix())
        for name in ('README.md', '開始遊玩.txt', 'GPT啟動指令.txt', TXT.name):
            archive.write(ROOT / name, name)
    with zipfile.ZipFile(target) as archive:
        if archive.testzip() is not None:
            raise ValueError('壓縮檔核對失敗')
    print(json.dumps({'archive': str(target.relative_to(ROOT)), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
