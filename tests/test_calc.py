"""Слой расчёта приложения: вызывает ядро без изменения формул и блокирует неполные данные."""
import unittest

from fluid_core.salinity import bodnar_1993, darling_1991
from fluid_app import calc
from fluid_app.methods import _CORE_MESSAGES_RU, translate_core_message

try:
    import CoolProp  # noqa: F401
    HAVE_COOLPROP = True
except ImportError:
    HAVE_COOLPROP = False


def obs(kind, t, **kw):
    d = dict(kind=kind, temperature_c=t, uncertainty_c=None, homogenization_to=None, liquid_co2_present=None,
             vapor_co2_present=None, aqueous_brine_present=None, co2_purity_confirmed=None)
    d.update(kw)
    return d


PHASES = dict(liquid_co2_present=True, vapor_co2_present=True, aqueous_brine_present=True)


class TestDispatch(unittest.TestCase):
    def test_bodnar_identical_to_core(self):
        for t in (-0.1, -5, -10.3, -21.1):
            o = calc.calculate_observation(obs('Tm_ice', t))
            self.assertEqual(o.status, 'ok')
            self.assertEqual(o.value, bodnar_1993(t).salinity_wt_pct_nacl_eq + 0.0)
            self.assertEqual(o.doi, '10.1016/0016-7037(93)90378-A')

    def test_bodnar_zero_not_negative_zero(self):
        o = calc.calculate_observation(obs('Tm_ice', 0.0))
        self.assertEqual(str(o.value), '0.0')

    def test_bodnar_out_of_range_blocked(self):
        o = calc.calculate_observation(obs('Tm_ice', -24.5))
        self.assertEqual(o.status, 'error')
        self.assertIn('−21,1', o.message)
        self.assertIsNone(o.value)

    def test_darling_identical_to_core(self):
        o = calc.calculate_observation(obs('Tm_clath', 5.8, **PHASES))
        self.assertEqual(o.status, 'ok')
        self.assertEqual(o.value, darling_1991(5.8, **PHASES).salinity_wt_pct_nacl_eq)

    def test_darling_unknown_phase_not_assumed(self):
        o = calc.calculate_observation(obs('Tm_clath', 5.8, liquid_co2_present=True, vapor_co2_present=None,
                                           aqueous_brine_present=True))
        self.assertEqual(o.status, 'error')
        self.assertIn('Газовая CO₂', o.message)

    def test_darling_phase_absent_blocked(self):
        o = calc.calculate_observation(obs('Tm_clath', 5.8, liquid_co2_present=False, vapor_co2_present=True,
                                           aqueous_brine_present=True))
        self.assertEqual(o.status, 'error')
        self.assertTrue(o.message_original.startswith('Darling requires'))

    def test_co2_branch_not_chosen_automatically(self):
        o = calc.calculate_observation(obs('Th_CO2', 20, co2_purity_confirmed=True))
        self.assertEqual(o.status, 'error')
        self.assertIn('не выполняется', o.message)

    def test_co2_critical_homogenization_blocked(self):
        o = calc.calculate_observation(obs('Th_CO2', 20, homogenization_to='critical', co2_purity_confirmed=True))
        self.assertEqual(o.status, 'error')

    def test_co2_purity_required(self):
        o = calc.calculate_observation(obs('Th_CO2', 20, homogenization_to='liquid'))
        self.assertEqual(o.status, 'error')

    @unittest.skipUnless(HAVE_COOLPROP, 'CoolProp не установлен')
    def test_co2_result_and_warnings(self):
        o = calc.calculate_observation(obs('Th_CO2', 20, homogenization_to='liquid', co2_purity_confirmed=True))
        self.assertEqual(o.status, 'ok')
        self.assertEqual(o.unit, 'г/см³')
        self.assertIn('saturation_pressure_bar', o.extras)
        self.assertTrue(any('не давление' in w for w in o.warnings))
        lines = dict(calc.passport_lines(obs('Th_CO2', 20, homogenization_to='liquid', co2_purity_confirmed=True),
                                         o.__dict__))
        self.assertIn('Давление насыщения CO₂ P_sat, бар', lines)
        self.assertNotIn('давление минералообразования', lines['Результат'].lower())

    def test_record_only_kinds_skipped(self):
        o = calc.calculate_observation(obs('Th_total', 250))
        self.assertEqual(o.status, 'skipped')
        self.assertIsNone(o.value)

    def test_te_and_tm_co2_are_interpreted_not_calculated(self):
        """Te и Tm CO₂ больше не «только регистрация»: выдаётся диагностическая интерпретация без числа."""
        from fluid_app.methods import method_category, status_label
        for k in ('Tm_CO2', 'Te'):
            o = calc.calculate_observation(obs(k, -56.6))
            self.assertEqual(o.status, 'ok')
            self.assertIsNone(o.value)
            self.assertEqual(method_category(o.method_key), 'interpretation')
            self.assertEqual(status_label(o.status, o.method_key), 'интерпретация (не расчёт)')
            self.assertEqual(o.extras['category'], 'interpretation')

    def test_missing_temperature(self):
        o = calc.calculate_observation(obs('Tm_ice', None))
        self.assertEqual(o.status, 'error')

    def test_unknown_kind(self):
        self.assertEqual(calc.calculate_observation(obs('XYZ', 1)).status, 'error')

    def test_sensitivity_range(self):
        o = calc.calculate_observation(obs('Tm_ice', -5, uncertainty_c=0.2))
        self.assertAlmostEqual(o.extras['sensitivity_t_minus_u'], bodnar_1993(-5.2).salinity_wt_pct_nacl_eq)
        self.assertAlmostEqual(o.extras['sensitivity_t_plus_u'], bodnar_1993(-4.8).salinity_wt_pct_nacl_eq)

    def test_sensitivity_partial_at_range_edge(self):
        o = calc.calculate_observation(obs('Tm_ice', -0.1, uncertainty_c=0.2))
        self.assertIsNone(o.extras['sensitivity_t_plus_u'])
        self.assertTrue(o.warnings)

    def test_passport_contains_source_and_limits(self):
        o = calc.calculate_observation(obs('Tm_ice', -5))
        keys = [k for k, _ in calc.passport_lines(obs('Tm_ice', -5), o.__dict__)]
        for k in ('Источник', 'DOI', 'Область применимости', 'Допущения', 'Ограничения', 'Уравнение / модель'):
            self.assertIn(k, keys)


class TestTranslations(unittest.TestCase):
    def test_core_errors_are_translated(self):
        """Каждое известное сообщение ядра, возникающее при отказе, имеет русский перевод."""
        from fluid_core.co2 import pure_co2_saturation, CRITICAL_POINT_C
        cases = [
            lambda: bodnar_1993(-30), lambda: bodnar_1993(float('nan')), lambda: bodnar_1993(True),
            lambda: darling_1991(20, **PHASES),
            lambda: darling_1991(5, liquid_co2_present=False, vapor_co2_present=True, aqueous_brine_present=True),
            lambda: pure_co2_saturation(20, 'x', co2_purity_confirmed=True),
            lambda: pure_co2_saturation(20, 'liquid', co2_purity_confirmed=False),
            lambda: pure_co2_saturation(-60, 'liquid', co2_purity_confirmed=True),
            lambda: pure_co2_saturation(40, 'liquid', co2_purity_confirmed=True),
            lambda: pure_co2_saturation(CRITICAL_POINT_C - 0.05, 'liquid', co2_purity_confirmed=True),
        ]
        for fn in cases:
            try:
                fn()
            except (ValueError, TypeError) as exc:
                self.assertIn(str(exc), _CORE_MESSAGES_RU, str(exc))
                self.assertNotEqual(translate_core_message(str(exc)), str(exc))
            else:
                self.fail('ожидалась ошибка')


@unittest.skipUnless(HAVE_COOLPROP, 'CoolProp не установлен')
class TestCoolPropRegression(unittest.TestCase):
    """Регрессионный снимок CoolProp 8.0.0 (Span & Wagner 1996).

    ВНИМАНИЕ: это НЕ независимая валидация — значения получены той же библиотекой.
    Тест фиксирует воспроизводимость при обновлении CoolProp. Сверка с таблицами
    NIST/REFPROP остаётся открытым пунктом docs/SCIENTIFIC_AUDIT.md.
    """
    SNAPSHOT = {  # T, °C: (rho_liq, rho_vap г/см³, P_sat бар)
        0: (0.927432, 0.097647, 34.85141),
        10: (0.861120, 0.135156, 45.02183),
        20: (0.773387, 0.194202, 57.29053),
        25: (0.710502, 0.242732, 64.34244),
        30: (0.593313, 0.345102, 72.13687),
    }

    def test_snapshot(self):
        from fluid_core.co2 import pure_co2_saturation
        for t, (rl, rv, p) in self.SNAPSHOT.items():
            l = pure_co2_saturation(t, 'liquid', co2_purity_confirmed=True)
            v = pure_co2_saturation(t, 'vapor', co2_purity_confirmed=True)
            self.assertAlmostEqual(l.density_g_cm3, rl, delta=2e-6)
            self.assertAlmostEqual(v.density_g_cm3, rv, delta=2e-6)
            self.assertAlmostEqual(l.saturation_pressure_bar, p, delta=2e-4)


if __name__ == '__main__':
    unittest.main()
