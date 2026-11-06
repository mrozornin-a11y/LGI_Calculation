"""Проверка окружения FluidCalc без обращения к сети: версии, glibc, импорт библиотек, CoolProp."""
import importlib
import os
import platform
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print(f'Python:     {sys.version.split()[0]} ({sys.executable})')
print(f'Платформа:  {platform.platform()}')
libc = platform.libc_ver()
print(f'glibc:      {libc[1] if libc[0] == "glibc" else "не определена"}')
status = 0
for mod, attr in (('PySide6', '__version__'), ('CoolProp', '__version__'), ('matplotlib', '__version__'),
                  ('openpyxl', '__version__'), ('numpy', '__version__'), ('scipy', '__version__'),
                  ('pandas', '__version__')):
    try:
        m = importlib.import_module(mod)
        print(f'{mod:11s} {getattr(m, attr, "?")}')
    except Exception as exc:  # noqa: BLE001
        need = mod in ('PySide6', 'CoolProp', 'matplotlib', 'openpyxl')
        print(f'{mod:11s} НЕ ДОСТУПЕН ({exc}){" — обязателен" if need else " — не обязателен"}')
        status |= need
try:
    from fluid_core.co2 import pure_co2_saturation
    r = pure_co2_saturation(20.0, 'liquid', co2_purity_confirmed=True)
    print(f'Проверка CoolProp: ρ(CO₂, ж, 20 °C) = {r.density_g_cm3:.6f} г/см³, P_sat = {r.saturation_pressure_bar:.4f} бар')
except Exception as exc:  # noqa: BLE001
    print(f'Проверка CoolProp: ОШИБКА {exc}')
    status = 1
from fluid_app import __version__
import fluid_core
print(f'FluidCalc:  {__version__}; ядро fluid_core {fluid_core.__version__}')
sys.exit(status)
