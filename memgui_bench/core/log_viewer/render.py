"""HTML rendering helpers for the MemGUI-Bench log viewer."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Callable
from urllib.parse import quote

from .data import calculate_stats, find_session_dirs, load_session, load_task_detail, rel_to_root

FileUrl = Callable[[Path], str]
TaskUrl = Callable[[str, str, int], str]


CSS = """
:root { color-scheme: light; --bg: #f7f8fb; --panel: #fff; --ink: #17202a; --muted: #667085; --line: #d9dee8; --accent: #2364aa; --ok: #0f8a5f; --bad: #b42318; --warn: #b54708; }
* { box-sizing: border-box; }
body { margin: 0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: var(--ink); background: var(--bg); }
a { color: var(--accent); text-decoration: none; }
.shell { max-width: 1440px; margin: 0 auto; padding: 28px; }
.topbar { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 22px; }
.eyebrow { color: var(--muted); font-size: 13px; text-transform: uppercase; letter-spacing: .08em; }
h1 { margin: 4px 0 6px; font-size: 32px; line-height: 1.15; }
h2 { margin: 0 0 12px; font-size: 20px; }
h3 { margin: 0 0 8px; font-size: 16px; }
.muted { color: var(--muted); }
.toolbar { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
.button { border: 1px solid var(--line); background: #fff; border-radius: 6px; padding: 9px 12px; color: var(--ink); }
.grid { display: grid; gap: 14px; }
.stats { grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); margin-bottom: 18px; }
.stat { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 16px; }
.stat .value { font-size: 26px; font-weight: 720; margin-top: 4px; }
.panel { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 18px; margin-bottom: 18px; }
.search { width: min(480px, 100%); border: 1px solid var(--line); border-radius: 6px; padding: 10px 12px; font-size: 14px; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th, td { padding: 11px 10px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
th { color: var(--muted); font-weight: 650; background: #fbfcfe; position: sticky; top: 0; }
.task-desc { max-width: 520px; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { display: inline-flex; align-items: center; gap: 5px; border: 1px solid var(--line); border-radius: 999px; padding: 3px 8px; font-size: 12px; color: var(--muted); background: #fff; }
.status { font-weight: 700; }
.success { color: var(--ok); }
.failure, .error { color: var(--bad); }
.executed { color: var(--warn); }
.pending { color: var(--muted); }
.attempts { display: flex; flex-wrap: wrap; gap: 6px; }
.attempt { border: 1px solid var(--line); border-radius: 6px; padding: 5px 7px; font-size: 12px; background: #fff; }
.two-col { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(320px, .65fr); gap: 18px; align-items: start; }
.media-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 14px; }
.step-card { border: 1px solid var(--line); border-radius: 8px; background: #fff; overflow: hidden; }
.step-card img, .puzzle img { width: 100%; height: auto; display: block; background: #eef1f6; }
.step-body { padding: 12px; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; background: #101828; color: #eef4ff; padding: 12px; border-radius: 6px; font-size: 12px; line-height: 1.5; max-height: 420px; overflow: auto; }
.kv { display: grid; grid-template-columns: 140px 1fr; gap: 8px 12px; font-size: 14px; }
.kv div:nth-child(odd) { color: var(--muted); }
.sessions { grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); }
@media (max-width: 900px) { .shell { padding: 18px; } .topbar, .two-col { display: block; } table { font-size: 13px; } .task-desc { max-width: unset; } }
"""


def page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>{CSS}</style>
</head>
<body>{body}</body>
</html>"""


def render_sessions(parent: Path, session_url: Callable[[Path], str]) -> str:
    sessions = find_session_dirs(parent)
    cards = []
    for session in sessions:
        stats = calculate_stats(session)
        cards.append(
            f"""<a class="stat" href="{html.escape(session_url(session))}">
  <div class="eyebrow">{html.escape(session.name)}</div>
  <div class="value">{stats['success_rate']:.1f}%</div>
  <div class="muted">{stats['success']}/{stats['total']} success, {stats['executed']} executed</div>
</a>"""
        )
    body = f"""<main class="shell">
  <div class="topbar">
    <div><div class="eyebrow">MemGUI-Bench Logs</div><h1>Select A Session</h1><div class="muted">{html.escape(str(parent))}</div></div>
  </div>
  <section class="grid sessions">{''.join(cards) or '<div class="panel">No MemGUI sessions found.</div>'}</section>
</main>"""
    return page("MemGUI-Bench Logs", body)


def _metric_value(metrics: dict, key: str, fallback: str = "-") -> str:
    value = metrics.get(key, fallback)
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def render_index(log_root: Path, task_url: TaskUrl) -> str:
    session = load_session(log_root)
    stats = calculate_stats(log_root)
    metrics = session["metrics"]
    cards = [
        ("Tasks", str(stats["total"])),
        ("Executed", str(stats["executed"])),
        ("Success", f"{stats['success_rate']:.1f}%"),
        ("Memory SR", f"{stats['memory_success_rate']:.1f}%"),
        ("Avg Steps", f"{stats['avg_steps']:.1f}"),
        ("Pass@1", _metric_value(metrics, "pass_at_1", "-")),
    ]
    card_html = "".join(
        f'<div class="stat"><div class="eyebrow">{html.escape(label)}</div><div class="value">{html.escape(value)}</div></div>'
        for label, value in cards
    )

    rows = []
    for task in session["tasks"]:
        attempts_html = []
        for agent, attempts in task["attempts"].items():
            for attempt in attempts:
                if not attempt["has_log"] and attempt["status"] == "pending":
                    continue
                cls = attempt["status"]
                href = task_url(task["id"], agent, attempt["attempt"])
                attempts_html.append(
                    f'<a class="attempt {cls}" href="{html.escape(href)}">{html.escape(agent)} #{attempt["attempt"]} {html.escape(attempt["status"])}</a>'
                )
        apps = "".join(f'<span class="chip">{html.escape(app)}</span>' for app in task["apps"])
        rows.append(
            f"""<tr data-filter="{html.escape((task['id'] + ' ' + task['description'] + ' ' + ' '.join(task['apps']) + ' ' + task['best_status']).lower())}">
  <td><strong>{html.escape(task['id'])}</strong><div class="chips">{apps}</div></td>
  <td class="task-desc">{html.escape(task['description'])}</td>
  <td>{'Y' if task['memory'] else 'N'}</td>
  <td>{html.escape(str(task['difficulty']))}</td>
  <td><span class="status {task['best_status']}">{html.escape(task['best_status'])}</span></td>
  <td><div class="attempts">{''.join(attempts_html) or '<span class="muted">No logs</span>'}</div></td>
</tr>"""
        )

    body = f"""<main class="shell">
  <div class="topbar">
    <div>
      <div class="eyebrow">MemGUI-Bench Session</div>
      <h1>{html.escape(session['name'])}</h1>
      <div class="muted">{html.escape(str(session['root']))}</div>
    </div>
    <div class="toolbar"><a class="button" href="?refresh=1">Refresh</a></div>
  </div>
  <section class="grid stats">{card_html}</section>
  <section class="panel">
    <div class="topbar">
      <h2>Tasks</h2>
      <input id="filter" class="search" placeholder="Filter by task, app, status..." oninput="filterRows()">
    </div>
    <table>
      <thead><tr><th>Task</th><th>Description</th><th>Memory</th><th>Diff</th><th>Status</th><th>Attempts</th></tr></thead>
      <tbody id="taskRows">{''.join(rows)}</tbody>
    </table>
  </section>
</main>
<script>
function filterRows() {{
  const q = document.getElementById('filter').value.toLowerCase();
  document.querySelectorAll('#taskRows tr').forEach(row => {{
    row.style.display = row.dataset.filter.includes(q) ? '' : 'none';
  }});
}}
</script>"""
    return page(f"MemGUI Logs - {session['name']}", body)


def _json_block(title: str, value: object) -> str:
    if not value:
        return ""
    return f"<h3>{html.escape(title)}</h3><pre>{html.escape(json.dumps(value, ensure_ascii=False, indent=2))}</pre>"


def _action_text(step: dict) -> str:
    action = step.get("action", "")
    if isinstance(action, list) and action:
        return json.dumps(action, ensure_ascii=False)
    if isinstance(action, dict):
        return json.dumps(action, ensure_ascii=False)
    return str(action)


def _description_for(descriptions: dict, step_num: int) -> object:
    for key in (step_num, str(step_num)):
        if key in descriptions:
            return descriptions[key]
    return None


def render_task(log_root: Path, task_id: str, agent: str, attempt: int, file_url: FileUrl, index_url: str) -> str:
    detail = load_task_detail(log_root, task_id, agent, attempt)
    task = detail["task"] or {"id": task_id, "description": "", "apps": []}
    directory = detail["directory"]
    steps = []
    single_by_step = {int(path.stem.split("_")[-1]): path for path in detail["single_actions"] if path.stem.split("_")[-1].isdigit()}
    visual_by_step = {int(path.stem.split("_")[-1]): path for path in detail["visual_actions"] if path.stem.split("_")[-1].isdigit()}
    screen_by_step = {int(path.stem): path for path in detail["screenshots"] if path.stem.isdigit()}

    for step in detail["step_logs"]:
        step_num = int(step.get("step", len(steps) + 1))
        image = single_by_step.get(step_num) or visual_by_step.get(step_num) or screen_by_step.get(max(step_num - 1, 0))
        image_html = f'<img src="{html.escape(file_url(image))}" alt="Step {step_num}">' if image else ""
        desc = _description_for(detail["descriptions"], step_num)
        desc_html = _json_block("Evaluator Description", desc)
        steps.append(
            f"""<article class="step-card" id="step-{step_num}">
  {image_html}
  <div class="step-body">
    <h3>Step {step_num}</h3>
    <div class="muted">{html.escape(_action_text(step))}</div>
    {desc_html}
  </div>
</article>"""
        )

    if not steps:
        for image in detail["screenshots"]:
            step_num = int(image.stem)
            steps.append(
                f"""<article class="step-card" id="screen-{step_num}">
  <img src="{html.escape(file_url(image))}" alt="Screenshot {step_num}">
  <div class="step-body"><h3>Screenshot {step_num}</h3></div>
</article>"""
            )

    puzzles = "".join(
        f'<div class="puzzle panel"><h3>{html.escape(path.name)}</h3><img src="{html.escape(file_url(path))}" alt="{html.escape(path.name)}"></div>'
        for path in detail["puzzles"]
    )

    summary = detail["summary"]
    final = detail["final_decision"]
    eval_summary = detail["evaluation_summary"]
    status = eval_summary.get("final_result", final.get("decision", "-"))
    reason = eval_summary.get("reason") or final.get("reason") or ""

    stdout = detail["files"].get("stdout") or ""
    stderr = detail["files"].get("stderr") or ""
    logs_html = ""
    if stdout:
        logs_html += f"<h3>stdout.txt</h3><pre>{html.escape(stdout)}</pre>"
    if stderr:
        logs_html += f"<h3>stderr.txt</h3><pre>{html.escape(stderr)}</pre>"

    apps = "".join(f'<span class="chip">{html.escape(app)}</span>' for app in task.get("apps", []))
    body = f"""<main class="shell">
  <div class="topbar">
    <div>
      <div class="eyebrow"><a href="{html.escape(index_url)}">Back to session</a></div>
      <h1>{html.escape(task_id)} / {html.escape(agent)} / attempt {attempt}</h1>
      <div class="chips">{apps}</div>
    </div>
  </div>
  <section class="panel">
    <h2>Task</h2>
    <p>{html.escape(task.get('description', ''))}</p>
    <div class="kv">
      <div>Directory</div><div>{html.escape(str(directory))}</div>
      <div>Final Result</div><div>{html.escape(str(status))}</div>
      <div>Total Steps</div><div>{html.escape(str(summary.get('total_steps', '-')))}</div>
      <div>Reason</div><div>{html.escape(str(reason))}</div>
    </div>
  </section>
  <div class="two-col">
    <section>
      <div class="media-grid">{''.join(steps) or '<div class="panel">No screenshots or steps found.</div>'}</div>
    </section>
    <aside>
      {_json_block('Execution Summary', summary)}
      {_json_block('Final Decision', final)}
      {_json_block('Evaluation Summary', eval_summary)}
      {_json_block('IRR Analysis', detail['irr'])}
      {_json_block('BadCase Analysis', detail['badcase'])}
      {_json_block('Error', detail['error'])}
      {logs_html}
    </aside>
  </div>
  {puzzles}
</main>"""
    return page(f"{task_id} - {agent} attempt {attempt}", body)

