import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

import fetch_limits


class ProfileStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.data_dir = self.root / "data"
        self.default_home = self.root / "codex-default"
        self.default_home.mkdir()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_default_profile_uses_existing_codex_home_without_copying(self):
        resolved = fetch_limits.profile_home(
            "default", data_dir=self.data_dir, default_home=self.default_home
        )

        self.assertEqual(resolved, self.default_home)
        self.assertFalse(self.data_dir.exists())

    def test_additional_profile_uses_private_isolated_codex_home(self):
        account_id = "2f0c1f9a4dbe4b80bcb6e6dc69428a77"

        resolved = fetch_limits.profile_home(
            account_id, data_dir=self.data_dir, default_home=self.default_home, create=True
        )

        self.assertEqual(resolved, self.data_dir / "profiles" / account_id)
        self.assertNotEqual(resolved, self.default_home)
        self.assertEqual(stat.S_IMODE(self.data_dir.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(resolved.stat().st_mode), 0o700)
        self.assertEqual(
            (resolved / "config.toml").read_text(),
            'cli_auth_credentials_store = "file"\n',
        )
        self.assertEqual(stat.S_IMODE((resolved / "config.toml").stat().st_mode), 0o600)

    def test_profile_id_rejects_path_traversal(self):
        with self.assertRaises(ValueError):
            fetch_limits.profile_home(
                "../../.ssh", data_dir=self.data_dir, default_home=self.default_home
            )

        self.assertFalse((self.root / ".ssh").exists())

    def test_profile_registry_keeps_only_public_account_metadata(self):
        account_id = "3d01b49831da411fba5a9642786e72d7"
        fetch_limits.save_profile(
            {
                "id": account_id,
                "email": "second@example.com",
                "planType": "plus",
                "accessToken": "never-save-this",
            },
            data_dir=self.data_dir,
        )

        profiles = fetch_limits.load_profiles(data_dir=self.data_dir)
        registry = json.loads((self.data_dir / "accounts.json").read_text())

        self.assertEqual(profiles[0], {"id": account_id, "email": "second@example.com", "planType": "plus"})
        self.assertNotIn("accessToken", registry["accounts"][0])
        self.assertEqual(stat.S_IMODE((self.data_dir / "accounts.json").stat().st_mode), 0o600)


class JsonLineReaderTests(unittest.TestCase):
    def test_reader_skips_notifications_only_when_waiting_for_response(self):
        read_fd, write_fd = os.pipe()
        try:
            payload = (
                json.dumps({"method": "account/updated", "params": {"planType": "plus"}})
                + "\n"
                + json.dumps({"id": 9, "result": {"rateLimits": {"limitId": "codex"}}})
                + "\n"
            )
            os.write(write_fd, payload.encode("utf-8"))
            os.close(write_fd)
            write_fd = -1

            reader = fetch_limits.JsonLineReader(read_fd)

            self.assertEqual(reader.read_message(timeout=1)["method"], "account/updated")
            self.assertEqual(reader.read_message(timeout=1)["id"], 9)
        finally:
            os.close(read_fd)
            if write_fd >= 0:
                os.close(write_fd)

    def test_rpc_request_preserves_notifications_before_its_response(self):
        class FakeReader:
            def __init__(self):
                self.messages = [
                    {"method": "account/updated", "params": {"planType": "plus"}},
                    {"id": 1, "result": {"account": {"type": "chatgpt"}}},
                ]

            def read_message(self, timeout):
                return self.messages.pop(0)

        server = fetch_limits.AppServer.__new__(fetch_limits.AppServer)
        server.request_id = 0
        server.pending_messages = []
        server.reader = FakeReader()
        server.send = lambda message: None

        result = server.request("account/read")

        self.assertEqual(result, {"account": {"type": "chatgpt"}})
        self.assertEqual(server.next_message(0)["method"], "account/updated")


class AccountLookupTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.data_dir = self.root / "data"
        self.default_home = self.root / "codex-default"
        self.default_home.mkdir()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_list_accounts_keeps_default_first_and_additional_profiles(self):
        fetch_limits.save_profile(
            {
                "id": "c900536df9224f97873bf1a60a9217fb",
                "email": "second@example.com",
                "planType": "pro",
            },
            data_dir=self.data_dir,
        )

        class FakeAppServer:
            def __init__(self, home):
                self.home = home

            def request(self, method, params=None, **kwargs):
                return {"account": {"type": "chatgpt", "email": "first@example.com", "planType": "plus"}}

            def close(self):
                pass

        result = fetch_limits.list_accounts(
            data_dir=self.data_dir,
            default_home=self.default_home,
            app_server_factory=FakeAppServer,
        )

        self.assertEqual([account["id"] for account in result["accounts"]], ["default", "c900536df9224f97873bf1a60a9217fb"])
        self.assertEqual(result["accounts"][0]["email"], "first@example.com")
        self.assertTrue(result["accounts"][0]["authenticated"])
        self.assertEqual(result["accounts"][1]["email"], "second@example.com")
        self.assertNotIn("authenticated", result["accounts"][1])

    def test_limits_reject_unregistered_profile_before_starting_server(self):
        def unexpected_server(home):
            raise AssertionError("An unregistered account must not start an app-server")

        with self.assertRaisesRegex(ValueError, "Аккаунт не найден"):
            fetch_limits.fetch_limits(
                "dbe1ebbe113d40f5bf3f16127a6f45ab",
                data_dir=self.data_dir,
                default_home=self.default_home,
                app_server_factory=unexpected_server,
            )


class LoginFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.data_dir = self.root / "data"
        self.default_home = self.root / "codex-default"
        self.default_home.mkdir()
        self.events = []

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_login_saves_profile_after_matching_success_notification(self):
        class FakeAppServer:
            def __init__(self, home):
                self.home = home

            def request(self, method, params=None, **kwargs):
                if method == "account/login/start":
                    return {"loginId": "login-1", "authUrl": "https://auth.openai.com/example"}
                if method == "account/read":
                    return {"account": {"type": "chatgpt", "email": "second@example.com", "planType": "plus"}}
                raise AssertionError(f"Unexpected RPC method: {method}")

            def next_message(self, timeout):
                return {
                    "method": "account/login/completed",
                    "params": {"loginId": "login-1", "success": True},
                }

            def close(self):
                pass

        profile_id = fetch_limits.begin_login(
            data_dir=self.data_dir,
            default_home=self.default_home,
            app_server_factory=FakeAppServer,
            emit=self.events.append,
        )

        self.assertEqual(profile_id, self.events[0]["profileId"])
        self.assertEqual(self.events[0]["event"], "login_started")
        self.assertEqual(self.events[-1]["event"], "login_completed")
        self.assertEqual(fetch_limits.load_profiles(data_dir=self.data_dir)[0]["email"], "second@example.com")
        self.assertTrue((self.data_dir / "profiles" / profile_id / "config.toml").exists())

    def test_failed_login_does_not_register_profile(self):
        class FakeAppServer:
            def __init__(self, home):
                self.home = home

            def request(self, method, params=None, **kwargs):
                if method == "account/login/start":
                    return {"loginId": "login-2", "authUrl": "https://auth.openai.com/example"}
                raise AssertionError(f"Unexpected RPC method: {method}")

            def next_message(self, timeout):
                return {
                    "method": "account/login/completed",
                    "params": {"loginId": "login-2", "success": False, "error": "cancelled"},
                }

            def close(self):
                pass

        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            fetch_limits.begin_login(
                data_dir=self.data_dir,
                default_home=self.default_home,
                app_server_factory=FakeAppServer,
                emit=self.events.append,
            )

        self.assertEqual(fetch_limits.load_profiles(data_dir=self.data_dir), [])

    def test_login_rejects_untrusted_auth_url_before_emitting_or_waiting(self):
        class FakeAppServer:
            def __init__(self, home):
                self.home = home

            def request(self, method, params=None, **kwargs):
                return {"loginId": "login-3", "authUrl": "https://malicious.example/login"}

            def next_message(self, timeout):
                raise AssertionError("An untrusted URL must be rejected before polling login")

            def close(self):
                pass

        with self.assertRaisesRegex(ValueError, "адрес входа"):
            fetch_limits.begin_login(
                data_dir=self.data_dir,
                default_home=self.default_home,
                app_server_factory=FakeAppServer,
                emit=self.events.append,
            )

        self.assertEqual(self.events, [])
        self.assertEqual(fetch_limits.load_profiles(data_dir=self.data_dir), [])


class AuthUrlValidationTests(unittest.TestCase):
    def test_known_chatgpt_and_openai_login_hosts_are_allowed(self):
        self.assertEqual(
            fetch_limits.validate_auth_url("https://chatgpt.com/auth/login?flow=codex"),
            "https://chatgpt.com/auth/login?flow=codex",
        )
        self.assertEqual(
            fetch_limits.validate_auth_url("https://auth.openai.com/codex/device"),
            "https://auth.openai.com/codex/device",
        )

    def test_non_https_untrusted_hosts_and_url_credentials_are_rejected(self):
        bad_urls = [
            "http://chatgpt.com/login",
            "https://malicious.example/login",
            "https://chatgpt.com.malicious.example/login",
            "https://user@chatgpt.com/login",
            "https://chatgpt.com:444/login",
            "https://chatgpt.com/\nother",
        ]
        for url in bad_urls:
            with self.subTest(url=url), self.assertRaises(ValueError):
                fetch_limits.validate_auth_url(url)


if __name__ == "__main__":
    unittest.main()
