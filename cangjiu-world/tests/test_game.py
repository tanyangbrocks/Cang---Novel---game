import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('game', ROOT / 'scripts/game.py')
game = importlib.util.module_from_spec(spec)
spec.loader.exec_module(game)


class EngineTests(unittest.TestCase):
    def ready(self):
        state = game.new_state('test', 'rpg', '測試人物')
        game.apply(state, 'build', {'event_id': 'build', 'expected_revision': 0, 'attributes': dict.fromkeys(game.ATTRS, 10), 'skills': {'觀察': 2, '交涉': 2, '野外求生': 2}})
        game.apply(state, 'finalize', {'event_id': 'open', 'expected_revision': 1, 'player_confirmed': True, 'source_refs': ['test-isolated'], 'scene': {'location': '測試房間', 'summary': '等待行動', 'choices': ['查看門上的字', '留在原地']}})
        return state

    def check_data(self, state, event_id='roll'):
        return {'event_id': event_id, 'expected_revision': state['revision'], 'gate': 'uncertain', 'basis': '隔離測試', 'obstacle_id': 'door',
                'actor_id': 'player', 'attribute_name': '感知', 'attribute': 10, 'skill_name': '觀察', 'rank': 2, 'difficulty': 10, 'required_rank': 1, 'context': 10, 'luck': 10}

    def commit(self, state, **fields):
        return {'event_id': f'event-{state["revision"]}', 'expected_revision': state['revision'], 'reason': '隔離測試事件', 'source_refs': ['test'], **fields}

    def test_probability_and_edges(self):
        self.assertEqual(game.probability(10, 10), 50)
        self.assertEqual(game.probability(20, 10), 70)
        self.assertEqual(game.probability(5, 10), 30)
        self.assertEqual(game.probability(10, 10, 2, 1, 10), 65)
        self.assertEqual(game.probability(100000, 1), 95)
        self.assertEqual(game.probability(1, 100000), 5)
        self.assertEqual(game.resolve(65, 65), '成功')
        self.assertEqual(game.resolve(65, 66), '失敗')
        self.assertEqual(game.resolve(65, 35), '出色成功')
        self.assertEqual(game.resolve(65, 95), '明顯失敗')

    def test_bad_numbers_rejected(self):
        for args in [(0, 10), (float('nan'), 10), (10, float('inf'))]:
            with self.assertRaises(ValueError): game.probability(*args)

    def test_creation_budget(self):
        state = game.new_state('test', 'rpg')
        payload = {'event_id': 'x', 'expected_revision': 0, 'attributes': dict.fromkeys(game.ATTRS, 15), 'skills': {'觀察': 3, '交涉': 3}}
        with self.assertRaises(ValueError): game.apply(state, 'build', payload)
        self.assertEqual(state['revision'], 0)

    def test_dice_idempotent_and_no_fishing(self):
        state = self.ready()
        payload = self.check_data(state)
        calls = []
        first = game.apply(state, 'check', payload, roller=lambda: calls.append(1) or 42)
        retry = game.apply(state, 'check', payload, roller=lambda: 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(first['event'], retry['event'])
        with self.assertRaises(ValueError): game.apply(state, 'check', self.check_data(state, 'new-roll'))
        game.apply(state, 'commit', self.commit(state, check_id='roll', elapsed_seconds=10))
        with self.assertRaises(ValueError): game.apply(state, 'commit', self.commit(state, check_id='roll'))
        self.assertTrue(game.verify(state))

    def test_stale_revision(self):
        state = self.ready()
        payload = self.commit(state)
        payload['expected_revision'] = 0
        with self.assertRaises(ValueError): game.apply(state, 'commit', payload)

    def test_bad_state_does_not_mutate(self):
        for fields in ({'entities': {'player': {'hp': {'current': -1, 'max': 100}}}}, {'entities': {'player': {'cash': -1}}},
                       {'items': {'x': {'quantity': -1, 'owner': 'player'}}}):
            state = self.ready()
            before = copy.deepcopy(state)
            with self.assertRaises(ValueError): game.apply(state, 'commit', self.commit(state, **fields))
            self.assertEqual(state, before)

    def test_death_and_revival(self):
        state = self.ready()
        game.apply(state, 'commit', self.commit(state, entities={'player': {'life': 'dead', 'hp': {'current': 0, 'max': 100}}}))
        with self.assertRaises(ValueError): game.apply(state, 'check', self.check_data(state))
        with self.assertRaises(ValueError): game.apply(state, 'commit', self.commit(state, event_type='revival', entities={'player': {'life': 'alive'}}))
        game.apply(state, 'commit', self.commit(state, event_type='revival', mechanism='僅測試假定儀式已完成', entities={'player': {'life': 'alive', 'hp': {'current': 1, 'max': 100}}}))
        self.assertTrue(game.verify(state))

    def test_zero_hp_becomes_dying(self):
        state = self.ready()
        game.apply(state, 'commit', self.commit(state, entities={'player': {'hp': {'current': 0, 'max': 100}}}))
        self.assertEqual(state['snapshot']['entities']['player']['life'], 'dying')

    def test_location_cannot_jump_without_event(self):
        state = self.ready()
        with self.assertRaises(ValueError): game.apply(state, 'commit', self.commit(state, entities={'player': {'location': '別處'}}))
        with self.assertRaises(ValueError): game.apply(state, 'commit', self.commit(state, event_type='movement', entities={'player': {'location': '別處'}}))
        game.apply(state, 'commit', self.commit(state, event_type='movement', elapsed_seconds=30, entities={'player': {'location': '別處'}}, scene={'location': '別處', 'summary': '已抵達', 'choices': []}))
        self.assertEqual(state['snapshot']['world_seconds'], 30)

    def test_query_is_readonly_and_private(self):
        state = self.ready()
        game.apply(state, 'commit', self.commit(state, relations={'npc': {'secret': '秘密', 'public': {'態度': '未知'}}},
                                               items={'a': {'name': '信', 'quantity': 1, 'owner': 'player', 'location': '包', 'secret': '不可洩漏'}}))
        before = copy.deepcopy(state)
        self.assertNotIn('秘密', json.dumps(game.visible_panel(state, '關係'), ensure_ascii=False))
        self.assertNotIn('不可洩漏', json.dumps(game.visible_panel(state, '物品'), ensure_ascii=False))
        self.assertEqual(game.visible_panel(state)['current_scene']['location'], '測試房間')
        self.assertEqual(state, before)

    def test_reconstruction_and_corruption(self):
        state = self.ready()
        game.apply(state, 'commit', self.commit(state, elapsed_seconds=9, entities={'player': {'cash': 900}}))
        self.assertTrue(game.verify(state))
        bad = copy.deepcopy(state)
        bad['snapshot']['entities']['player']['cash'] = 9999
        with self.assertRaises(ValueError): game.verify(bad)
        bad = copy.deepcopy(state)
        bad['events'][0]['input']['skills']['觀察'] = 5
        with self.assertRaises(ValueError): game.verify(bad)

    def test_disk_export_resume_and_preserve(self):
        with tempfile.TemporaryDirectory(dir=ROOT, prefix='test-isolated-') as directory:
            self.assertTrue(Path(directory).resolve().is_relative_to(ROOT.resolve()))
            path = game.save_path(directory, 'test')
            with game.locked(path): game.atomic(path, self.ready())
            state = game.load(path)
            game.apply(state, 'commit', self.commit(state, elapsed_seconds=12))
            with game.locked(path): game.atomic(path, state)
            self.assertEqual(game.load(path)['snapshot']['world_seconds'], 12)
            self.assertTrue((path.parent / 'history/revision-000002.json').exists())
            out = Path(directory) / 'export.json'
            cmd = [sys.executable, str(ROOT / 'scripts/game.py'), 'export', '--root', directory, '--id', 'test', '--audience', 'host', '--output', str(out)]
            self.assertEqual(subprocess.run(cmd, capture_output=True).returncode, 0)
            self.assertTrue(game.verify(json.loads(out.read_text(encoding='utf-8'))))
            self.assertNotEqual(subprocess.run(cmd, capture_output=True).returncode, 0)

    def test_path_traversal(self):
        with self.assertRaises(ValueError): game.save_path('.', '../other')


if __name__ == '__main__':
    unittest.main()
