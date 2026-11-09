# Происхождение исходных материалов валидации

Файлы в этом каталоге хранятся **без изменений** и используются только как источник данных и для
воспроизведения аудита. Программа FluidCalc их не импортирует.

## Аудит 2026-11-06

| Файл | SHA-256 |
|---|---|
| `FluidCalc_scientific_audit_2026-11-06.md` | `caea1489340305306c0b8d1c5602f4dbd8c4635a846c2a9f191d5839fa6eac49` |
| `FluidCalc_reference_checkpoints.csv` | `8d62f5a7b33c903c5ba48ea528b2da9513f48a65a9f206f7276c366c2d4fb9c4` |

Значения перенесены в `validation/checkpoints.csv`; соответствие проверяет `validation/test_checkpoints.py`.

## Пакет 2026-11-09 (`audit_2026-11-09/`)

Получен архивом `FluidCalc_validation_2026-11-09.zip`, SHA-256
`cc931db57c9a7213e702973e5efa972fe851aba682a8cd5ef1d2e251173be637`. Распакован без изменений.
Описание аудитора — `audit_2026-11-09/README_RU.md` (его ограничения действуют).

| Файл | Роль |
|---|---|
| `hall1988_experiments.csv` | Hall, Sterner & Bodnar (1988) через IUPAC SDS-47 (калибровочные данные Bodnar 1993) |
| `chen1972_experiments.csv` | Chen (1972b), табл. 5, со сверкой по Darling (1991), табл. 1 (калибровочные данные Darling 1991) |
| `nist_co2_raw.tsv` | неизменённая выгрузка NIST WebBook SRD 69, насыщение CO₂, 223,15–303,15 K |
| `nist_co2_mass.tsv` | та же выгрузка (побайтно идентична `nist_co2_raw.tsv`) |
| `nist_co2_checkpoints.csv` | расчёт аудитора по NIST |
| `reproduce_audit.py`, `summary.json`, `source_hashes.json` | воспроизведение аудита, итоги, хеши PDF-источников |
| `audit_repo/fluid_core/*.py` | копии ядра 0.2, прочитанные аудитором через GitHub — **только для воспроизведения**, не заменяют файлы программы |

### Проверка при приёме (2026-11-09)

1. Копии ядра в `audit_repo/` отличаются от рабочих `fluid_core/*.py` только завершающей пустой строкой
   (артефакт чтения через GitHub); после её удаления код идентичен. Рабочие файлы ядра не заменялись.
2. `reproduce_audit.py`, запущенный на копии пакета в лабораторной конфигурации (Python 3.11.18,
   CoolProp 8.0.0; аудитор использовал Python 3.12.14), дал `hall1988_experiments.csv`,
   `chen1972_experiments.csv` и `nist_co2_checkpoints.csv`, **побайтно идентичные** файлам архива.
   В `summary.json` различие только в последнем знаке среднего относительного отклонения Chen
   (1,3196512776194336 → …333), это порядок суммирования с плавающей точкой.
3. Входные данные (температура, состав, ошибки источника, принятые значения) перенесены в
   `validation/data/*.csv` без расчётных столбцов аудитора; NIST читается напрямую из `nist_co2_raw.tsv`.
   Совпадение с архивом проверяет `validation/test_datasets.py`.

## Эталонные прогоны программ авторов (2026-11-09)

Пользователь выполнил в Excel входные наборы `validation/oracle/*_inputs.csv` в программах
H2O-NaCl-CO2 (Steele-MacInnis, 2018) и HOKIEFLINCS_H2O-NACL (Steele-MacInnis et al., 2012) и вернул файл
`validation/oracle/Эталонные_расчёты_результаты.xlsx` (SHA-256
`d827d4ce3e7cec52976e9b12598e03ce6f8e5659d03f94907a35c23c9144b984`). Результаты перенесены без изменения в
`validation/data/sm2018_oracle.csv` (41 случай) и `validation/data/hokieflincs_oracle.csv` (22 случая).
Формулы HOKIEFLINCS прочитаны из присланной пользователем копии в формате .xlsx (SHA-256
`64433e90710dccea7a124a02c27adf852b04131ece0e037c4002a9499bbf41db`); сама программа в репозиторий не включена.
