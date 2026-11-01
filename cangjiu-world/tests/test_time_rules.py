import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('game_time_tests', ROOT / 'scripts/game.py')
game = importlib.util.module_from_spec(spec)
spec.loader.exec_module(game)
DAY, MONTH = game.time_rules.DAY, game.time_rules.MONTH


class TimeTests(unittest.TestCase):
    def ready(self, mode='rpg', age=219):
        state = game.new_state('test', mode, '隔離測試')
        if mode == 'rpg':
            game.apply(state, 'build', self.payload(state, attributes=dict.fromkeys(game.ATTRS, 10), skills={'觀察': 3, '交涉': 3}))
        game.apply(state, 'finalize', self.payload(state, player_confirmed=True, age_months=age, source_refs=['隔離假設'],
                                                  scene={'location': '測試室', 'summary': '等待安排', 'choices': []}))
        return state

    def payload(self, state, **fields):
        return {'event_id': f'test-{state["revision"]}', 'expected_revision': state['revision'], 'source_refs': ['隔離測試'], **fields}

    def act(self, state, operation, **fields):
        return game.apply(state, 'time', self.payload(state, operation=operation, **fields))

    def tick(self, state, seconds, **fields):
        return game.apply(state, 'commit', self.payload(state, reason='測試經過時間', elapsed_seconds=seconds, **fields))

    def schedule(self, state, identifier='training', cost=2, days=3, **fields):
        return self.act(state, 'schedule', activity_id=identifier, name='學習觀察', category='study', ap_cost=cost,
                        duration_seconds=days * DAY, player_confirmed=True, basis='測試訓練', **fields)

    def test_month_and_age_no_automatic_jump(self):
        state = self.ready()
        self.assertEqual(game.visible_panel(state)['rpg_time']['age_display'], '18歲3個月')
        self.tick(state, DAY)
        self.assertEqual(game.visible_panel(state)['rpg_time']['age_display'], '18歲3個月')
        self.assertEqual(game.visible_panel(state)['rpg_time']['day_in_unit'], 2)
        self.act(state, 'end-unit', player_confirmed=True, reason='玩家結束本月')
        self.assertEqual(game.visible_panel(state)['rpg_time']['age_display'], '18歲4個月')
        self.assertEqual(state['snapshot']['world_seconds'], MONTH)

    def test_reserve_once_and_query_no_time(self):
        state = self.ready()
        payload = self.payload(state, operation='schedule', activity_id='one', name='測試活動', category='study', ap_cost=3,
                               duration_seconds=5 * DAY, player_confirmed=True, basis='測試')
        game.apply(state, 'time', payload)
        before = copy.deepcopy(state)
        self.assertTrue(game.apply(state, 'time', payload)['replayed'])
        self.assertEqual(game.visible_panel(state)['rpg_time']['ap_remaining'], 9)
        game.visible_panel(state, '物品')
        self.assertEqual(state, before)
        self.tick(state, 2 * DAY)
        self.assertEqual(state['snapshot']['rpg_time']['activity']['remaining_seconds'], 3 * DAY)

    def test_budget_and_month_space_rejected(self):
        state = self.ready()
        self.tick(state, 29 * DAY)
        before = copy.deepcopy(state)
        with self.assertRaises(ValueError): self.schedule(state, days=2)
        self.assertEqual(state, before)
        self.schedule(state, cost=12, days=1)
        with self.assertRaises(ValueError): self.schedule(state, identifier='second', cost=1, days=1)
        self.tick(state, DAY)
        self.assertEqual(game.visible_panel(state)['rpg_time']['ap_remaining'], 12)

    def test_nested_situations_pause_activity(self):
        state = self.ready()
        self.schedule(state)
        self.tick(state, DAY, time_transition={'operation': 'enter', 'situation_id': 'realm', 'kind': 'realm', 'name': '祕境'})
        self.act(state, 'enter', situation_id='fight', kind='combat', name='遭遇戰')
        self.tick(state, 600)
        with self.assertRaises(ValueError): self.act(state, 'exit', situation_id='realm', resolution='尚不能離開外層')
        self.act(state, 'exit', situation_id='fight', resolution='戰鬥結束')
        self.assertEqual(game.visible_panel(state)['rpg_time']['situation']['id'], 'realm')
        self.act(state, 'exit', situation_id='realm', resolution='離開祕境')
        self.assertEqual(game.visible_panel(state)['rpg_time']['state'], '自由時間')
        self.assertEqual(state['snapshot']['rpg_time']['activity']['remaining_seconds'], 2 * DAY)
        self.assertEqual(game.visible_panel(state)['rpg_time']['ap_remaining'], 10)

    def test_special_crosses_month_no_ap_accumulation(self):
        state = self.ready()
        self.act(state, 'enter', situation_id='conversation', kind='dialogue', name='長期事件')
        self.tick(state, 2 * MONTH + 60)
        clock = state['snapshot']['rpg_time']
        self.assertEqual(len(clock['closed_units']), 2)
        self.assertEqual(clock['ap_capacity'], 12)
        self.assertEqual(game.visible_panel(state)['rpg_time']['age_display'], '18歲5個月')
        self.assertEqual(clock['unit_elapsed'], 60)

    def test_health_recalculates_without_refunding_spent(self):
        state = self.ready()
        self.schedule(state, cost=4, days=1)
        self.tick(state, DAY, entities={'player': {'hp': {'current': 50, 'max': 100}}})
        self.assertEqual(game.visible_panel(state)['rpg_time']['ap_remaining'], 2)
        self.tick(state, 0, entities={'player': {'hp': {'current': 100, 'max': 100}}})
        self.assertEqual(game.visible_panel(state)['rpg_time']['ap_remaining'], 8)
        self.assertEqual(state['snapshot']['rpg_time']['ap_spent'], 4)

    def test_incapacitated_can_face_situations(self):
        state = self.ready()
        self.tick(state, 0, entities={'player': {'fatigue': '無法活動'}})
        self.assertEqual(game.visible_panel(state)['rpg_time']['ap_remaining'], 0)
        with self.assertRaises(ValueError): self.schedule(state, cost=1)
        self.act(state, 'enter', situation_id='talk', kind='dialogue', name='來訪者說話')
        self.assertEqual(game.visible_panel(state)['rpg_time']['state'], '特殊情境')

    def test_claim_only_completed_once(self):
        state = self.ready()
        self.schedule(state, days=1)
        with self.assertRaises(ValueError): self.act(state, 'claim', activity_id='training', resolution='尚未完成')
        self.tick(state, DAY)
        self.tick(state, 0, time_transition={'operation': 'claim', 'activity_id': 'training', 'resolution': '累積觀察學習進展'},
                  entities={'player': {'growth_progress': [{'activity_id': 'training', 'skill': '觀察', 'progress': 1}]}})
        with self.assertRaises(ValueError): self.act(state, 'claim', activity_id='training', resolution='重複領取')
        self.assertTrue(game.verify(state))

    def test_cancel_does_not_refund(self):
        state = self.ready()
        self.schedule(state, cost=5)
        self.act(state, 'cancel', player_confirmed=True)
        self.assertEqual(game.visible_panel(state)['rpg_time']['ap_remaining'], 7)
        self.assertEqual(state['snapshot']['rpg_time']['activities'][0]['status'], 'cancelled')

    def test_end_month_needs_confirmation_and_idle(self):
        state = self.ready()
        with self.assertRaises(ValueError): self.act(state, 'end-unit', reason='沒有授權')
        self.schedule(state)
        with self.assertRaises(ValueError): self.act(state, 'end-unit', player_confirmed=True, reason='活動仍進行')

    def test_story_unchanged_and_no_rpg_commands(self):
        state = self.ready('story')
        with self.assertRaises(ValueError): self.act(state, 'enter', situation_id='x', kind='combat', name='RPG操作')
        self.tick(state, 45 * DAY)
        self.assertNotIn('rpg_time', state['snapshot'])
        self.assertNotIn('rpg_time', game.visible_panel(state))
        self.assertEqual(state['snapshot']['entities']['player']['attributes'], {})
        self.assertTrue(game.verify(state))

    def test_legacy_save_explicit_setup(self):
        state = game.new_state('legacy', 'rpg')
        # A legacy event sequence has no rpg_time field; it must remain valid.
        state['initial']['phase'] = 'playing'
        state['snapshot'] = copy.deepcopy(state['initial'])
        state['initial']['entities']['player']['location'] = '尚未開局'
        state['snapshot']['entities']['player']['location'] = '尚未開局'
        self.assertTrue(game.verify(state))
        self.act(state, 'setup', player_confirmed=True, age_months=240)
        with self.assertRaises(ValueError): self.act(state, 'setup', player_confirmed=True)
        self.assertEqual(game.visible_panel(state)['rpg_time']['age_display'], '20歲0個月')

    def test_restore_pending_activity_and_nested_situation(self):
        state = self.ready()
        self.schedule(state)
        self.act(state, 'enter', situation_id='x', kind='realm', name='測試祕境')
        with tempfile.TemporaryDirectory(dir=ROOT, prefix='test-isolated-') as directory:
            self.assertTrue(Path(directory).resolve().is_relative_to(ROOT.resolve()))
            path = game.save_path(directory, 'restore')
            with game.locked(path): game.atomic(path, state)
            loaded = game.load(path)
            self.assertEqual(loaded, state)
            self.assertEqual(game.visible_panel(loaded)['rpg_time']['activity']['remaining_seconds'], 3 * DAY)


if __name__ == '__main__':
    unittest.main()
