import os
import unittest
from unittest.mock import patch

import httpx

from api import index as api


HTTPClient = httpx.Client
USER_ID = "ac0da2ea-85fc-4119-8363-3a3235ea407e"


class VercelSessionTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "SUPABASE_URL": " https://example.supabase.co\r\n",
            "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_test\n",
            "SUPABASE_SECRET_KEY": " sb_secret_test\r\n",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.requests = []
        self.transports = []
        self.reject_token = False

    def upstream(self, request):
        self.requests.append(request)
        if request.url.path == "/auth/v1/user":
            self.assertEqual(request.headers["apikey"], "sb_publishable_test")
            self.assertEqual(request.headers["authorization"], "Bearer user-token")
            if self.reject_token:
                return httpx.Response(401, json={"msg": "Invalid JWT", "code": "bad_jwt"})
            return httpx.Response(200, json={
                "id": USER_ID, "aud": "authenticated", "role": "authenticated",
                "email": "demo@example.test", "created_at": "2026-10-12T00:00:00Z",
                "app_metadata": {}, "user_metadata": {},
            })
        self.assertEqual(request.url.path, "/rest/v1/profiles")
        self.assertEqual(request.headers["apikey"], "sb_secret_test")
        self.assertEqual(request.headers["authorization"], "Bearer sb_secret_test")
        self.assertEqual(request.url.params["id"], "eq." + USER_ID)
        return httpx.Response(200, json=[{
            "id": USER_ID, "email": "demo@example.test", "name": "Demo",
            "interests": [], "keywords": "",
        }])

    def transport(self, **kwargs):
        self.assertIs(kwargs["http2"], False)
        client = HTTPClient(transport=httpx.MockTransport(self.upstream), **kwargs)
        self.transports.append(client)
        return client

    def test_me_verifies_token_then_loads_profile_with_separate_clients(self):
        with patch.object(api.httpx, "Client", side_effect=self.transport):
            response = api.app.test_client().get("/api/me", headers={"Authorization": "Bearer user-token"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["user"]["id"], USER_ID)
        self.assertEqual(len(self.transports), 2)
        self.assertTrue(all(client.is_closed for client in self.transports))
        self.assertNotIn("sb_secret", response.get_data(as_text=True))

    def test_invalid_token_never_reaches_privileged_database(self):
        self.reject_token = True
        with patch.object(api.httpx, "Client", side_effect=self.transport):
            response = api.app.test_client().get("/api/me", headers={"Authorization": "Bearer user-token"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(len(self.requests), 1)
        self.assertTrue(self.transports[0].is_closed)

    def test_missing_token_does_not_contact_supabase(self):
        with patch.object(api.httpx, "Client") as client:
            response = api.app.test_client().get("/api/me")
        self.assertEqual(response.status_code, 401)
        client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
