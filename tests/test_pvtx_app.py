"""Подключение строгой модели H₂O–CO₂–NaCl (режимы 1–3) к расчётному слою приложения."""
import unittest

from fluid_app import calc
from fluid_core import duan1995, h2o_co2_nacl as model, mao2013


def obs(kind, t, **kw):
    d = dict(kind=kind, temperature_c=t, uncertainty_c=None, homogenization_to=None, liquid_co2_present=None,
             vapor_co2_present=None, aqueous_brine_present=None, co2_purity_confirmed=None, inclusion_id=1,
             inclusion_name='1', sample_name='S', project_name='P', carbonic_fraction=0.3,
             carbonic_fraction_unc=None, carbonic_fraction_method='визуально', carbonic_fraction_temp_c=23.5)
    d.update(kw)
    return d


Q2 = dict(liquid_co2_present=True, vapor_co2_present=True, aqueous_brine_present=True)


def pvtx(rows):
    return next((ob, o) for ob, o in calc.calculate_all(rows) if o.kind == 'co2_pvtx')


def mode1_rows(**kw):
    return [obs('Th_CO2', 25.0, homogenization_to='liquid', co2_purity_confirmed=True, **kw),
            obs('Tm_clath', 8.0, **Q2, **kw)]


class TestModes(unittest.TestCase):
    def test_mode1_equals_core(self):
        _, o = pvtx(mode1_rows())
        ref = model.mode1(8.0, 25.0, 'liquid', 0.3, 23.5)
        self.assertEqual(o.status, 'ok', o.message)
        self.assertEqual(o.value, ref.density_g_cm3)
        self.assertEqual(o.unit, 'г/см³')
        self.assertEqual(o.extras['mode'], 1)
        self.assertEqual(o.extras['x_co2'], ref.x_co2)
        self.assertTrue(o.extras['converged'])
        self.assertIn('Steele-MacInnis', o.model)
        self.assertTrue(o.assumptions and o.scope)
        self.assertTrue(any('не давление захвата' in w for w in o.warnings))

    def test_mode2_both_branches(self):
        for branch, flags in (('liquid', dict(liquid_co2_present=True, vapor_co2_present=False)),
                              ('vapor', dict(liquid_co2_present=False, vapor_co2_present=True))):
            with self.subTest(branch):
                rows = [obs('Th_CO2', 5.0, homogenization_to=branch, co2_purity_confirmed=True),
                        obs('Tm_clath', 8.0, aqueous_brine_present=True, **flags)]
                _, o = pvtx(rows)
                self.assertEqual(o.status, 'ok', o.message)
                self.assertEqual(o.extras['mode'], 2)
                self.assertEqual(o.value, model.mode2(8.0, 5.0, branch, 0.3, 23.5).density_g_cm3)

    def test_mode3(self):
        rows = [obs('Tm_ice', -5.0), obs('Tm_clath', 5.0, liquid_co2_present=False, vapor_co2_present=True,
                                         aqueous_brine_present=True, co2_purity_confirmed=True)]
        _, o = pvtx(rows)
        self.assertEqual(o.status, 'ok', o.message)
        self.assertEqual(o.extras['mode'], 3)
        self.assertEqual(o.value, model.mode3(-5.0, 5.0, 0.3, 23.5).density_g_cm3)
        self.assertTrue(any('в присутствии клатрата' in w for w in o.warnings))
        self.assertIsNotNone(o.extras['pressure_at_tm_ice_bar'])

    def test_not_a_carbonic_inclusion(self):
        items = calc.calculate_all([obs('Tm_ice', -3.0), obs('Th_total', 200.0, homogenization_to='liquid')])
        self.assertFalse([o for _, o in items if o.kind == 'co2_pvtx'])

    def test_phi_uncertainty_range(self):
        _, o = pvtx(mode1_rows(carbonic_fraction_unc=0.05))
        self.assertLess(o.extras['rho_at_phi_plus_u'], o.value)
        self.assertGreater(o.extras['rho_at_phi_minus_u'], o.value)
        _, o2 = pvtx(mode1_rows())
        self.assertTrue(any('Погрешность φ не указана' in w for w in o2.warnings))


class TestMissingData(unittest.TestCase):
    """Пользователь видит, чего не хватает; программа ничего не подставляет."""
    def blocked(self, rows, *texts):
        _, o = pvtx(rows)
        self.assertEqual(o.status, 'error')
        self.assertIsNone(o.value)
        for t in texts:
            self.assertIn(t, o.message)
        return o

    def test_missing_items_are_listed(self):
        self.blocked([obs('Th_CO2', 25.0), obs('Tm_clath', 8.0)], 'Не хватает данных',
                     'направление гомогенизации CO₂', 'приближение чистой CO₂',
                     'Жидкая CO₂ присутствует при плавлении клатрата — не указано')
        self.blocked([obs('Th_CO2', 25.0, homogenization_to='liquid', co2_purity_confirmed=True)],
                     'Tm клатрата')
        self.blocked([obs('Tm_clath', 5.0, liquid_co2_present=False, vapor_co2_present=True,
                          aqueous_brine_present=True, co2_purity_confirmed=True)], 'Tm льда')
        self.blocked(mode1_rows(carbonic_fraction_temp_c=None), 'температура, при которой оценена доля φ')
        self.blocked(mode1_rows(carbonic_fraction=None), 'объёмная доля углекислотных фаз φ')

    def test_phases_contradicting_the_mode(self):
        rows = [obs('Th_CO2', 25.0, homogenization_to='liquid', co2_purity_confirmed=True),
                obs('Tm_clath', 8.0, liquid_co2_present=True, vapor_co2_present=False, aqueous_brine_present=True)]
        self.blocked(rows, 'записанные фазы не соответствуют режиму', 'Газовая CO₂')
        rows = [obs('Th_CO2', 5.0, homogenization_to='liquid', co2_purity_confirmed=True), obs('Tm_clath', 8.0, **Q2)]
        self.blocked(rows, 'режим 2', 'Газовая CO₂')

    def test_duplicates_and_critical(self):
        self.blocked(mode1_rows() + [obs('Tm_clath', 7.0, **Q2)], 'несколько наблюдений «Tm клатрата»')
        rows = [obs('Th_CO2', 25.0, homogenization_to='critical', co2_purity_confirmed=True), obs('Tm_clath', 8.0, **Q2)]
        self.blocked(rows, 'Критическая гомогенизация')

    def test_non_physical_solution_is_reported(self):
        rows = [obs('Th_CO2', 30.5, homogenization_to='vapor', co2_purity_confirmed=True, carbonic_fraction=0.02,
                    carbonic_fraction_temp_c=30.5),
                obs('Tm_clath', 5.0, **Q2, carbonic_fraction=0.02, carbonic_fraction_temp_c=30.5)]
        self.blocked(rows, 'физически недопустимо', 'результат не выдаётся')

    def test_non_convergence_is_reported(self):
        limits = dict(model.RESIDUAL_LIMITS)
        try:
            model.RESIDUAL_LIMITS['volume_cm3_mol'] = 0.0
            self.blocked(mode1_rows(), 'СХОДИМОСТЬ НЕ ДОСТИГНУТА', 'результат не выдаётся')
        finally:
            model.RESIDUAL_LIMITS.update(limits)

    def test_fraction_temperature_below_clathrate_melting(self):
        self.blocked(mode1_rows(carbonic_fraction_temp_c=2.0), 'не ниже Tm клатрата')


class TestPressures(unittest.TestCase):
    """Q31: давление на линии расслоения и давление по изохоре показываются раздельно."""
    def test_two_pressures_at_th_total(self):
        _, o = pvtx(mode1_rows() + [obs('Th_total', 250.0, homogenization_to='liquid')])
        ex = o.extras
        p_solv, p_iso = ex['pressure_solvus_th_total_bar'], ex['pressure_isochore_th_total_bar']
        self.assertAlmostEqual(p_solv, model.solvus_pressure_bar(250.0, ex['x_h2o'], ex['x_nacl'], ex['x_co2']),
                               delta=1e-9)
        self.assertIn('ЭКСТРАПОЛЯЦИЯ', ex['pressure_isochore_th_total_method'])           # 250 °C < 300 °C
        self.assertAlmostEqual(ex['pressure_th_total_difference_bar'], p_iso - p_solv, delta=1e-9)
        self.assertGreater(abs(ex['pressure_th_total_difference_pct']), 5)
        text = ' '.join(o.warnings)
        for t in ('ДВА разных давления', 'не взаимозаменяемы', 'не являются давлением захвата', 'экстраполяцией'):
            self.assertIn(t, text)
        lines = dict(calc.passport_lines(dict(kind='co2_pvtx', **pvtx(
            mode1_rows() + [obs('Th_total', 250.0, homogenization_to='liquid')])[0]['extra_inputs']), o.__dict__))
        self.assertIn('Давление на линии расслоения при Th общ., бар', lines)
        self.assertIn('Давление по изохоре при Th общ., бар', lines)
        self.assertIn('Расхождение двух давлений при Th общ.', lines)

    def test_isochore_pressure_from_eos_above_300(self):
        _, o = pvtx(mode1_rows() + [obs('Th_total', 320.0, homogenization_to='liquid')])
        ex = o.extras
        self.assertIn('уравнение состояния', ex['pressure_isochore_th_total_method'])
        self.assertAlmostEqual(ex['pressure_isochore_th_total_bar'],
                               duan1995.pressure_bar(320.0, ex['molar_volume_cm3_mol'], ex['x_h2o'], ex['x_nacl'],
                                                     ex['x_co2']), delta=1e-9)
        self.assertFalse(any('экстраполяцией' in w for w in o.warnings))

    def test_isochore_points_use_correct_kelvin(self):
        _, o = pvtx(mode1_rows())
        ex = o.extras
        t, p = ex['isochore'][1]
        self.assertEqual(t, 350.0)
        x = (ex['x_h2o'], ex['x_nacl'], ex['x_co2'])
        self.assertAlmostEqual(p, duan1995.pressure_at_kelvin_bar(623.15, ex['molar_volume_cm3_mol'], *x), delta=1e-9)
        author = duan1995.author_isochore(ex['molar_volume_cm3_mol'], *x)                # 623 K под подписью 350 °C
        self.assertGreater(p, author.pressures_bar[0])
        self.assertNotEqual(ex['isochore_slope_bar_per_c'], author.slope_bar_per_c)
        self.assertNotIn('pressure_solvus_th_total_bar', ex)                             # Th общ. не задана

    def test_th_total_not_to_liquid(self):
        _, o = pvtx(mode1_rows() + [obs('Th_total', 250.0, homogenization_to='vapor')])
        self.assertEqual(o.status, 'ok')
        self.assertNotIn('pressure_solvus_th_total_bar', o.extras)
        self.assertTrue(any('не как гомогенизация в жидкость' in w for w in o.warnings))


class TestByTotalHomogenization(unittest.TestCase):
    def test_fallback_is_marked(self):
        rows = mode1_rows(carbonic_fraction=None, carbonic_fraction_temp_c=None) + [
            obs('Th_total', 250.0, homogenization_to='liquid', carbonic_fraction=None, carbonic_fraction_temp_c=None)]
        _, o = pvtx(rows)
        self.assertEqual(o.status, 'ok', o.message)
        self.assertIn('Th общ.', o.extras['fraction_source'])
        text = ' '.join(o.warnings)
        self.assertIn('Доля углекислотных фаз не измерена', text)
        self.assertIn('ОРИЕНТИРОВОЧНО', text)                                            # 250 °C > 200 °C
        ref = model.mode1(8.0, 25.0, 'liquid', total_homogenization_c=250.0, total_homogenization_to='liquid')
        self.assertEqual(o.value, ref.density_g_cm3)

    def test_below_200_is_not_marked_approximate(self):
        rows = mode1_rows(carbonic_fraction=None) + [obs('Th_total', 180.0, homogenization_to='liquid',
                                                         carbonic_fraction=None)]
        _, o = pvtx(rows)
        self.assertEqual(o.status, 'ok', o.message)
        self.assertFalse(any('ОРИЕНТИРОВОЧНО' in w for w in o.warnings))

    def test_measured_fraction_has_priority(self):
        _, o = pvtx(mode1_rows() + [obs('Th_total', 250.0, homogenization_to='liquid')])
        self.assertEqual(o.extras['fraction_source'], 'измеренная доля φ')
        self.assertFalse(any('ОРИЕНТИРОВОЧНО' in w for w in o.warnings))


class TestPureWaterExemption(unittest.TestCase):
    """Q30: оговорка Mao et al. (2013) для строго нулевой солёности."""
    def test_core(self):
        exact = mao2013.co2_solubility(300.0, 500.0, 0.0)[0]
        author = mao2013.co2_solubility(300.0, 500.0, 0.0, numerics='author')[0]
        self.assertAlmostEqual(exact, 7.3783, delta=0.004)            # табл. 7 статьи: 573,15 K, 500 бар
        self.assertAlmostEqual(author, 4.984, delta=0.001)            # программа автора: высокотемпературный набор
        # на слабосолёные растворы оговорка не распространяется, сглаживания нет — скачок
        self.assertAlmostEqual(mao2013.co2_solubility(300.0, 500.0, 1e-6)[0], author, delta=0.001)
        # ниже 503 K наборы совпадают; выше 647 K оговорка не действует
        self.assertEqual(mao2013.co2_solubility(200.0, 500.0, 0.0)[0],
                         mao2013.co2_solubility(200.0, 500.0, 0.0, numerics='exact')[0])
        self.assertAlmostEqual(mao2013.co2_solubility(400.0, 800.0, 0.0)[0],
                               mao2013.co2_solubility(400.0, 800.0, 1e-9)[0], delta=1e-6)

    def test_warning_in_application(self):
        rows = [obs('Th_CO2', 25.0, homogenization_to='liquid', co2_purity_confirmed=True, carbonic_fraction_temp_c=25.0),
                obs('Tm_clath', 10.0, **Q2, carbonic_fraction_temp_c=25.0),
                obs('Th_total', 300.0, homogenization_to='liquid', carbonic_fraction_temp_c=25.0)]
        _, o = pvtx(rows)
        self.assertEqual(o.status, 'ok', o.message)
        self.assertEqual(o.extras['x_nacl'], 0.0)
        self.assertTrue(any('Солёность строго нулевая' in w and 'скачком' in w for w in o.warnings))


if __name__ == '__main__':
    unittest.main()
