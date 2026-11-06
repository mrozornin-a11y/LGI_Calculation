"""Хранилище SQLite: миграции, иерархия, неизменяемость версий расчёта, резервная копия."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fluid_app import calc
from fluid_app.db import SCHEMA_VERSION, Database, DatabaseError


class DbCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.db = Database(self.dir / 'test.sqlite')
        self.pid = self.db.add_project('П1')
        self.sid = self.db.add_sample(self.pid, 'BR2')

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()


class TestSchema(DbCase):
    def test_version(self):
        self.assertEqual(self.db.schema_version(), SCHEMA_VERSION)

    def test_reopen_keeps_data(self):
        self.db.close()
        self.db = Database(self.dir / 'test.sqlite')
        self.assertEqual([p['name'] for p in self.db.projects()], ['П1'])

    def test_newer_schema_refused(self):
        path = self.dir / 'new.sqlite'
        c = sqlite3.connect(path)
        c.execute('PRAGMA user_version = 999')
        c.execute('CREATE TABLE x(a)')
        c.commit()
        c.close()
        with self.assertRaises(DatabaseError):
            Database(path)

    def test_backup(self):
        target = self.db.backup_to(self.dir / 'copy.sqlite')
        other = Database(target)
        self.assertEqual(len(other.projects()), 1)
        other.close()
        with self.assertRaises(DatabaseError):
            self.db.backup_to(self.dir / 'test.sqlite')


class TestHierarchy(DbCase):
    def test_tree(self):
        mid = self.db.add_mineral(self.sid, 'кварц')
        fid = self.db.add_fia(self.sid, mid, 'A1')
        iid = self.db.add_inclusion(self.sid, 'FI-1', None, fid)
        inc = self.db.find_inclusion(self.sid, 'FI-1')
        self.assertEqual(inc['mineral_id'], mid)          # минерал наследуется от FIA
        self.assertEqual(inc['id'], iid)

    def test_duplicates_refused(self):
        self.db.add_inclusion(self.sid, 'FI-1')
        with self.assertRaises(DatabaseError):
            self.db.add_inclusion(self.sid, 'FI-1')
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.add_sample(self.pid, 'BR2')
        self.db.add_fia(self.sid, None, 'A')
        with self.assertRaises(DatabaseError):
            self.db.add_fia(self.sid, None, 'A')

    def test_empty_name_refused(self):
        with self.assertRaises(DatabaseError):
            self.db.add_sample(self.pid, '   ')

    def test_observation_validation(self):
        iid = self.db.add_inclusion(self.sid, 'FI-1')
        with self.assertRaises(DatabaseError):
            self.db.add_observation(iid, {'kind': 'Tm_ice', 'temperature_c': None})
        with self.assertRaises(DatabaseError):
            self.db.add_observation(iid, {'kind': 'Tm_ice', 'temperature_c': -5, 'uncertainty_c': -1})
        with self.assertRaises(DatabaseError):
            self.db.add_observation(iid, {'kind': 'bad', 'temperature_c': -5})

    def test_flags_roundtrip_none(self):
        iid = self.db.add_inclusion(self.sid, 'FI-1')
        oid = self.db.add_observation(iid, {'kind': 'Tm_clath', 'temperature_c': 5.8, 'liquid_co2_present': True,
                                            'vapor_co2_present': False})
        o = self.db.observation(oid)
        self.assertIs(o['liquid_co2_present'], True)
        self.assertIs(o['vapor_co2_present'], False)
        self.assertIsNone(o['aqueous_brine_present'])

    def test_cascade_delete(self):
        iid = self.db.add_inclusion(self.sid, 'FI-1')
        self.db.add_observation(iid, {'kind': 'Tm_ice', 'temperature_c': -5})
        self.db.delete('samples', self.sid)
        self.assertEqual(self.db.observations(), [])


class TestRuns(DbCase):
    def _run(self):
        obs = self.db.observations()
        items = [(o, calc.calculate_observation(o)) for o in obs]
        return self.db.save_run(self.pid, 'тест', calc.backend_versions(), items)

    def test_runs_do_not_overwrite(self):
        iid = self.db.add_inclusion(self.sid, 'FI-1')
        oid = self.db.add_observation(iid, {'kind': 'Tm_ice', 'temperature_c': -5})
        r1 = self._run()
        self.db.update_observation(oid, {'kind': 'Tm_ice', 'temperature_c': -10})
        r2 = self._run()
        v1 = self.db.results(r1)[0]
        v2 = self.db.results(r2)[0]
        self.assertAlmostEqual(v1['value'], 7.864625)
        self.assertAlmostEqual(v2['value'], 13.937)
        self.assertEqual(v1['inputs']['temperature_c'], -5)   # снимок входных данных сохранён
        self.assertEqual(len(self.db.runs()), 2)

    def test_results_survive_observation_delete(self):
        iid = self.db.add_inclusion(self.sid, 'FI-1')
        oid = self.db.add_observation(iid, {'kind': 'Tm_ice', 'temperature_c': -5})
        r1 = self._run()
        self.db.delete('observations', oid)
        res = self.db.results(r1)
        self.assertEqual(len(res), 1)
        self.assertIsNone(res[0]['observation_id'])
        self.assertEqual(res[0]['inclusion_name'], 'FI-1')

    def test_run_records_versions(self):
        iid = self.db.add_inclusion(self.sid, 'FI-1')
        self.db.add_observation(iid, {'kind': 'Th_total', 'temperature_c': 250})
        run = self.db.run(self._run())
        self.assertEqual((run['n_total'], run['n_ok'], run['n_skipped']), (1, 0, 1))
        for k in ('app_version', 'core_version', 'python_version', 'coolprop_version'):
            self.assertTrue(run[k])


if __name__ == '__main__':
    unittest.main()
