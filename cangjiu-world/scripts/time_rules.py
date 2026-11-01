"""RPG calendar and activity scheduling; no story-mode side effects."""
import copy

DAY = 86400
MONTH = 30 * DAY


def need(value, message):
    if not value:
        raise ValueError(message)


def integer(value, minimum=0):
    return type(value) is int and value >= minimum


def capacity(player):
    if player['life'] != 'alive':
        return 0
    maximum = 12
    hp = player.get('hp')
    if hp:
        ratio = hp['current'] / hp['max']
        maximum = 0 if ratio <= 0 else 3 if ratio <= .25 else 6 if ratio <= .5 else 9 if ratio <= .75 else 12
    maximum = min(maximum, {'正常': 12, '輕度疲勞': 9, '疲勞': 6, '重度疲勞': 3, '無法活動': 0}.get(player.get('fatigue'), 12))
    for effect in player.get('effects', []):
        if isinstance(effect, dict) and 'ap_cap' in effect:
            need(integer(effect['ap_cap']) and effect['ap_cap'] <= 12, 'ap_cap須為0～12整數')
            maximum = min(maximum, effect['ap_cap'])
    return maximum


def initialize(player, world_seconds, age_months=None, unit_seconds=MONTH):
    need(integer(unit_seconds, 1), '需指定有效時間單位')
    need(age_months is None or integer(age_months), '年齡需非負整數月，未知可留空')
    return {'unit_seconds': unit_seconds, 'origin_seconds': world_seconds, 'age_months_at_origin': age_months,
            'unit_index': 0, 'unit_elapsed': 0, 'ap_capacity': capacity(player), 'ap_spent': 0,
            'activity': None, 'activities': [], 'situations': [], 'closed_units': []}


def validate(clock, world_seconds):
    need(integer(clock['unit_seconds'], 1) and integer(clock['origin_seconds']), '時間單位或基準錯誤')
    need(world_seconds >= clock['origin_seconds'], '時間不可早於月制基準')
    index, elapsed = divmod(world_seconds - clock['origin_seconds'], clock['unit_seconds'])
    need(clock['unit_index'] == index and clock['unit_elapsed'] == elapsed, '月內進度與世界時間不一致')
    need(integer(clock['ap_capacity']) and clock['ap_capacity'] <= 12 and integer(clock['ap_spent']), '行動點欄位錯誤')
    need(clock['age_months_at_origin'] is None or integer(clock['age_months_at_origin']), '年齡基準錯誤')
    activity = clock['activity']
    if activity:
        need(integer(activity['remaining_seconds'], 1) and activity['remaining_seconds'] <= activity['duration_seconds'], '活動剩餘時間錯誤')
    ids = [item['id'] for item in clock['activities']]
    need(len(ids) == len(set(ids)), '活動ID重複')
    need(len({item['id'] for item in clock['situations']}) == len(clock['situations']), '特殊情境ID重複')


def advance(clock, before_seconds, elapsed, before_player, after_player):
    result = copy.deepcopy(clock)
    validate(result, before_seconds)
    need(integer(elapsed), '耗時須為非負整數')
    activity = result['activity']
    if activity and not result['situations']:
        need(elapsed <= activity['remaining_seconds'], '先結算活動完成點，不越過活動終點自動等待')
        activity['remaining_seconds'] -= elapsed
        if activity['remaining_seconds'] == 0:
            record = next(a for a in result['activities'] if a['id'] == activity['id'])
            record.update(status='completed', completed_at=before_seconds + elapsed)
            result['activity'] = None
    end = before_seconds + elapsed
    new_index, new_elapsed = divmod(end - result['origin_seconds'], result['unit_seconds'])
    need(new_index - result['unit_index'] <= 1200, '一次時間提交最多1200個單位，長期跳躍請分段核對事件')
    while result['unit_index'] < new_index:
        result['closed_units'].append({'index': result['unit_index'], 'ap_capacity': result['ap_capacity'], 'ap_spent': result['ap_spent']})
        result['unit_index'] += 1
        result['ap_spent'] = 0
        result['ap_capacity'] = capacity(before_player)
    result['unit_elapsed'] = new_elapsed
    # Changed conditions apply at the end of this event, never retroactively
    # to the old month's activity or a previously emitted boundary record.
    result['ap_capacity'] = capacity(after_player)
    validate(result, end)
    return result


def transition(clock, operation, data, world_seconds, player):
    result = copy.deepcopy(clock)
    validate(result, world_seconds)
    result['ap_capacity'] = capacity(player)
    if operation == 'schedule':
        need(not result['situations'] and result['activity'] is None, '目前不能安排新的自由時間活動')
        need(player['life'] == 'alive', '角色不能正常安排活動')
        identifier = data.get('activity_id')
        need(isinstance(identifier, str) and identifier.strip(), '活動需有ID')
        need(not any(a['id'] == identifier for a in result['activities']), '活動ID已使用')
        cost, duration = data.get('ap_cost'), data.get('duration_seconds')
        need(integer(cost) and cost <= 12 and integer(duration, 1), '需有效行動點成本與耗時')
        need(cost > 0 or data.get('category') in ('rest', 'wait'), '只有休息或等待可為0行動點')
        need(cost <= max(0, result['ap_capacity'] - result['ap_spent']), '剩餘行動點不足')
        need(duration <= result['unit_seconds'] - result['unit_elapsed'], '自由活動須在本單位內安排；長活動請分月')
        need(data.get('name') and data.get('player_confirmed') is True and data.get('basis'), '活動需名稱、依據及玩家授權')
        result['ap_spent'] += cost
        result['activity'] = {'id': identifier, 'name': data['name'], 'duration_seconds': duration,
                              'remaining_seconds': duration, 'ap_cost': cost, 'reserved_in_unit': result['unit_index']}
        result['activities'].append({'id': identifier, 'name': data['name'], 'status': 'scheduled', 'ap_cost': cost,
                                     'started_at': world_seconds, 'claimed': False})
    elif operation == 'enter':
        identifier = data.get('situation_id')
        need(isinstance(identifier, str) and identifier.strip() and data.get('name'), '特殊情境需ID及名稱')
        need(data.get('kind') in ('combat', 'dialogue', 'realm', 'other'), '特殊情境類型錯誤')
        need(not any(a['id'] == identifier for a in result['situations']), '情境已在進行')
        result['situations'].append({'id': identifier, 'name': data['name'], 'kind': data['kind'], 'entered_at': world_seconds,
                                     'entry_location': data.get('location', player['location'])})
    elif operation == 'exit':
        need(result['situations'] and result['situations'][-1]['id'] == data.get('situation_id'), '只能結束目前最內層情境')
        need(data.get('resolution'), '結束情境需有結果依據')
        result['situations'].pop()
    elif operation == 'cancel':
        need(not result['situations'] and result['activity'], '無可取消的自由活動')
        need(data.get('player_confirmed') is True, '取消活動需玩家授權')
        record = next(a for a in result['activities'] if a['id'] == result['activity']['id'])
        record.update(status='cancelled', completed_at=world_seconds)
        result['activity'] = None
        # Reserved AP is not refunded by toggling situations or cancelling.
    elif operation == 'claim':
        records = [a for a in result['activities'] if a['id'] == data.get('activity_id')]
        need(records and records[0]['status'] == 'completed' and not records[0]['claimed'], '活動未完成或已結算收益')
        need(data.get('resolution'), '活動結算需記錄結果，不保證獲益')
        records[0]['claimed'] = True
        records[0]['resolution'] = data['resolution']
    else:
        raise ValueError('未知時間狀態操作')
    validate(result, world_seconds)
    return result


def public_clock(clock):
    age = clock['age_months_at_origin']
    if age is not None:
        age += (clock['unit_index'] * clock['unit_seconds'] + clock['unit_elapsed']) // MONTH
    return {'state': '特殊情境' if clock['situations'] else '自由時間', 'age_months': age,
            'age_display': f'{age // 12}歲{age % 12}個月' if age is not None else '未確認',
            'unit_number': clock['unit_index'] + 1, 'day_in_unit': clock['unit_elapsed'] // DAY + 1,
            'unit_seconds': clock['unit_seconds'], 'ap_capacity': clock['ap_capacity'],
            'ap_remaining': max(0, clock['ap_capacity'] - clock['ap_spent']),
            'activity': copy.deepcopy(clock['activity']),
            'situation': copy.deepcopy(clock['situations'][-1]) if clock['situations'] else None}
