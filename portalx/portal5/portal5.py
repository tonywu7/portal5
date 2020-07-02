# features.py
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

import json
import uuid
from functools import reduce
from urllib.parse import SplitResult, urlsplit

from flask import Request

from .. import common, security

APPNAME = 'portal5'


class PreferenceMixin(object):
    __slots__ = ()

    def __init__(self):
        self.prefs: dict = self.bitmask_to_dict(self.prefs) if self.prefs is not None else FEATURES_DEFAULTS

    def print_prefs(self, **kwargs):
        prefs = {}
        for k, v in self.prefs.items():
            option = {}
            option['enabled'] = v
            option.update({k_: v for k_, v in FEATURES_TEXTS.get(k, dict(name=k)).items()})
            if 'desc' in option:
                option['desc'] = [line % kwargs for line in option['desc']]
            section = prefs.setdefault(k.split('_')[0], {})
            section[k] = option
        return prefs

    def make_client_prefs(self):
        prefs = dict(
            value=self.get_bitmask(),
            local={FEATURES_KEYS[k]: self.prefs[FEATURES_KEYS[k]] for k in FEATURES_CLIENT_SPECIFIC},
        )
        return dict(prefs=prefs)

    def get_bitmask(self):
        return self.dict_to_bitmask(self.prefs)

    def set_bitmask(self, mask):
        self.prefs = self.bitmask_to_dict(mask)

    @classmethod
    def bitmask_to_dict(cls, mask):
        return {FEATURES_KEYS[k]: bool(mask & 2 ** k) for k in FEATURES_KEYS if k in FEATURES_KEYS}

    @classmethod
    def dict_to_bitmask(cls, prefs):
        reverse_lookup = {v: k for k, v in FEATURES_KEYS.items()}
        return reduce(lambda x, y: x | y, [2 ** reverse_lookup.get(k, 0) * int(v) for k, v in prefs.items()])

    @classmethod
    def make_default_prefs(cls):
        return {**FEATURES_DEFAULTS}


class FeaturesMixin(object):
    __slots__ = ()

    def process_response(self, remote, response, **kwargs):
        kwargs.update({f'request_{k}': getattr(self, k) for k in self.__slots__})

        if self.prefs['basic_set_headers']:
            common.copy_headers(remote, response, **kwargs)

        if self.prefs['basic_set_cookies']:
            common.copy_cookies(remote, response, **kwargs)

        if self.prefs['security_enforce_cors']:
            security.enforce_cors(remote, response, **kwargs)

        if self.prefs['security_break_csp']:
            security.break_csp(remote, response, **kwargs)

        if self.prefs['security_clear_cookies_on_navigate']:
            security.add_clear_site_data_header(remote, response, **kwargs)


class URLPassthruSettingsMixin(object):
    __slots__ = ()

    def make_passthru_settings(self, app, g):
        sibling_domains = {
            f'{rule.subdomain}.{g.sld}'
            for rule in app.url_map.iter_rules()
            if rule.subdomain and rule.subdomain != APPNAME
        }

        passthru = app.config.get_namespace('PORTAL5_PASSTHRU_')
        passthru_domains = passthru.get('domains', set())
        passthru_urls = passthru.get('urls', set())
        return {
            'passthru': dict(
                domains={k: True for k in {g.sld} | sibling_domains | passthru_domains},
                urls={k: True for k in passthru_urls},
            ),
        }


class Portal5Request(PreferenceMixin, FeaturesMixin, URLPassthruSettingsMixin):
    __slots__ = 'id', 'version', 'prefs', 'mode', 'referrer', 'origin'

    VERSION = 5

    HEADER = 'X-Portal5'
    SETTINGS_ENDPOINT = '/settings'

    def __init__(self, request: Request):
        try:
            fetch = json.loads(request.headers.get(self.HEADER, '{}'))
        except Exception:
            fetch = {}

        for k in self.__slots__:
            if not hasattr(self, k):
                setattr(self, k, fetch.get(k, None))

        PreferenceMixin.__init__(self)

    @property
    def up_to_date(self):
        return self.VERSION == self.version

    @property
    def origin_domain(self):
        if self.origin:
            return urlsplit(self.origin).netloc
        elif self.referrer:
            return urlsplit(self.referrer).netloc
        return None

    def __call__(self, url: SplitResult, request: Request, **overrides):
        info = common.extract_request_info(request)

        headers = info['headers']
        headers.pop('Host', None)
        headers.pop('Origin', None)
        headers.pop('Referer', None)
        headers.pop(self.HEADER, None)

        if self.referrer:
            headers['Referer'] = self.referrer

        if self.origin and (self.mode == 'cors' or request.method not in {'GET', 'HEAD'}):
            headers['Origin'] = self.origin

        if self.origin_domain:
            kwargs = security.conceal_origin(request.host, self.origin_domain, url, **info)
        else:
            kwargs = dict(url=url, **info)

        kwargs['method'] = request.method
        kwargs['url'] = kwargs['url'].geturl()
        kwargs['data'] = common.stream_request_body(request)
        kwargs.update(overrides)

        return kwargs

    def make_worker_settings(self, request, app, g):
        settings = {**self.make_passthru_settings(app, g), **self.make_client_prefs()}

        restricted = settings.setdefault('restricted', {})
        restricted.update({k: True for k in [self.SETTINGS_ENDPOINT]})

        settings['id'] = uuid.uuid4()
        settings['version'] = self.VERSION
        settings['protocol'] = request.scheme
        settings['host'] = request.host

        return settings


FEATURES_KEYS = {
    0: 'basic_rewrite_crosssite',
    1: 'basic_set_headers',
    2: 'basic_set_cookies',
    3: 'security_enforce_cors',
    4: 'security_break_csp',
    5: 'security_clear_cookies_on_navigate',
    6: 'experimental_client_side_rewrite',
}

FEATURES_CLIENT_SPECIFIC = [0, 6]

FEATURES_DEFAULTS = {
    'basic_rewrite_crosssite': True,
    'basic_set_headers': True,
    'basic_set_cookies': True,
    'security_enforce_cors': True,
    'security_break_csp': False,
    'security_clear_cookies_on_navigate': False,
    'experimental_client_side_rewrite': False,
}

FEATURES_TEXTS = {
    'basic_rewrite_crosssite': dict(
        name='Redirect cross-site requests',
        desc=[
            'Let Service Worker intercept and redirect cross-site requests (those to a different domain) through this tool.',
        ],
    ),
    'basic_set_headers': dict(
        name='Forward HTTP headers',
        desc=[
            'Forward HTTP headers received from the remote server.',
        ],
    ),
    'basic_set_cookies': dict(
        name='Forward cookies',
        desc=[
            'Forward cookies received from the remote server, changing their domain and path values as appropriate.',
            'Note: This does not affect cookies set by scripts on the webpage. These cookies may not be set with proper domains/paths.',
        ],
    ),
    'security_enforce_cors': dict(
        name='Enforce CORS <code>Access-Control-Allow-Origin</code> header',
        desc=[
            'Recommended. <em>Modify the <code>Access-Control-Allow-Origin</code> header following these rules:</em>',
            '<ul>'
            '<li>If it is set to <code>*</code>, it is kept unmodified</li>'
            '<li>If it is set to a particular origin, then check if such origin matches the origin who requested the resource (e.g. the webpage); '
            'if it matches, the header is set to <code>%(server_origin)s</code> so that the resource will be accepted by browsers, '
            'and if it does not match, drop the <code>Access-Control-Allow-Origin</code> header so that the resource will be rejected by browsers.</li>'
            '</ul>',
            'If disabled, the <code>Access-Control-Allow-Origin</code> is transmitted unmodified.',
        ],
    ),
    'security_break_csp': dict(
        name='Bypass Content Security Policy (CSP) protection',
        desc=[
            'NOT recommended. <em>Append <code>%(server_origin)s</code> to all CSP directives that specify sources,</em> except for '
            "those that specify <code>'none'</code>. Doing so ensures that browsers can load resources as if the webpage is not "
            'proxied by this tool.',
            '<strong>However, doing so entirely defeats the purpose of CSP,</strong> '
            'as (potentially malicious) contents that would otherwise be forbidden by CSP will now also be loaded.',
            'If disabled, CSP headers will be transmitted unmodified, and resources protected by CSP directives may not load.',
        ],
        color='yellow',
    ),
    'security_clear_cookies_on_navigate': dict(
        name='Clear cookies between cross-site visits',
        desc=[
            '<em>Delete all cookies when you navigate from one page to another page on a different domain.</em> '
            'One major security caveats of this tool is that website cookies that would otherwise be separated under different domains '
            'will now all stored under the same domain. Keeping cookies separate by domains ensures that one website cannot get cookies that '
            'may contain sensitive information, such as login info, of another website. When using this tool, all websites you visit may see '
            'cookies of other sites.',
            'This option mitigates this security concern by asking your browser to clear out all cookies between visits to different websites. '
            'Visits that stay within the same site are not affected. The drawback is that you may lose some functionalities on some websites. '
            'Additionally, this option takes effect on all windows/tabs that are open, meaning that if you have multiple tabs open, and one of them '
            'navigates to a different site, cookies on all tabs will be cleared, and you may notice inconsistencies in the behaviors of the webpages you are visiting.',
            'Note: This option relies on the <code>Clear-Site-Data</code> header to work, which is not supported by all browsers.',
        ],
    ),
    'experimental_client_side_rewrite': dict(
        name='Enable in-browser URL preprocessing',
        desc=[
            'Experimental feature. <em>Allow Service Worker to prefetch an HTML document and rewrite all URLs in the document '
            'before serving it to the browser.</em> This mainly has two benefits:',
            '<ul>'
            '<li><em>This allows user-initiated navigations to go through this tool.</em> Before, if you click on a link on a webpage that '
            'goes to a different domain, your browser will visit that domain directly, bypassing Service Worker altogether, and you will '
            'exit this tool. Rewriting these URLs makes sure you stay on <code>%(server_origin)s</code>.</li>'
            '<li><em>This allows requests to embedded contents such as <code>iframe</code>s to go through this tool.</em> Same as above: '
            'without rewriting their URLs, requests to these contents will bypass Service Worker, which means that they may not load correctly.</li>'
            '</ul>',
            'Note: This feature currently looks for all <code>href</code>, <code>src</code>, <code>data-href</code>, and <code>data-src</code> '
            'attributes. If the webpage you are visiting uses other non-conventional attributes for URLs, they will not be rewritten. '
            'The same goes for URLs generated dynamically by scripts.',
        ],
        color='blue',
    ),
}
