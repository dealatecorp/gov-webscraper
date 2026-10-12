import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from api import index as api
from api import collector


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.db.rpc.return_value.execute.return_value.data = True
        self.patches = [patch.object(api, 'database', return_value=self.db),
                        patch.object(api, 'current_user', return_value=SimpleNamespace(id='demo')),
                        patch.dict(os.environ, {'VERCEL_ENV': 'test', 'CRON_SECRET': 'test-cron-secret'})]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.client = api.app.test_client()

    def test_click_collects_and_reports_partial_failure(self):
        results = [{'feed': 'gem', 'state': 'ok', 'fetched': 10, 'new': 8},
                   {'feed': 'hsl', 'state': 'error', 'error': 'Source timeout'}]
        with patch.object(api, 'run_collection', return_value=results) as collect:
            response = self.client.post('/api/sync', json={})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['added'], 8)
        self.assertIn('1/2 feeds connected', response.json['message'])
        collect.assert_called_once_with(self.db)
        update = self.db.table.return_value.update.call_args.args[0]
        self.assertIsNone(update['lease_until'])
        self.assertEqual(update['results'], results)

    def test_duplicate_click_does_not_scrape(self):
        self.db.rpc.return_value.execute.return_value.data = False
        with patch.object(api, 'collection_status', return_value={'running': True}), patch.object(api, 'run_collection') as collect:
            response = self.client.post('/api/sync', json={})
        self.assertTrue(response.json['running'])
        collect.assert_not_called()

    def test_cooldown_reports_wait_without_scraping(self):
        self.db.rpc.return_value.execute.return_value.data = False
        with patch.object(api, 'collection_status', return_value={'running': False}), patch.object(api, 'run_collection') as collect:
            response = self.client.post('/api/sync', json={})
        self.assertIn('15 minutes', response.json['message'])
        collect.assert_not_called()

    def test_anonymous_click_is_rejected(self):
        with patch.object(api, 'current_user', return_value=None), patch.object(api, 'run_collection') as collect:
            response = self.client.post('/api/sync', json={})
        self.assertEqual(response.status_code, 401)
        collect.assert_not_called()

    def test_cron_requires_its_own_secret(self):
        with patch.object(api, 'perform_collection') as collect:
            for headers in ({}, {'Authorization': 'Bearer user-token'}):
                self.assertEqual(self.client.get('/api/collect', headers=headers).status_code, 401)
            collect.assert_not_called()
            collect.return_value = {'ok': True}
            response = self.client.get('/api/collect', headers={'Authorization': 'Bearer test-cron-secret'})
            self.assertEqual(response.status_code, 200)
            collect.assert_called_once()

    def test_failure_releases_lease(self):
        with patch.object(api, 'run_collection', side_effect=RuntimeError('upstream unavailable')):
            response = self.client.post('/api/sync', json={})
        self.assertEqual(response.status_code, 500)
        self.assertIsNone(self.db.table.return_value.update.call_args.args[0]['lease_until'])

    def test_production_registers_secret_only_on_server(self):
        with patch.dict(os.environ, {'VERCEL_ENV': 'production'}), patch.object(api, 'perform_collection', return_value={'ok': True}):
            response = self.client.post('/api/sync', json={})
        self.db.rpc.assert_called_once_with('tenderdesk_set_collection_secret', {'cron_secret': 'test-cron-secret'})
        self.assertNotIn('test-cron-secret', response.get_data(as_text=True))

    def test_collector_joins_every_feed(self):
        with patch.object(collector, 'settings', return_value={}), patch.object(collector, 'collect_feed', side_effect=lambda client, feed, config: {'feed': feed, 'state': 'ok'}) as collect:
            result = collector.run_collection(self.db)
        self.assertEqual({item['feed'] for item in result}, set(collector.local.FEEDS))
        self.assertEqual(collect.call_count, len(collector.local.FEEDS))


if __name__ == '__main__':
    unittest.main()
