"""Диагностическая интерпретация Te и Tm CO₂ (не количественный расчёт)."""
import unittest

from fluid_core import interpretation as I


def keys(r):
    return [c.key for c in r.candidates]


class TestTe(unittest.TestCase):
    def test_nacl_window_and_kcl_overlap(self):
        r = I.interpret_te(-21.2, 0.3)
        self.assertEqual(r.status, 'candidates_identified')
        self.assertIn('nacl_dominant', keys(r))
        self.assertTrue(any('NaCl–KCl' in w for w in r.warnings))
        self.assertFalse(r.indicates_multicomponent)
        # в области перекрытия возвращаются оба кандидата — выбор не делается
        self.assertEqual(keys(I.interpret_te(-22.0, 0.2)), ['nacl_dominant', 'nacl_kcl'])
        self.assertEqual(keys(I.interpret_te(-23.2, 0.2)), ['nacl_kcl'])

    def test_mg_and_fe_are_returned_together(self):
        for te in (-33.5, -35.0, -37.5):
            r = I.interpret_te(te, 0.5)
            self.assertEqual(keys(r), ['mgcl2_bearing', 'fecl2_bearing'], te)
            self.assertTrue(r.indicates_multicomponent)
            self.assertTrue(any('не различаются' in w for w in r.warnings))

    def test_cacl2_window(self):
        r = I.interpret_te(-51.0, 0.5)
        self.assertEqual(keys(r), ['cacl2_bearing'])
        self.assertTrue(r.indicates_multicomponent)

    def test_below_minus_55_no_salt_is_assigned(self):
        for te in (-55.1, -60.0, -75.0):
            r = I.interpret_te(te, 2.0)
            self.assertEqual(r.status, 'metastable_or_complex_system')
            self.assertEqual(r.candidates, ())
            self.assertTrue(r.indicates_multicomponent)
            self.assertIn('автоматически не назначаются', r.summary)

    def test_uncertainty_widens_the_match(self):
        self.assertEqual(I.interpret_te(-32.0, None).status, 'no_matching_window')
        self.assertEqual(keys(I.interpret_te(-32.0, 1.5)), ['mgcl2_bearing', 'fecl2_bearing'])
        self.assertEqual(I.interpret_te(-24.5, 0.2).status, 'no_matching_window')
        self.assertEqual(keys(I.interpret_te(-24.5, 1.0)), ['nacl_kcl'])
        self.assertTrue(any('Погрешность Te не указана' in w for w in I.interpret_te(-32.0).warnings))

    def test_metastable_nacl_note_and_unexplained_low_te(self):
        r = I.interpret_te(-28.0, 0.5)                      # в пределах ~15 °C ниже эвтектики H₂O–NaCl
        self.assertEqual(r.status, 'no_matching_window')
        self.assertFalse(r.indicates_multicomponent)
        self.assertTrue(any('метастабильное' in w for w in r.warnings))
        low = I.interpret_te(-45.0, 1.0)                    # ниже этого предела и вне окон
        self.assertEqual(low.status, 'no_matching_window')
        self.assertTrue(low.indicates_multicomponent)
        self.assertEqual(I.interpret_te(-10.0, 0.5).status, 'no_matching_window')
        self.assertIn('выше эвтектики', I.interpret_te(-10.0, 0.5).summary)

    def test_never_quantitative(self):
        for te in (-21.2, -35.0, -51.0, -60.0, -28.0, -5.0):
            r = I.interpret_te(te, 0.5)
            self.assertFalse(r.quantitative_composition_available)
            self.assertIn(I.TE_COMPOSITION_WARNING, r.warnings)
            self.assertEqual(r.kind, 'diagnostic_interpretation')
            self.assertEqual(len(r.limitations), 4)
        text = ' '.join(I.TE_LIMITATIONS)
        for needle in ('метастабильным', '15 °C', 'гидратов Ca и Mg', 'Baldassaro', '−196'):
            self.assertIn(needle, text)

    def test_recommended_data_excludes_available(self):
        full = I.interpret_te(-35.0, 0.5).recommended_data
        self.assertIn('Tm льда', full)
        self.assertIn('криогенная КР-спектроскопия', full)
        some = I.interpret_te(-35.0, 0.5, observations=['Tm_ice', 'Tm_hydrohalite']).recommended_data
        self.assertNotIn('Tm льда', some)
        self.assertNotIn('Tm гидрогалита', some)
        self.assertIn('отношения катионов (LA-ICP-MS)', some)

    def test_input_validation(self):
        with self.assertRaises(ValueError):
            I.interpret_te(-21.0, -1.0)
        with self.assertRaises(ValueError):
            I.interpret_te(float('nan'))
        with self.assertRaises(TypeError):
            I.interpret_te(True)


class TestTmCo2(unittest.TestCase):
    def test_reference_is_the_project_value(self):
        from fluid_core.co2 import TRIPLE_POINT_C
        self.assertAlmostEqual(I.CO2_TRIPLE_POINT_C, TRIPLE_POINT_C, delta=1e-9)
        self.assertEqual(I.CO2_TRIPLE_POINT_C, -56.558)

    def test_compatible_with_pure_co2(self):
        for tm in (-56.6, -56.558, -56.5):
            r = I.interpret_tm_co2(tm, 0.1)
            self.assertEqual(r.status, 'consistent_with_pure_CO2_within_measurement', tm)
        self.assertIn('не доказательство', I.interpret_tm_co2(-56.6, 0.1).summary)

    def test_depressed(self):
        r = I.interpret_tm_co2(-57.5, 0.2)
        self.assertEqual(r.status, 'volatile_impurity_suspected')
        self.assertAlmostEqual(r.difference_c, -0.942, delta=1e-9)
        self.assertIn('не различает', r.summary)
        self.assertTrue(any('КР-спектроскопии нет' in w for w in r.warnings))
        self.assertIsNone(r.mole_percent)
        self.assertFalse(r.quantitative_result_available)

    def test_above_reference_is_not_negative_impurity(self):
        r = I.interpret_tm_co2(-56.0, 0.2)
        self.assertEqual(r.status, 'calibration_or_transition_check_required')
        self.assertIn('калибровку', r.summary)
        self.assertIn('не трактуется', r.summary)

    def test_without_uncertainty_no_purity_statement(self):
        r = I.interpret_tm_co2(-57.5)
        self.assertEqual(r.status, 'uncertainty_not_specified')
        self.assertIn('вывод о чистоте CO₂ не делается', r.summary)

    def test_raman_single_second_component(self):
        for gas in ('CH4', 'N2'):
            ok = I.interpret_tm_co2(-58.0, 0.2, ['CO2', gas], th_co2_c=10.0, homogenization_direction='liquid')
            self.assertEqual(ok.status, 'data_sufficient_for_future_Thiery_binary_VX_model')
            self.assertEqual(ok.temperature_status, 'volatile_impurity_suspected')
            self.assertFalse(ok.quantitative_result_available)
            self.assertIsNone(ok.mole_percent)
            lacking = I.interpret_tm_co2(-58.0, 0.2, ['CO2', gas], th_co2_c=10.0)       # нет направления
            self.assertEqual(lacking.status, 'volatile_impurity_suspected')
            self.assertTrue(any('не хватает' in n for n in lacking.notes))
            crit = I.interpret_tm_co2(-58.0, 0.2, ['CO2', gas], th_co2_c=10.0, homogenization_direction='critical')
            self.assertEqual(crit.status, 'volatile_impurity_suspected')

    def test_raman_ternary(self):
        r = I.interpret_tm_co2(-59.0, 0.2, ['CO2', 'CH4', 'N2'], th_co2_c=5.0, homogenization_direction='vapor')
        self.assertEqual(r.status, 'ternary_requires_quantitative_Raman_and_mixture_EOS')
        self.assertFalse(r.quantitative_result_available)

    def test_raman_co2_only_but_depressed(self):
        r = I.interpret_tm_co2(-58.0, 0.2, ['CO2'])
        self.assertEqual(r.status, 'volatile_impurity_suspected')
        self.assertTrue(any('предел' in w for w in r.warnings))

    def test_input_validation(self):
        with self.assertRaises(ValueError):
            I.interpret_tm_co2(-57.0, 0.1, ['CO2', 'H2S'])
        with self.assertRaises(ValueError):
            I.interpret_tm_co2(-57.0, 0.1, homogenization_direction='up')
        with self.assertRaises(ValueError):
            I.interpret_tm_co2(-57.0, -0.1)


if __name__ == '__main__':
    unittest.main()
