"""Local text-RPG state, auditable D100 and atomic saves. Python 3.10+, stdlib only."""
import argparse
import copy
import hashlib
import json
import math
import os
import re
import secrets
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import time_rules

VERSION = '2.0'
RULES_VERSION = '2.2'
ATTRS = ('顏值', '智力', '體質', '力量', '敏捷', '感知', '意志', '魅力')
SKILLS = ('觀察', '交涉', '潛行', '野外求生', '閱讀演算', '急救', '武器基礎', '工藝')
DEFAULT_ROOT = Path(__file__).resolve().parents[2] / 'campaigns'
MANIFEST = Path(__file__).resolve().parents[1] / 'assets/canon-manifest.json'


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(x):
    return type(x) in (int, float) and math.isfinite(x)


def whole(x):
    return type(x) is int


def half_up(x):
    return math.floor(x + 0.5)


def probability(a, difficulty, rank=0, required_rank=0, context=0, luck=10):
    require(all(number(v) for v in (a, difficulty, luck)), '屬性、難度與運氣須為有限數字')
    require(a > 0 and difficulty > 0, '屬性及難度須大於0')
    require(whole(rank) and whole(required_rank) and rank >= 0 and required_rank >= 0, '技能級須為非負整數')
    require(whole(context) and context in (-20, -10, 0, 10, 20), '情境須為-20/-10/0/10/20')
    bonus = max(-5, min(5, (luck - 10) / 2))
    return max(5, min(95, half_up(50 + 20 * math.log2(a / difficulty) + 5 * (rank - required_rank) + context + bonus)))


def resolve(p, roll):
    require(whole(roll) and 1 <= roll <= 100, 'D100範圍錯誤')
    if roll <= p:
        return '出色成功' if p - roll >= 30 else '成功'
    return '明顯失敗' if roll - p >= 30 else '失敗'


def save_path(root, campaign):
    require(bool(re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', campaign)), '存檔ID僅用小寫英數、底線或連字號')
    return Path(root) / campaign / 'state.json'


@contextmanager
def locked(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix('.lock')
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ValueError('存檔正被另一操作使用；若程序中斷，先核對存檔再處理殘留lock')
    try:
        os.close(fd)
        yield
    finally:
        lock.unlink(missing_ok=True)


def atomic(path, state):
    verify(state)
    temp = path.with_suffix('.tmp')
    try:
        with temp.open('w', encoding='utf-8', newline='\n') as f:
            json.dump(state, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        if path.exists():
            backup = path.parent / 'history' / f'revision-{state["revision"] - 1:06d}.json'
            backup.parent.mkdir(exist_ok=True)
            if not backup.exists():
                with backup.open('xb') as f:
                    f.write(path.read_bytes())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def load(path):
    state = json.loads(path.read_text(encoding='utf-8-sig'))
    verify(state)
    return state


def validate_snapshot(s):
    require(s['mode'] in ('story', 'rpg'), '未知模式')
    require(s['phase'] in ('creation', 'playing'), '未知階段')
    require(whole(s['world_seconds']) and s['world_seconds'] >= 0, '世界時間錯誤')
    require(isinstance(s['scene'], dict) and isinstance(s['scene'].get('location'), str), '缺場景位置')
    require(isinstance(s['scene'].get('summary'), str), '缺場景摘要')
    require(isinstance(s['scene'].get('choices', []), list) and len(s['scene'].get('choices', [])) <= 4, '選項最多4項')
    require(all(isinstance(c, str) and c.strip() for c in s['scene'].get('choices', [])), '選項須有具體內容')
    require('player' in s['entities'], '缺玩家角色')
    for entity in s['entities'].values():
        require(entity['life'] in ('alive', 'dying', 'dead', 'missing', 'unknown'), '存亡值錯誤')
        hp = entity.get('hp')
        if hp is not None:
            require(all(number(hp.get(k)) for k in ('current', 'max')) and hp['max'] > 0 and 0 <= hp['current'] <= hp['max'], 'HP範圍錯誤')
        require(all(number(v) and v > 0 for v in entity.get('attributes', {}).values()), '屬性須大於0')
        require(all(whole(v) and v >= 0 for v in entity.get('skills', {}).values()), '技能級錯誤')
        require(all(number(entity.get(k, 0)) and entity.get(k, 0) >= 0 for k in ('cash',)), '現金不可負值')
        for pool in entity.get('energies', {}).values():
            if pool.get('current') is not None:
                require(number(pool['current']) and number(pool.get('max')) and 0 <= pool['current'] <= pool['max'], 'MP範圍錯誤')
    for item in s['items'].values():
        require(whole(item['quantity']) and item['quantity'] >= 0, '物品數量錯誤')
        require(item['owner'] in s['entities'] or item['owner'] == 'world', '物品持有者不存在')
    if s['phase'] == 'playing':
        require(s['scene']['location'] == s['entities']['player']['location'], '場景與玩家位置不一致')
    if s.get('rpg_time') is not None:
        require(s['mode'] == 'rpg' and s['phase'] == 'playing', '故事模式或創角階段不能套用RPG行動點')
        time_rules.validate(s['rpg_time'], s['world_seconds'])


def verify(state):
    require(state.get('schema_version') == VERSION, '不支援的存檔格式')
    snapshot = copy.deepcopy(state['initial'])
    previous = '0' * 64
    checks = {}
    ids = set()
    for seq, event in enumerate(state['events'], 1):
        require(event['seq'] == seq and event['previous_hash'] == previous, '事件序列斷裂')
        require(event['id'] not in ids, '重複事件ID')
        ids.add(event['id'])
        unsigned = {k: v for k, v in event.items() if k != 'hash'}
        require(digest(unsigned) == event['hash'], '事件指紋不符')
        if event['kind'] == 'check':
            result = event['result']
            params = event['input']
            p = probability(params['attribute'], params['difficulty'], params.get('rank', 0), params.get('required_rank', 0), params.get('context', 0), params.get('luck', 10))
            require(result['probability'] == p and result['degree'] == resolve(p, result['roll']), '檢定紀錄不符')
            checks[event['id']] = result
        else:
            for key, value in event['changes'].items():
                snapshot[key] = copy.deepcopy(value)
        validate_snapshot(snapshot)
        previous = event['hash']
    require(state['revision'] == len(state['events']), '版本與事件數不符')
    require(state['snapshot'] == snapshot and state['checks'] == checks, '快照無法由事件重建')
    validate_snapshot(snapshot)
    return True


def append(state, event_id, kind, payload, changes=None, result=None):
    event = {'id': event_id, 'seq': state['revision'] + 1, 'previous_hash': state['events'][-1]['hash'] if state['events'] else '0' * 64,
             'kind': kind, 'input': copy.deepcopy(payload), 'changes': changes or {}}
    if result is not None:
        event['result'] = result
        state['checks'][event_id] = result
    event['hash'] = digest(event)
    state['events'].append(event)
    state['revision'] += 1
    state['snapshot'].update(copy.deepcopy(changes or {}))
    return event


def new_state(campaign, mode, name='未命名'):
    require(mode in ('story', 'rpg'), '模式需為story或rpg')
    player = {'name': name, 'species': '人族', 'life': 'alive', 'attributes': {}, 'skills': {}, 'hp': None,
              'cash': 0, 'luck': 10, 'injuries': [], 'effects': [], 'energies': {}, 'identity': '未定', 'titles': [], 'location': '未定',
              'age': None, 'affiliation': '未定', 'mental_state': '正常', 'fatigue': '正常', 'destiny': '未確認', 'combat_class': '未測定', 'abilities': [], 'assets': [], 'debts': []}
    snap = {'mode': mode, 'phase': 'creation', 'creation_profile': 'ordinary-human', 'world_seconds': 0,
            'scene': {'location': '尚未開局', 'summary': '等待創角與配點確認', 'choices': []}, 'entities': {'player': player},
            'items': {}, 'relations': {}, 'reputation': {}, 'additions': [], 'pending': [], 'used_checks': []}
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    return {'schema_version': VERSION, 'campaign_id': campaign, 'rules_version': RULES_VERSION, 'canon_sha256': manifest['sha256'], 'revision': 0,
            'initial': copy.deepcopy(snap), 'snapshot': snap, 'events': [], 'checks': {}}


def apply(state, command, data, roller=None):
    s = state['snapshot']
    event_id = data.get('event_id', '')
    require(isinstance(event_id, str) and event_id.strip(), '需要穩定event_id')
    identity = {k: v for k, v in data.items() if k != 'expected_revision'}
    for old in state['events']:
        if old['id'] == event_id:
            require(old['input'] == identity and old['kind'] == command, '同一事件ID的內容已變更')
            return {'replayed': True, 'event': old, 'revision': state['revision']}
    require(whole(data.get('expected_revision')) and data['expected_revision'] == state['revision'], '版本已變更；先重讀再提交')
    changes = {}
    result = None
    if command == 'build':
        require(s['phase'] == 'creation' and s['mode'] == 'rpg', '只有RPG創角階段可配點')
        attrs, skills = data['attributes'], data['skills']
        require(set(attrs) == set(ATTRS), '需提供完整八項屬性')
        require(all(whole(v) and 5 <= v <= 15 for v in attrs.values()) and sum(attrs.values()) == 80, '八項各5～15，總和80')
        require(set(skills) <= set(SKILLS) and all(whole(v) and 1 <= v <= 3 for v in skills.values()) and sum(skills.values()) == 6, '技能需用目錄項目，每項1～3級，總共6點')
        entities = copy.deepcopy(s['entities'])
        p = entities['player']
        p.update(attributes=attrs, skills=skills, hp={'current': attrs['體質'] * 10, 'max': attrs['體質'] * 10}, cash=1000)
        changes = {'entities': entities}
    elif command == 'finalize':
        require(s['phase'] == 'creation', '已完成創角')
        require(data.get('player_confirmed') is True, '需要玩家確認配點／角色')
        require(data.get('source_refs'), '開局位置與身分需有來源或明標新增')
        require(data['scene']['location'] != '尚未開局', '需要實際開局位置')
        entities = copy.deepcopy(s['entities'])
        if s['mode'] == 'rpg':
            require(len(entities['player']['attributes']) == 8, '先完成配點')
        entities['player']['location'] = data['scene']['location']
        entities['player']['identity'] = data.get('identity', '普通居民')
        changes = {'entities': entities, 'phase': 'playing', 'scene': data['scene']}
        if s['mode'] == 'rpg':
            changes['rpg_time'] = time_rules.initialize(entities['player'], s['world_seconds'], data.get('age_months'))
            changes['items'] = {key: {'name': name, 'quantity': qty, 'owner': 'player', 'location': '隨身', 'source': 'RPG開局方案2.0'} for key, name, qty in
                                [('clothes', '基本衣物', 1), ('bag', '背包', 1), ('food', '普通口糧（日份）', 7), ('water', '水壺', 1)]}
    elif command == 'check':
        require(s['phase'] == 'playing' and s['mode'] == 'rpg', '需先完成RPG開局')
        require(data.get('gate') == 'uncertain' and data.get('basis') and data.get('obstacle_id'), '先確認為可成可敗行動、依據及障礙ID')
        actor = s['entities'].get(data.get('actor_id', 'player'))
        require(actor and actor['life'] == 'alive', '行動者不能正常行動')
        require(not actor.get('hp') or actor['hp']['current'] > 0, 'HP0不能正常行動')
        require(not (set(state['checks']) - set(s['used_checks'])), '先結算或記錄放棄目前檢定，不能重新抽取')
        require(data.get('attribute_name') in actor['attributes'], '缺主屬性')
        require(data['attribute'] == actor['attributes'][data['attribute_name']], '主屬性與快照不一致')
        skill = data.get('skill_name')
        require(data.get('rank', 0) == actor['skills'].get(skill, 0), '技能與快照不一致')
        require(data.get('luck', 10) == actor.get('luck', 10), '運氣與快照不一致')
        p = probability(data['attribute'], data['difficulty'], data.get('rank', 0), data.get('required_rank', 0), data.get('context', 0), data.get('luck', 10))
        roll = roller() if roller else secrets.randbelow(100) + 1
        result = {'probability': p, 'roll': roll, 'degree': resolve(p, roll)}
    elif command == 'time':
        require(s['phase'] == 'playing' and s['mode'] == 'rpg', '時間安排只適用已開局RPG')
        require(not (set(state['checks']) - set(s['used_checks'])), '先結算未決檢定')
        require(data.get('source_refs'), '時間安排需來源或玩法依據')
        operation = data.get('operation')
        if operation == 'setup':
            require(s.get('rpg_time') is None, '既有月制不能重設以刷新行動點')
            require(data.get('player_confirmed') is True, '舊存檔啟用月制需玩家確認')
            changes['rpg_time'] = time_rules.initialize(s['entities']['player'], s['world_seconds'], data.get('age_months'))
        elif operation == 'end-unit':
            clock = s.get('rpg_time')
            require(clock and not clock['situations'] and not clock['activity'], '先結束情境或活動再月結')
            require(data.get('player_confirmed') is True and data.get('reason'), '跳至下月需玩家授權及事件核對')
            delta = clock['unit_seconds'] - clock['unit_elapsed']
            changes['world_seconds'] = s['world_seconds'] + delta
            changes['rpg_time'] = time_rules.advance(clock, s['world_seconds'], delta, s['entities']['player'], s['entities']['player'])
            changes['scene'] = dict(s['scene'], choices=[], summary=data.get('summary', '本時間單位已結束，等待安排下一個月。'))
        else:
            require(s.get('rpg_time') is not None, '舊存檔先setup以記錄月制基準')
            changes['rpg_time'] = time_rules.transition(s['rpg_time'], operation, data, s['world_seconds'], s['entities']['player'])
    elif command == 'commit':
        require(s['phase'] == 'playing' and data.get('reason') and data.get('source_refs'), '事件需開局、原因與來源')
        delta = data.get('elapsed_seconds', 0)
        require(whole(delta) and delta >= 0, '行動耗時需非負整數')
        require(data.get('actor_id', 'player') in s['entities'], '缺行動者')
        actor = s['entities'][data.get('actor_id', 'player')]
        require(actor['life'] == 'alive' or data.get('event_type') in ('revival', 'aftermath', 'correction'), '死亡或失蹤角色不能正常行動')
        used = list(s['used_checks'])
        check_id = data.get('check_id')
        if check_id:
            require(check_id in state['checks'] and check_id not in used, '檢定不存在或已結算')
            original = next(e for e in state['events'] if e['id'] == check_id)
            require(original['input'].get('actor_id', 'player') == data.get('actor_id', 'player'), '不能使用另一角色的檢定')
            used.append(check_id)
        entities = copy.deepcopy(s['entities'])
        for eid, patch in data.get('entities', {}).items():
            require(eid in entities, '新增NPC請透過new_entities並附來源')
            old = entities[eid]
            if old['life'] == 'dead' and patch.get('life', 'dead') != 'dead':
                require(data.get('event_type') == 'revival' and data.get('mechanism'), '復活需實際機制及事件')
            if patch.get('location', old.get('location')) != old.get('location'):
                require(data.get('event_type') in ('movement', 'revival', 'correction'), '位置變化需移動事件')
            require(set(patch) <= {'life', 'hp', 'cash', 'injuries', 'effects', 'location', 'attributes', 'skills', 'energies', 'identity', 'titles', 'luck',
                                   'age', 'affiliation', 'mental_state', 'fatigue', 'destiny', 'combat_class', 'abilities', 'assets', 'debts',
                                   'knowledge', 'goals', 'beliefs', 'public_claims', 'truth', 'background', 'personality', 'constraints', 'sources', 'growth_progress'}, '不支援的角色欄位')
            old.update(patch)
            if old.get('hp') and old['hp']['current'] == 0 and old['life'] == 'alive':
                old['life'] = 'dying'
        for eid, entity in data.get('new_entities', {}).items():
            require(eid not in entities and eid != 'player', '人物ID已存在')
            require(entity.get('source_refs'), '新人物需來源或新增設定標記')
            entities[eid] = entity
        changes = {'entities': entities, 'world_seconds': s['world_seconds'] + delta, 'used_checks': used}
        for key in ('items', 'relations', 'reputation', 'pending', 'additions'):
            if key in data:
                changes[key] = data[key]
        if 'scene' in data:
            require(data['scene']['location'] == entities['player'].get('location'), '場景位置與玩家不一致')
            changes['scene'] = data['scene']
        if s['mode'] == 'rpg' and s.get('rpg_time') is not None:
            clock = time_rules.advance(s['rpg_time'], s['world_seconds'], delta, s['entities']['player'], entities['player'])
            if data.get('time_transition'):
                action = data['time_transition']
                clock = time_rules.transition(clock, action.get('operation'), action, s['world_seconds'] + delta, entities['player'])
            changes['rpg_time'] = clock
        else:
            require(not data.get('time_transition'), '故事模式或未啟用月制不能提交RPG情境操作')
    else:
        raise ValueError('未知操作')
    trial = copy.deepcopy(s)
    trial.update(changes)
    validate_snapshot(trial)
    event = append(state, event_id, command, identity, changes, result)
    return {'revision': state['revision'], 'event': event}


def visible_panel(state, section='面板'):
    s = state['snapshot']
    p = s['entities']['player']
    public = {k: copy.deepcopy(p.get(k)) for k in ('name', 'species', 'age', 'affiliation', 'life', 'attributes', 'skills', 'hp', 'cash', 'luck', 'identity', 'injuries', 'effects', 'titles', 'location', 'mental_state', 'fatigue', 'destiny', 'combat_class')}
    public['energies'] = {k: {field: v.get(field, '未標定') for field in ('current', 'max', 'output', 'power', 'baseline', 'source_ref')} for k, v in p['energies'].items()}
    public['physical_defense'] = p['attributes']['體質'] / 2 if '體質' in p['attributes'] else '未標定'
    public['unarmed_output'] = p['attributes']['力量'] * 2 if '力量' in p['attributes'] else '未標定'
    public['energy_defense'] = '依能力卡與傷害通道查看'
    selected = {'物品': {k: {field: v.get(field) for field in ('name', 'quantity', 'owner', 'location', 'quality', 'status', 'public_description')} for k, v in s['items'].items() if v['owner'] == 'player'},
                '技能': {'ordinary': p['skills'], 'abilities': [a['public'] for a in p.get('abilities', []) if isinstance(a, dict) and 'public' in a]},
                '能力': public['energies'], '財富': {'cash': p['cash'], 'assets': p.get('assets', []), 'debts': p.get('debts', [])},
                '狀態': {k: public[k] for k in ('life', 'hp', 'injuries', 'effects', 'mental_state', 'fatigue')},
                '關係': {k: v['public'] for k, v in s['relations'].items() if isinstance(v, dict) and 'public' in v},
                '聲望': {k: v['public'] for k, v in s['reputation'].items() if isinstance(v, dict) and 'public' in v}}
    if section == '面板':
        content = public
    else:
        require(section in selected, '未知面板')
        content = copy.deepcopy(selected[section])
    result = {'mode': s['mode'], 'section': section, 'content': content, 'world_seconds': s['world_seconds'], 'current_scene': copy.deepcopy(s['scene'])}
    if s.get('rpg_time') is not None:
        result['rpg_time'] = time_rules.public_clock(s['rpg_time'])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('new', 'build', 'finalize', 'check', 'commit', 'time', 'panel', 'verify', 'export'))
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    parser.add_argument('--id', required=True)
    parser.add_argument('--data', type=Path, help='UTF-8 JSON操作檔，所有修改含event_id及expected_revision')
    parser.add_argument('--mode', choices=('story', 'rpg'))
    parser.add_argument('--name', default='未命名')
    parser.add_argument('--section', default='面板')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--audience', choices=('player', 'host'), default='player')
    args = parser.parse_args()
    path = save_path(args.root, args.id)
    if args.command == 'new':
        require(args.mode is not None, '先由玩家選模式')
        with locked(path):
            require(not path.exists(), '存檔已存在，不覆寫')
            state = new_state(args.id, args.mode, args.name)
            atomic(path, state)
        result = {'created': str(path), 'revision': 0, 'phase': 'creation'}
    elif args.command in ('build', 'finalize', 'check', 'commit', 'time'):
        require(args.data is not None, '需要--data JSON檔')
        data = json.loads(args.data.read_text(encoding='utf-8-sig'))
        with locked(path):
            state = load(path)
            result = apply(state, args.command, data)
            if not result.get('replayed'):
                atomic(path, state)
    else:
        state = load(path)
        if args.command == 'panel':
            result = visible_panel(state, args.section)
        elif args.command == 'verify':
            result = {'valid': True, 'revision': state['revision'], 'events': len(state['events']), 'reconstructed': True}
        else:
            require(args.output is not None, '匯出需要--output')
            require(not args.output.exists(), '匯出目的地已存在，不覆寫')
            result = state if args.audience == 'host' else {section: visible_panel(state, section) for section in ('面板', '能力', '技能', '物品', '關係', '聲望')}
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open('x', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            json.loads(args.output.read_text(encoding='utf-8'))
            result = {'exported': str(args.output), 'audience': args.audience, 'resumable': args.audience == 'host'}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False))
        raise SystemExit(1)
