#!/usr/bin/env python3
"""
Chaos Merchant Dashboard - Flask app for monitoring the pipeline and
tuning it without touching Terminal.

Run from the project root: python dashboard/app.py
Binds to 127.0.0.1 by default (see DASHBOARD_HOST/DASHBOARD_PORT in .env).
This is a single-user local tool with NO authentication - do not bind it
to 0.0.0.0 or expose it on a shared network without adding your own auth
in front of it, since the Settings page can read and write .env (API keys).
"""

import logging
import os
import sys
from pathlib import Path

# Run from the project root (python dashboard/app.py) - this makes the
# repo root importable (core.*, agents.*) the same way main.py's own
# working-directory convention already assumes.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from flask import Flask, render_template, request, redirect, url_for, jsonify, flash

import dashboard.data as data

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.getenv('DASHBOARD_SECRET_KEY', 'chaos-merchant-local-dashboard')

# Documented schedule (main.py's actual registrations) - the dashboard runs
# as its own process so it can't introspect a live scheduler instance; this
# is paired with real last-run data from data/job_tracker.json below.
SCHEDULED_JOBS = [
    {'name': 'trend_intelligence', 'schedule': 'Daily 07:00'},
    {'name': 'competitor_monitor', 'schedule': 'Every 3 hours'},
    {'name': 'analytics_feedback', 'schedule': 'Daily 09:00'},
    {'name': 'comment_mining', 'schedule': 'Weekly, Sunday 10:00'},
    {'name': 'thumbnail_research', 'schedule': 'Weekly, Sunday 10:00'},
]


@app.context_processor
def inject_nav():
    return {'nav_items': [
        ('home', 'Home'), ('output', 'Output'), ('analytics', 'Analytics'),
        ('trends', 'Trends'), ('research', 'Research'), ('settings', 'Settings'),
        ('logs', 'Logs')
    ]}


@app.route('/')
def home():
    job_status = data.get_job_status()
    jobs = [{**job, **job_status.get(job['name'], {})} for job in SCHEDULED_JOBS]

    publisher_flags = {
        'youtube': os.getenv('AUTO_POST_YOUTUBE', 'false').lower() == 'true',
        'tiktok': os.getenv('AUTO_POST_TIKTOK', 'false').lower() == 'true',
        'instagram': os.getenv('AUTO_POST_INSTAGRAM', 'false').lower() == 'true',
    }

    return render_template(
        'home.html',
        queue=data.get_input_queue(),
        checkpoints=data.get_checkpoints(),
        jobs=jobs,
        quota=data.get_quota_status(),
        cost=data.get_cost_summary(days=7),
        publisher_flags=publisher_flags,
        recent_batches=data.get_batches()[:5]
    )


@app.route('/output')
def output_list():
    return render_template('output.html', batches=data.get_batches())


@app.route('/output/<folder>')
def output_detail(folder):
    detail = data.get_batch_detail(folder)
    if detail is None:
        flash(f"Batch folder not found: {folder}", 'error')
        return redirect(url_for('output_list'))
    return render_template('output_detail.html', batch=detail)


@app.route('/audit')
def audit_page():
    return render_template(
        'audit.html',
        latest=data.get_latest_audit(),
        history=data.get_audit_batches()
    )


@app.route('/audit/<folder>')
def audit_detail_route(folder):
    detail = data.get_audit_detail(folder)
    if detail is None:
        flash(f"Audit report not found for: {folder}", 'error')
        return redirect(url_for('audit_page'))
    return render_template('audit_detail.html', audit=detail)


@app.route('/analytics')
def analytics_page():
    return render_template(
        'analytics.html',
        performance_log=data.get_performance_log(limit=200),
        top_hooks=data.get_top_hooks(limit=10),
        recent_shorts=data.get_recent_shorts(limit=20),
        cost=data.get_cost_summary(days=30)
    )


@app.route('/trends')
def trends_page():
    return render_template(
        'trends.html',
        brief=data.get_trend_brief(),
        alerts=data.get_competitor_alerts(limit=20),
        ideas=data.get_ideas_backlog(limit=30),
        competitors=data.get_competitors()
    )


@app.route('/trends/competitors/add', methods=['POST'])
def add_competitor_route():
    handle_or_url = request.form.get('handle_or_url', '').strip()
    category = request.form.get('category', 'gaming').strip() or 'gaming'
    if not handle_or_url:
        flash('Enter a channel handle or URL first.', 'error')
        return redirect(url_for('trends_page'))

    result = data.add_competitor(handle_or_url, category)
    if result:
        flash(f"Added competitor: {result.get('channel', handle_or_url)}", 'success')
    else:
        flash(f"Could not resolve channel: {handle_or_url} (check YOUTUBE_API_KEY and the handle/URL)", 'error')
    return redirect(url_for('trends_page'))


@app.route('/sources')
def sources_page():
    return render_template(
        'sources.html',
        source_config=data.get_source_config(),
        activity=data.get_sourcing_activity(limit=30)
    )


@app.route('/schedule')
def schedule_page():
    format_dist = data.get_format_distribution_7d()
    calendar = data.get_content_calendar()
    return render_template(
        'schedule.html',
        calendar=calendar,
        queue=data.get_posting_queue(limit=30),
        next_post=data.get_next_scheduled_post(),
        history=data.get_posting_history(limit=30),
        format_distribution=format_dist,
        format_distribution_total=sum(format_dist.values()),
        auto_post_enabled=data.get_auto_post_youtube_enabled()
    )


@app.route('/research')
def research_page():
    return render_template(
        'research.html',
        thumbnail_research=data.get_latest_thumbnail_research(),
        comment_insights=data.get_latest_comment_insights(),
        gap_report=data.get_content_gap_report()
    )


@app.route('/settings')
def settings_page():
    return render_template(
        'settings.html',
        env_content=data.read_env_file(),
        prompt_files=data.list_prompt_files()
    )


@app.route('/settings/env', methods=['POST'])
def save_env_route():
    content = request.form.get('env_content', '')
    data.write_env_file(content)
    flash('.env saved. Restart the pipeline/scheduler for changes to take effect.', 'success')
    return redirect(url_for('settings_page'))


@app.route('/settings/prompts/<name>')
def edit_prompt_route(name):
    content = data.read_prompt_file(name)
    if content is None:
        flash(f"Prompt file not found or invalid name: {name}", 'error')
        return redirect(url_for('settings_page'))
    return render_template('prompt_edit.html', name=name, content=content)


@app.route('/settings/prompts/<name>', methods=['POST'])
def save_prompt_route(name):
    content = request.form.get('content', '')
    if data.write_prompt_file(name, content):
        flash(f"Saved {name}", 'success')
    else:
        flash(f"Could not save {name} (invalid filename)", 'error')
    return redirect(url_for('settings_page'))


@app.route('/settings/prompts/new', methods=['POST'])
def new_prompt_route():
    name = request.form.get('new_name', '').strip()
    if name and not name.endswith('.txt'):
        name = f"{name}.txt"
    if not name or not data.write_prompt_file(name, ''):
        flash('Invalid prompt file name (must be a plain .txt filename).', 'error')
        return redirect(url_for('settings_page'))
    return redirect(url_for('edit_prompt_route', name=name))


@app.route('/logs')
def logs_page():
    return render_template('logs.html', lines=data.tail_log(300))


@app.route('/logs/data')
def logs_data():
    return jsonify({'lines': data.tail_log(300)})


if __name__ == '__main__':
    host = os.getenv('DASHBOARD_HOST', '127.0.0.1')
    port = int(os.getenv('DASHBOARD_PORT', '5050'))
    logger.info(f"🖥️  Chaos Merchant Dashboard starting on http://{host}:{port}")
    app.run(host=host, port=port, debug=False)
