"""Графики и работа без сети."""
import socket
import tempfile
import unittest
from pathlib import Path

from fluid_app import calc, importer, plots
from fluid_app.db import Database

ROOT = Path(__file__).resolve().parent.parent


class NoNetwork:
    """Любая попытка открыть сетевое соединение приводит к ошибке теста."""

    def __enter__(self):
        self._orig = socket.socket.connect, socket.create_connection, socket.getaddrinfo

        def deny(*a, **k):
            raise AssertionError('Попытка сетевого соединения')
        socket.socket.connect = deny
        socket.create_connection = deny
        socket.getaddrinfo = deny
        return self

    def __exit__(self, *exc):
        socket.socket.connect, socket.create_connection, socket.getaddrinfo = self._orig


class TestWorkflowOffline(unittest.TestCase):
    def test_full_workflow_without_network(self):
        with NoNetwork(), tempfile.TemporaryDirectory() as d:
            db = Database(Path(d) / 'db.sqlite')
            pid = db.add_project('Офлайн')
            t = importer.read_table(ROOT / 'examples' / 'example_wide.xlsx')
            importer.import_rows(db, pid, importer.parse_rows(t, importer.auto_mapping(t.headers)), source='x')
            obs = db.observations()
            items = [(o, calc.calculate_observation(o)) for o in obs]
            rid = db.save_run(pid, 'все', calc.backend_versions(), items)
            results = db.results(rid)
            run = db.run(rid)
            for ptype in plots.PLOT_TYPES:
                for group in plots.GROUP_BY:
                    fig = plots.make_figure(ptype, results, group, run)
                    self.assertTrue(fig.axes)
            fig = plots.make_figure('th_salinity', results, 'fia', run)
            for ext in ('png', 'svg'):
                out = Path(d) / f'plot.{ext}'
                plots.save_figure(fig, str(out))
                self.assertGreater(out.stat().st_size, 1000)
            db.close()

    def test_th_salinity_points_use_mean_of_replicates(self):
        def res(kind, t, value=None, method=None, status='skipped'):
            return dict(project_name='P', sample_name='S', fia_name=None, inclusion_name='1', kind=kind,
                        inputs={'temperature_c': t}, status=status, method_key=method, value=value)
        results = [res('Th_total', 200), res('Th_total', 210),
                   res('Tm_ice', -5, 7.8, 'bodnar_1993', 'ok'), res('Tm_ice', -5, 7.8, 'bodnar_1993', 'error')]
        results[-1]['status'] = 'error'
        pts, replicated = plots.th_salinity_points(results, 'sample')
        self.assertEqual(pts[('S', 'bodnar_1993')], [(7.8, 205)])
        self.assertEqual(replicated, 1)

    def test_empty_plot(self):
        fig = plots.make_figure('hist_th_total', [], 'sample')
        self.assertTrue(fig.axes)


if __name__ == '__main__':
    unittest.main()
