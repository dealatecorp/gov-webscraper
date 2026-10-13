import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import app
from official_notice import OfficialNoticeError, fetch_official_notice, sanitize_html


NOTICE_URL = 'https://eprocure.gov.in/eprocure/app?notice=one'
NOTICE = {'id': 'official-one', 'url': NOTICE_URL, 'title': 'Supply of railway equipment', 'reference': 'REF-2026-123'}
DETAIL_HTML = b'''<html><head><title>Portal</title><script>alert(1)</script></head><body>
<nav><a href="/login">Login navigation</a></nav><form action="https://evil.example/steal">
<input type="hidden" value="private-state"><main><h2>Tender Details</h2>
<table><tr><th colspan="2">Organisation Chain</th></tr><tr><td>Tender Reference Number</td>
<td>REF-2026-123</td></tr><tr><td rowspan="2">Tender ID</td><td>2026_TEST_123_1</td></tr>
<tr><td>Supply of railway equipment</td></tr></table><p>Read all specifications.</p>
<a href="javascript:alert(1)">Tender document label</a><button>Submit bid</button>
</main></form></body></html>'''


class OfficialSnapshotTests(unittest.TestCase):
    def fetch(self, body=DETAIL_HTML, final_url=NOTICE_URL):
        client = Mock()
        client.binary.return_value = (body, final_url)
        return fetch_official_notice(NOTICE, client, app.allowed_url)

    def test_details_inside_form_preserve_tables_and_unwrap_links(self):
        result = self.fetch()
        self.assertEqual(result['kind'], 'html')
        self.assertEqual(result['source_url'], NOTICE_URL)
        self.assertIn('T', result['fetched'])
        html = result['html']
        self.assertIn('<th colspan="2">Organisation Chain</th>', html)
        self.assertIn('<td rowspan="2">Tender ID</td>', html)
        self.assertIn('Tender document label', html)
        self.assertIn('Read all specifications.', html)
        for removed in ('<form', '<input', '<script', '<a ', '<button', 'private-state', 'Login navigation', 'Submit bid'):
            self.assertNotIn(removed, html)

    def test_xss_attributes_embeds_and_malformed_markup_never_survive(self):
        source = '''<main onclick="steal()"><h1 style="background:url(https://evil.example)">Title</h1>
        <svg><foreignObject><iframe src="//evil.example">bad</iframe></foreignObject></svg>
        <math><mtext><img src=x onerror=steal()></mtext></math><script>alert('x')</script>
        <template><p>hidden template</p></template><div hidden>hidden content</div>
        <p data-secret="x"><a href="javascript:steal()">Plain label</a> &lt;img src=x onerror=steal()&gt;</p>
        <table><tr><td colspan="999" rowspan="2" formaction="//evil.example">Value</td></tr></table>
        <img src=//evil.example onerror=steal()><object data=//evil.example></object>
        </main>'''
        html, _, _ = sanitize_html(source)
        for removed in ('onclick=', 'style=', 'href=', 'data-secret=', 'src=', '<script', '<svg', '<math', '<template', '<iframe', '<img', '<object', 'formaction=', 'colspan="999"'):
            # An escaped text example may mention src=; it cannot create an element.
            if removed != 'src=':
                self.assertNotIn(removed, html)
        self.assertNotIn('hidden template', html)
        self.assertNotIn('hidden content', html)
        self.assertIn('&lt;img src=x onerror=steal()&gt;', html)
        self.assertIn('<td rowspan="2">Value</td>', html)

    def test_nested_content_regions_not_duplicated(self):
        html, _, _ = sanitize_html('<main><div class="page_content"><p>Once</p></div></main>')
        self.assertEqual(html.count('Once'), 1)

    def test_pdf_returns_type_without_remote_markup(self):
        result = self.fetch(b'%PDF-')
        self.assertEqual(result['kind'], 'pdf')
        self.assertNotIn('html', result)

    def test_rejects_expired_blocked_captcha_login_homepage_and_wrong_notice(self):
        for body in (
            b'<p>Your session has timed out</p>',
            b'<p>Access denied</p>',
            b'<p>Please enter the CAPTCHA</p>',
            b'<form><h1>Login</h1><p>Username and password required</p></form>',
            b'<h1>Latest tenders</h1><p>REF-2026-123 Supply of railway equipment</p>',
            DETAIL_HTML.replace(b'REF-2026-123', b'OTHER-REFERENCE').replace(b'Supply of railway equipment', b'Road repairs'),
        ):
            with self.subTest(body=body[:60]), self.assertRaises(OfficialNoticeError):
                self.fetch(body)

    def test_no_fetch_for_unsupported_initial_url(self):
        client = Mock()
        for url in ('http://127.0.0.1/private', 'https://eprocure.gov.in.evil.example/private', 'https://user:pass@eprocure.gov.in/private'):
            with self.subTest(url=url), self.assertRaises(OfficialNoticeError):
                fetch_official_notice({**NOTICE, 'url': url}, client, app.allowed_url)
        client.binary.assert_not_called()

    def test_matching_title_does_not_override_a_different_strong_reference(self):
        with self.assertRaisesRegex(OfficialNoticeError, 'could not be matched'):
            self.fetch(DETAIL_HTML.replace(b'REF-2026-123', b'OTHER-REFERENCE'))

    def test_rejects_unsupported_final_url_and_redirect(self):
        with self.assertRaises(OfficialNoticeError):
            self.fetch(final_url='http://127.0.0.1/private')
        with self.assertRaises(ValueError):
            app.SafeRedirect().redirect_request(Request(NOTICE_URL), None, 302, '', {}, 'https://evil.example/x')

    def test_remote_errors_are_actionable_and_do_not_expose_internals(self):
        for error in (HTTPError(NOTICE_URL, 403, 'secret response', {}, None), TimeoutError('socket internals'), ValueError('blocked redirect URL')):
            client = Mock()
            client.binary.side_effect = error
            with self.subTest(error=error), self.assertRaises(OfficialNoticeError) as caught:
                fetch_official_notice(NOTICE, client, app.allowed_url)
            self.assertNotIn(str(error), str(caught.exception))

    def test_binary_sniffs_pdf_without_reading_full_file(self):
        response = io.BytesIO(b'%PDF-' + b'x' * 1000)
        response.geturl = lambda: NOTICE_URL
        with patch.object(app, 'build_opener') as build:
            build.return_value.open.return_value.__enter__.return_value = response
            body, _ = app.Client(timeout=15).binary(NOTICE_URL, max_bytes=20, pdf_header_only=True)
            self.assertEqual(body, b'%PDF-')
            self.assertEqual(response.tell(), 5)

    def test_binary_limits_size_and_expired_time_budget(self):
        response = io.BytesIO(b'<html>' + b'x' * 100)
        response.geturl = lambda: NOTICE_URL
        with patch.object(app, 'build_opener') as build:
            build.return_value.open.return_value.__enter__.return_value = response
            with self.assertRaises(ValueError):
                app.Client().binary(NOTICE_URL, max_bytes=20)
            with self.assertRaises(TimeoutError):
                app.Client(deadline=time.monotonic() - 1).binary(NOTICE_URL)


class LocalOfficialEndpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        database = patch.object(app, 'DB', Path(self.temp.name) / 'test.sqlite3')
        database.start()
        self.addCleanup(database.stop)
        app.init_db()
        app.save_records('cppp', [{**NOTICE, 'feed': 'cppp', 'kind': 'tender', 'organisation': 'Ministry', 'category': '', 'deadline': None, 'opening': None, 'description': ''}])
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        port = patch.object(app, 'PORT', self.server.server_port)
        port.start()
        self.addCleanup(port.stop)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        identity = patch.object(app, 'supabase_identity', side_effect=lambda token: {'id': 'test-user'} if token == 'valid' else None)
        identity.start()
        self.addCleanup(identity.stop)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, path='/api/notices/official-one/official', token='valid'):
        headers = {'Authorization': 'Bearer ' + token} if token else {}
        try:
            response = urlopen(Request(f'http://127.0.0.1:{self.server.server_port}' + path, headers=headers))
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    def test_authentication_required_before_loading_remote_page(self):
        with patch.object(app.Client, 'binary') as fetch:
            self.assertEqual(self.request(token=None)[0], 401)
            self.assertEqual(self.request(token='invalid')[0], 401)
            fetch.assert_not_called()

    def test_unknown_id_never_fetches_arbitrary_query_url(self):
        with patch.object(app.Client, 'binary') as fetch:
            self.assertEqual(self.request('/api/notices/missing/official?url=https://evil.example')[0], 404)
            fetch.assert_not_called()

    def test_html_pdf_and_remote_error_responses(self):
        with patch.object(app.Client, 'binary', return_value=(DETAIL_HTML, NOTICE_URL)) as fetch:
            status, result = self.request('/api/notices/official-one/official?url=https://evil.example')
            self.assertEqual(status, 200)
            self.assertEqual(result['kind'], 'html')
            self.assertEqual(fetch.call_args.args[0], NOTICE_URL)
        with patch.object(app.Client, 'binary', return_value=(b'%PDF-', NOTICE_URL)):
            self.assertEqual(self.request()[1]['kind'], 'pdf')
        with patch.object(app.Client, 'binary', side_effect=TimeoutError):
            status, result = self.request()
            self.assertEqual(status, 502)
            self.assertIn('Try again later', result['error'])


if __name__ == '__main__':
    unittest.main()
