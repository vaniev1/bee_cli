#!/usr/bin/env python3
"""Генератор HTML-отчёта по bench_result.json.

Используется автоматически из bench, либо вручную:
    python report.py [bench_result.json] [report.html]

Отчёт — один самодостаточный HTML-файл (без интернета и зависимостей):
шапка с железом, карточки средних, гистограмма tok/s по промптам, таблица.
"""
import html
import json
import os
import sys

CSS = """
:root{--bg:#0e0e13;--card:#16161f;--bd:#26262f;--tx:#f4f4f5;--mut:#9b9ba6;--honey:#fbbf24;--honey2:#f59e0b}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--tx);font-family:-apple-system,Segoe UI,Roboto,sans-serif;padding:32px;line-height:1.5}
.wrap{max-width:920px;margin:0 auto}
h1{font-size:26px;font-weight:800;letter-spacing:-.02em;margin-bottom:4px}
h1 .bee{display:inline-block;transform:scaleX(-1)}
.sub{color:var(--mut);font-size:14px;margin-bottom:24px}
.meta{background:var(--card);border:1px solid var(--bd);border-radius:14px;padding:16px 20px;margin-bottom:24px;
  display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px 24px;font-size:13px}
.meta div span{color:var(--mut);display:block;font-size:11px;text-transform:uppercase;letter-spacing:.05em;margin-bottom:2px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;margin-bottom:28px}
.card{background:var(--card);border:1px solid var(--bd);border-radius:14px;padding:18px 20px}
.card .v{font-size:30px;font-weight:800;background:linear-gradient(135deg,#fff,var(--honey));-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}
.card .l{color:var(--mut);font-size:12px;margin-top:4px}
h2{font-size:16px;margin:26px 0 14px;font-weight:700}
.bar{display:grid;grid-template-columns:240px 1fr 90px;align-items:center;gap:12px;margin-bottom:9px;font-size:13px}
.bar .lbl{color:var(--mut);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bar .track{background:#1d1d27;border-radius:6px;height:22px;overflow:hidden}
.bar .fill{height:100%;background:linear-gradient(90deg,var(--honey2),var(--honey));border-radius:6px}
.bar .val{text-align:right;font-variant-numeric:tabular-nums;font-weight:600}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:8px}
th,td{padding:8px 10px;text-align:right;border-bottom:1px solid var(--bd);font-variant-numeric:tabular-nums}
th{color:var(--mut);font-weight:600;text-transform:uppercase;font-size:11px;letter-spacing:.04em}
td:first-child,th:first-child{text-align:left}
.foot{color:var(--mut);font-size:12px;margin-top:28px;text-align:center}
"""


def _cards(s):
    out = [("avg_tps", "{:.1f}", "ток/с (средн.)"),
           ("avg_ttft", "{:.2f}s", "TTFT (средн.)"),
           ("avg_prefill", "{:.0f}", "prefill ток/с"),
           ("total_tokens", "{:.0f}", "всего токенов")]
    cards = []
    for key, fmt, label in out:
        if s.get(key) is not None:
            cards.append(f'<div class="card"><div class="v">{fmt.format(s[key])}</div><div class="l">{label}</div></div>')
    if s.get("peak_ram_gb"):
        cards.append(f'<div class="card"><div class="v">{s["peak_ram_gb"]:.2f}</div><div class="l">пик RAM, ГБ</div></div>')
    return "".join(cards)


def _bars(turns, labels):
    gen = [(labels[i], t) for i, t in enumerate(turns) if t.get("gen_tokens")]
    if not gen:
        return "<p style='color:var(--mut)'>Нет ходов с генерацией.</p>"
    mx = max(t["gen_tps"] for _, t in gen) or 1
    rows = []
    for label, t in gen:
        w = max(2, t["gen_tps"] / mx * 100)
        rows.append(
            f'<div class="bar"><div class="lbl" title="{html.escape(label)}">{html.escape(label)}</div>'
            f'<div class="track"><div class="fill" style="width:{w:.1f}%"></div></div>'
            f'<div class="val">{t["gen_tps"]:.1f} t/s</div></div>'
        )
    return "".join(rows)


def _table(turns, labels):
    head = "<tr><th>Промпт</th><th>tok/s</th><th>TTFT</th><th>роутер</th><th>prefill</th><th>токенов</th><th>думал</th></tr>"
    rows = [head]
    for i, t in enumerate(turns):
        if not t.get("gen_tokens"):
            continue
        rows.append(
            f"<tr><td>{html.escape(labels[i])}</td><td>{t['gen_tps']:.1f}</td>"
            f"<td>{t['ttft_s']:.2f}s</td><td>{t['router_s']:.2f}s</td>"
            f"<td>{t['prompt_tps']:.0f}</td><td>{t['gen_tokens']}</td>"
            f"<td>{'да' if t.get('think') else '—'}</td></tr>"
        )
    return "<table>" + "".join(rows) + "</table>"


def build_html(data: dict) -> str:
    sysinfo = data.get("system", {})
    cfg = data.get("config", {})
    summary = data.get("summary", {})
    turns = data.get("turns", [])
    labels = data.get("labels", [f"#{i+1}" for i in range(len(turns))])

    freq = f'{sysinfo["freq_mhz"]/1000:.1f} ГГц' if sysinfo.get("freq_mhz") else "—"
    ram = f'{sysinfo["ram_gb"]} ГБ' if sysinfo.get("ram_gb") else "—"
    meta = f"""
      <div><span>CPU</span>{html.escape(str(sysinfo.get('cpu','—')))}</div>
      <div><span>Ядра</span>{sysinfo.get('cores','—')}</div>
      <div><span>Макс. частота</span>{freq}</div>
      <div><span>RAM</span>{ram}</div>
      <div><span>ОС</span>{html.escape(str(sysinfo.get('os','—')))}</div>
      <div><span>Модель</span>{html.escape(str(cfg.get('model','—')))}</div>
      <div><span>Контекст</span>{cfg.get('ctx','—')} ток</div>
      <div><span>Потоки</span>{cfg.get('threads','—')}</div>
    """
    return f"""<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bee CLI — отчёт по метрикам</title><style>{CSS}</style></head>
<body><div class="wrap">
  <h1><span class="bee">🐝</span> Bee CLI — метрики</h1>
  <div class="sub">Бенчмарк локальной модели Bonsai-8B</div>
  <div class="meta">{meta}</div>
  <div class="cards">{_cards(summary)}</div>
  <h2>Скорость генерации по промптам</h2>
  {_bars(turns, labels)}
  <h2>Подробно</h2>
  {_table(turns, labels)}
  <div class="foot">Сгенерировано Bee CLI · откройте этот файл в браузере</div>
</div></body></html>"""


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "bench_result.json"
    dst = sys.argv[2] if len(sys.argv) > 2 else "report.html"
    if not os.path.exists(src):
        print(f"Нет файла {src}. Сначала запусти: ./run.sh bench")
        sys.exit(1)
    with open(src, encoding="utf-8") as f:
        data = json.load(f)
    with open(dst, "w", encoding="utf-8") as f:
        f.write(build_html(data))
    print(f"Отчёт: {dst}")


if __name__ == "__main__":
    main()
