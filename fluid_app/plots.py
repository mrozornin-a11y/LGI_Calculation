"""Простые графики без интерпретаций: Th–солёность и распределения по образцам/FIA.

Используется только matplotlib.figure.Figure (без pyplot) — работает без дисплея.
Данные берутся из одного сохранённого расчёта, поэтому график воспроизводим.
"""
from __future__ import annotations

from collections import OrderedDict, defaultdict
from statistics import mean

from matplotlib.figure import Figure

# Категориальная палитра (фиксированный порядок, не циклится); 9-я и далее группы → «Прочие»
PALETTE = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948']
OTHER_COLOR = '#8a8986'
MARKERS = ['o', 's', 'D', '^', 'v', 'P', 'X', 'h']
TEXT = '#0b0b0b'
TEXT2 = '#52514e'
GRID = '#e4e3df'

PLOT_TYPES = OrderedDict([
    ('th_salinity', 'Th общ. — солёность'),
    ('hist_th_total', 'Распределение Th общ.'),
    ('hist_salinity', 'Распределение солёности'),
    ('hist_th_co2', 'Распределение Th CO₂'),
])
GROUP_BY = OrderedDict([('sample', 'по образцам'), ('fia', 'по FIA'), ('none', 'без группировки')])
SALINITY_METHODS = {'bodnar_1993': 'Bodnar (1993), Tm лёд', 'darling_1991': 'Darling (1991), Tm клатрат'}


def _group_key(r: dict, group_by: str) -> str:
    if group_by == 'sample':
        return r.get('sample_name') or '—'
    if group_by == 'fia':
        fia = r.get('fia_name')
        return f'{r.get("sample_name")} / {fia}' if fia else f'{r.get("sample_name")} / FIA не указана'
    return 'Все включения'


def _inclusion_key(r: dict):
    return (r.get('project_name'), r.get('sample_name'), r.get('inclusion_name'))


def _style(ax):
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)
    for s in ('left', 'bottom'):
        ax.spines[s].set_color('#b5b4ae')
    ax.tick_params(colors=TEXT2, labelsize=9)


def _colors(groups: list[str]) -> dict[str, str]:
    return {g: (PALETTE[i] if i < len(PALETTE) else OTHER_COLOR) for i, g in enumerate(groups)}


def _fold_groups(data: dict[str, list]) -> 'OrderedDict[str, list]':
    groups = sorted(data)
    out: OrderedDict[str, list] = OrderedDict()
    for i, g in enumerate(groups):
        if i < len(PALETTE):
            out[g] = list(data[g])
        else:
            out.setdefault('Прочие', []).extend(data[g])
    return out


def th_salinity_points(results: list[dict], group_by: str):
    """Точки (солёность, Th) по включениям. При повторных измерениях — среднее."""
    th = defaultdict(list)
    sal = defaultdict(lambda: defaultdict(list))
    meta = {}
    for r in results:
        key = _inclusion_key(r)
        meta[key] = r
        if r['kind'] == 'Th_total' and r['inputs'].get('temperature_c') is not None:
            th[key].append(r['inputs']['temperature_c'])
        if r['status'] == 'ok' and r.get('method_key') in SALINITY_METHODS:
            sal[key][r['method_key']].append(r['value'])
    points = defaultdict(list)    # (group, method) -> [(x, y, n_th, n_sal)]
    replicated = 0
    for key, by_method in sal.items():
        if key not in th:
            continue
        for method, values in by_method.items():
            if len(values) > 1 or len(th[key]) > 1:
                replicated += 1
            points[(_group_key(meta[key], group_by), method)].append((mean(values), mean(th[key])))
    return points, replicated


def make_figure(plot_type: str, results: list[dict], group_by: str = 'sample', run: dict | None = None) -> Figure:
    fig = Figure(figsize=(8, 5.5), dpi=100, layout='constrained')
    fig.patch.set_facecolor('white')
    if plot_type == 'th_salinity':
        _th_salinity(fig, results, group_by)
    else:
        _histograms(fig, plot_type, results, group_by)
    if run:
        fig.text(0.995, 0.003, f'Расчёт № {run["id"]} от {run["created_at"]} UTC; FluidCalc {run["app_version"]}',
                 ha='right', va='bottom', fontsize=7, color=TEXT2)
    return fig


def _empty(fig, text):
    ax = fig.add_subplot()
    ax.axis('off')
    ax.text(0.5, 0.5, text, ha='center', va='center', fontsize=11, color=TEXT2, wrap=True)


def _th_salinity(fig: Figure, results, group_by):
    points, replicated = th_salinity_points(results, group_by)
    if not points:
        _empty(fig, 'Нет включений, у которых в этом расчёте есть одновременно\n'
                    'Th общ. и рассчитанная солёность (Bodnar или Darling).')
        return
    ax = fig.add_subplot()
    _style(ax)
    groups = list(_fold_groups({g: [] for g, _ in points}).keys())
    folded = {g: (g if g in groups else 'Прочие') for g, _ in points}
    colors = _colors(groups)
    method_marker = {'bodnar_1993': 'o', 'darling_1991': '^'}
    n = 0
    for (g, method), pts in sorted(points.items()):
        xs, ys = zip(*pts)
        n += len(pts)
        ax.scatter(xs, ys, s=70, marker=method_marker[method], color=colors[folded[g]],
                   edgecolors='white', linewidths=1.2, zorder=3)
    # легенда: цвет — группа, форма — методика
    from matplotlib.lines import Line2D
    handles = [Line2D([], [], marker='s', linestyle='', color=colors[g], markersize=8, label=g) for g in groups]
    handles += [Line2D([], [], marker=m, linestyle='', color=TEXT2, markersize=8, label=SALINITY_METHODS[k])
                for k, m in method_marker.items() if any(k == mm for _, mm in points)]
    ax.legend(handles=handles, fontsize=8, frameon=False, loc='best')
    ax.set_xlabel('Солёность, мас. % NaCl-экв.', color=TEXT)
    ax.set_ylabel('Th общ., °C', color=TEXT)
    ax.set_title(f'Th общ. — солёность (n = {n})', color=TEXT, fontsize=12, loc='left')
    note = 'Солёность — NaCl-эквивалент; Th не пересчитана в температуру образования.'
    if replicated:
        note += f' При повторных измерениях взято среднее ({replicated} случ.).'
    fig.text(0.005, 0.003, note, ha='left', va='bottom', fontsize=7, color=TEXT2)


def _histograms(fig: Figure, plot_type, results, group_by):
    data: dict[str, list[float]] = defaultdict(list)
    if plot_type == 'hist_salinity':
        for r in results:
            if r['status'] == 'ok' and r.get('method_key') in SALINITY_METHODS:
                data[_group_key(r, group_by)].append(r['value'])
        xlabel, title = 'Солёность, мас. % NaCl-экв.', 'Распределение солёности (Bodnar и Darling вместе)'
    else:
        kind = 'Th_total' if plot_type == 'hist_th_total' else 'Th_CO2'
        for r in results:
            t = r['inputs'].get('temperature_c')
            if r['kind'] == kind and t is not None:
                data[_group_key(r, group_by)].append(t)
        xlabel = 'Th общ., °C' if kind == 'Th_total' else 'Th CO₂, °C'
        title = f'Распределение {xlabel.split(",")[0]} (зарегистрированные значения)'
    if not data:
        _empty(fig, 'В выбранном расчёте нет данных для этого графика.')
        return
    groups = _fold_groups(data)
    colors = _colors(list(groups))
    all_v = [v for vs in groups.values() for v in vs]
    lo, hi = min(all_v), max(all_v)
    if hi == lo:
        lo, hi = lo - 0.5, hi + 0.5
    bins = min(30, max(5, int(len(all_v) ** 0.5) + 2))
    edges = [lo + (hi - lo) * i / bins for i in range(bins + 1)]
    axes = fig.subplots(len(groups), 1, sharex=True, squeeze=False)[:, 0]
    for ax, (g, vals) in zip(axes, groups.items()):
        _style(ax)
        ax.hist(vals, bins=edges, color=colors[g], edgecolor='white', linewidth=1.0)
        ax.set_ylabel('n', color=TEXT2, fontsize=9)
        ax.set_title(f'{g} (n = {len(vals)})', color=TEXT, fontsize=9, loc='left')
        ax.yaxis.get_major_locator().set_params(integer=True)
    axes[-1].set_xlabel(xlabel, color=TEXT)
    fig.suptitle(title, color=TEXT, fontsize=12, x=0.01, ha='left')


def save_figure(fig: Figure, path: str) -> None:
    fmt = 'svg' if str(path).lower().endswith('.svg') else 'png'
    fig.savefig(path, format=fmt, dpi=200 if fmt == 'png' else None, facecolor='white')
