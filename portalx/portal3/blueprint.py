# blueprint.py
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

from urllib.parse import urljoin, urlsplit, urlunsplit

from flask import Blueprint, Request, render_template, redirect, g, abort
from flask import request

from .. import common

APPNAME = 'portal3'
request: Request
portal3 = Blueprint(APPNAME, __name__, template_folder='templates', subdomain=APPNAME)


@portal3.route('/')
@portal3.route('/index.html')
def home():
    return render_template(f'{APPNAME}/index.html')


(lambda: home())


@portal3.url_value_preprocessor
def collect_data_from_request(endpoint, values: dict):
    common.metadata_from_request(g, request, endpoint, values)

    if 'remote' in values:
        g.direct_request = g.request_cookies.get(f'{APPNAME}-remote-redirect', False)

        g.base_scheme = g.request_cookies.get(f'{APPNAME}-remote-scheme')
        g.base_domain = g.request_cookies.get(f'{APPNAME}-remote-domain')
        g.referred_by = g.request_cookies.get(f'{APPNAME}-remote-referrer')
        g.referred_by = g.referred_by and urlsplit(g.referred_by)
        if g.base_scheme and g.request_referrer and not g.referred_by:
            referrer = request.referrer[len(f'{request.scheme}://{request.host}'):]
            g.referred_by = urlsplit(referrer)


@portal3.route('/direct/<path:remote>', methods=('GET', 'POST', 'PUT', 'DELETE', 'HEAD'))
def forward_direct(remote):
    g.direct_request = True
    g.prefix = '/direct/'
    return forward(remote)


@portal3.route('/<path:remote>', methods=('GET', 'POST', 'PUT', 'DELETE', 'HEAD'))
def forward(remote):
    remote_parts = g.remote_url_parts

    if (
        not g.direct_request
        and (not g.request_fetch_mode or g.request_fetch_mode not in ('navigate', 'nested-navigate'))
        and g.referred_by and g.referred_by.scheme and g.referred_by.netloc
        and remote_parts.netloc != g.base_domain
    ):
        base_url_parts = urlsplit(urljoin(g.referred_by.geturl(), '.'))
        subpath = f'{g.remote_url_parts.netloc}/{g.remote_url_parts.path}'.strip('/')
        remote_parts = urlsplit(urljoin(base_url_parts.geturl(), subpath))

    if not remote_parts.scheme and g.base_scheme:
        path = f'/{g.base_scheme}://{g.base_domain}{urlsplit(request.url).path}'
        if request.args:
            path = f'{path}?{request.query_string.decode("utf8")}'
        res = redirect(path, 307)
        set_cookies(res, path=path, redirect='true', max_age=30)
        return res

    guard = common.guard_incoming_url(g, remote_parts, request)
    if guard:
        abort(guard)

    if g.remote_url_parts == remote_parts:

        url = remote_parts.geturl()
        kwargs = dict(**g.request_metadata, data=g.request_payload)

        remote, response = common.pipe_request(url, method=request.method, **kwargs)

        common.copy_headers(request, remote, response)
        common.copy_cookies(request, remote, response)

        if not g.direct_request:
            set_cookies(response, scheme=remote_parts.scheme, domain=remote_parts.netloc, max_age=1800)
            set_cookies(response, path=f'{urljoin(url, ".")}', referrer=remote_parts.geturl(), max_age=1800)

        return response

    return redirect(urlunsplit(tuple([
        *urlsplit(f'{request.scheme}://{request.host}/{remote_parts.geturl()}')[:3],
        request.query_string.decode('utf8'), ''
    ])), 307)


def set_cookies(res, *, path='/', max_age=180, **cookies):
    for k, v in cookies.items():
        opts = dict(key=f'{APPNAME}-remote-{k}', value=v, path=path, max_age=max_age)
        res.set_cookie(**opts)
