from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from api import index as api


NOTICE_URL = 'https://eprocure.gov.in/eprocure/app?notice=one'
NOTICE = {'id': 'official-one', 'url': NOTICE_URL, 'reference': 'REF-2026-123', 'title': 'Supply of railway equipment'}
HTML = b'<h1>Tender Details</h1><table><tr><td>Tender ID</td><td>2026_TEST_123_1</td></tr><tr><td>Tender Reference Number</td><td>REF-2026-123</td></tr></table>'


class VercelOfficialEndpointTests(unittest.TestCase):
    def test_unauthenticated_request_never_contacts_database_or_source(self):
        with patch.object(api, 'database') as database, patch.object(api.local.Client, 'binary') as fetch:
            response = api.app.test_client().get('/api/notices/official-one/official')
        self.assertEqual(response.status_code, 401)
        database.assert_not_called()
        fetch.assert_not_called()

    def test_id_bound_lookup_html_pdf_errors_and_unknown_notice(self):
        database = Mock()
        query = database.table.return_value.select.return_value.eq.return_value
        query.execute.return_value = SimpleNamespace(data=[NOTICE])
        with patch.object(api, 'current_user', return_value=SimpleNamespace(id='user')), patch.object(api, 'database', return_value=database):
            with patch.object(api.local.Client, 'binary', return_value=(HTML, NOTICE_URL)) as fetch:
                response = api.app.test_client().get('/api/notices/official-one/official?url=https://evil.example')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json['kind'], 'html')
                self.assertEqual(response.json['source_url'], NOTICE_URL)
                self.assertIn('REF-2026-123', response.json['html'])
                database.table.return_value.select.return_value.eq.assert_called_with('id', 'official-one')
                self.assertEqual(fetch.call_args.args[0], NOTICE_URL)
            with patch.object(api.local.Client, 'binary', return_value=(b'%PDF-', NOTICE_URL)):
                response = api.app.test_client().get('/api/notices/official-one/official')
                self.assertEqual(response.json['kind'], 'pdf')
            with patch.object(api.local.Client, 'binary', side_effect=TimeoutError):
                response = api.app.test_client().get('/api/notices/official-one/official')
                self.assertEqual(response.status_code, 502)
                self.assertIn('Try again later', response.json['error'])
            query.execute.return_value = SimpleNamespace(data=[])
            with patch.object(api.local.Client, 'binary') as fetch:
                response = api.app.test_client().get('/api/notices/missing/official')
                self.assertEqual(response.status_code, 404)
                fetch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
