import unittest
from fluid_core.salinity import bodnar_1993, darling_1991, mixture_density_simple
from fluid_core.co2 import pure_co2_saturation, CRITICAL_POINT_C

class TestSalinity(unittest.TestCase):
    def test_bodnar_formula(self):
        self.assertAlmostEqual(bodnar_1993(-5).salinity_wt_pct_nacl_eq,7.864625,places=6)
        self.assertAlmostEqual(bodnar_1993(-10).salinity_wt_pct_nacl_eq,13.937,places=6)
    def test_bodnar_range(self):
        with self.assertRaises(ValueError):bodnar_1993(-30)
    def test_darling_formula(self):
        a=darling_1991(5.8,liquid_co2_present=True,vapor_co2_present=True,aqueous_brine_present=True)
        self.assertAlmostEqual(a.salinity_wt_pct_nacl_eq,7.780310544,places=7)
    def test_darling_phase_gate(self):
        with self.assertRaises(ValueError):
            darling_1991(5.8,liquid_co2_present=False,vapor_co2_present=True,aqueous_brine_present=True)
    def test_balance(self):
        self.assertAlmostEqual(mixture_density_simple(.81,.86,.2,same_temperature_pressure=True),.85)
    def test_balance_requires_same_tp(self):
        with self.assertRaises(ValueError):mixture_density_simple(.81,.86,.2,same_temperature_pressure=False)

class TestCO2(unittest.TestCase):
    def test_missing_branch(self):
        with self.assertRaises(ValueError):pure_co2_saturation(20,'unknown',co2_purity_confirmed=True)
    def test_missing_purity_confirmation(self):
        with self.assertRaises(ValueError):pure_co2_saturation(20,'liquid',co2_purity_confirmed=False)
    def test_above_critical(self):
        with self.assertRaises(ValueError):pure_co2_saturation(40,'liquid',co2_purity_confirmed=True)
    def test_near_critical(self):
        with self.assertRaises(ValueError):pure_co2_saturation(CRITICAL_POINT_C-0.05,'vapor',co2_purity_confirmed=True)
    def test_below_triple(self):
        with self.assertRaises(ValueError):pure_co2_saturation(-60,'vapor',co2_purity_confirmed=True)
    def test_backend_saturation_properties(self):
        try: import CoolProp
        except ImportError: self.skipTest('CoolProp not installed: backend numerical test pending')
        l = pure_co2_saturation(20,'liquid',co2_purity_confirmed=True)
        v = pure_co2_saturation(20,'vapor',co2_purity_confirmed=True)
        self.assertGreater(l.density_g_cm3,v.density_g_cm3)
        self.assertAlmostEqual(l.saturation_pressure_bar,v.saturation_pressure_bar,places=5)
        self.assertGreater(l.saturation_pressure_bar,0)
        # independent mass-volume consistency, not an independent EOS reference
        self.assertAlmostEqual(l.density_g_cm3*l.molar_volume_cm3_mol,44.0095,delta=.02)

if __name__=='__main__':unittest.main()
