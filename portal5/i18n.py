# i18n.py
# Copyright (C) 2020  Tony Wu <tony[dot]wu(at)nyu[dot]edu>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import subprocess
from pathlib import Path

import click
from flask import Flask, g, request
from flask_babel import Babel

babel = Babel()
TRANSLATIONS = f'{Path(__file__).parent}/translations'


def setup_languages(app: Flask):
    babel.init_app(app)

    @babel.localeselector
    def get_locale():
        lang = (
            getattr(g, '_lang', None)
            or request.args.get('lang', None)
            or request.accept_languages.best_match(app.config['LANGUAGES'])
        )
        return lang and lang.replace('-', '_')

    app.jinja_env.add_extension('jinja2.ext.i18n')

    @app.before_request
    def language_provider():
        if not getattr(g, '_lang', None):
            g._lang = get_locale()
        g.get_lang = get_lang

    @app.cli.group()
    def i18n():
        pass

    def extract():
        subprocess.run(['pybabel', 'extract', '-F', 'babel.ini', '-o', 'strings.pot', '.'])

    @i18n.command()
    @click.argument('lang')
    def init(lang):
        extract()
        subprocess.run(['pybabel', 'init', '-i', 'strings.pot', '-d', TRANSLATIONS, '-l', lang])

    @i18n.command()
    def update():
        extract()
        subprocess.run(['pybabel', 'update', '-i', 'strings.pot', '-d', TRANSLATIONS])

    @i18n.command()
    def compile():
        subprocess.run(['pybabel', 'compile', '-d', TRANSLATIONS])


def override_language(lang):
    g._lang = lang


def get_lang():
    return g._lang
