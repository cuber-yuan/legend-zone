"""Render browser-test fixtures without starting the app, scheduler or database."""
from pathlib import Path
import sys
from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader

root = Path(__file__).resolve().parents[1]
output = Path(sys.argv[1])
output.mkdir(parents=True, exist_ok=True)
env = Environment(loader=FileSystemLoader(root / 'app/templates'), autoescape=True)
env.globals['url_for'] = lambda endpoint, **kwargs: (
    '/static/' + kwargs['filename'] if endpoint == 'static'
    else '/' + endpoint.replace('.', '/')
)
for status in ('playing', 'finished'):
    rendered = env.get_template('connect4.html').render(
        request=SimpleNamespace(path='/match/smoke', endpoint='main.match_view'),
        current_user=SimpleNamespace(is_authenticated=False), bots=[], match_id='smoke',
        match={'status': status, 'winner': 0 if status == 'finished' else None,
               'move_history': [{'x': 3, 'y': 5, 'player': 1}] if status == 'finished' else []},
    )
    (output / f'connect4-{status}.html').write_text(rendered, encoding='utf-8')
