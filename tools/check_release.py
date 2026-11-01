"""Check portable source integrity, links and private-path exclusions."""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / 'cangjiu-world'


def check():
    manifest = json.loads((PKG / 'assets/canon-manifest.json').read_text(encoding='utf-8'))
    if Path(manifest['source_path']).is_absolute():
        raise ValueError('正典來源不能依賴絕對路徑')
    source = (PKG / manifest['source_path']).resolve()
    if not source.is_relative_to(PKG.resolve()):
        raise ValueError('正典來源離開套件目錄')
    raw = source.read_bytes()
    if hashlib.sha256(raw).hexdigest().upper() != manifest['sha256']:
        raise ValueError('正典指紋不符，請先審閱變更再refresh-index')
    if len(manifest['pages']) != 531 or len({p['id'] for p in manifest['pages']}) != 531:
        raise ValueError('531篇來源索引不完整')
    for file in ROOT.rglob('*'):
        if not file.is_file() or file.suffix not in ('.txt', '.md', '.json', '.py', '.yaml', '.yml'):
            continue
        if any(p in ('.git', 'dist', 'campaigns', '__pycache__') or p.startswith('test-isolated-') for p in file.relative_to(ROOT).parts):
            continue
        text = file.read_text(encoding='utf-8-sig')
        if re.search(r'(?<![A-Za-z])[A-Za-z]:[\\/]', text):
            raise ValueError(f'含本機絕對路徑：{file.relative_to(ROOT)}')
        if file.suffix == '.md':
            for link in re.findall(r'\]\(([^)]+)\)', text):
                if link.startswith(('https://', 'http://', '#')):
                    continue
                if not (file.parent / link.split('#')[0]).is_file():
                    raise ValueError(f'連結不存在：{file.relative_to(ROOT)} -> {link}')
    txt = (ROOT / '蒼究世界_匯入即玩_v2.1.txt').read_text(encoding='utf-8')
    if not txt.endswith(raw.decode('utf-8')):
        raise ValueError('文字匯入檔與目前正典不同步')
    for required in ('沉浸式故事冒險', '沉浸式命運RPG', '極黏唾液（22%）', 'No.180'):
        if required not in txt:
            raise ValueError(f'匯入檔缺少必要內容：{required}')
    return {'valid': True, 'pages': 531, 'portable': True}


if __name__ == '__main__':
    print(json.dumps(check(), ensure_ascii=False))
