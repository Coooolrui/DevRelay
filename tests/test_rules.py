import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from mitmproxy import http

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from devrelay_proxy import DevRelayProxy
from rules import ConfigError, capture_rule_values, find_rule, parse_config_text, parse_target, rule_matches


class RuleMatchingTest(unittest.TestCase):
    def setUp(self):
        self.rule = {
            "name": "api",
            "enabled": True,
            "match": {
                "host": r"^api\.example\.test$",
                "path": r"^/api(?:/|$)",
                "method": r"^(GET|POST)$",
            },
            "target": {"scheme": "http", "host": "127.0.0.1", "port": 8080},
        }

    def test_matches_all_regex_dimensions(self):
        self.assertTrue(
            rule_matches(
                self.rule,
                host="api.example.test",
                path="/api/users?active=1",
                method="POST",
            )
        )

    def test_rejects_wrong_method(self):
        self.assertFalse(
            rule_matches(
                self.rule,
                host="api.example.test",
                path="/api/users",
                method="OPTIONS",
            )
        )

    def test_request_headers_do_not_control_rule_matching(self):
        rule = {**self.rule, "match": {**self.rule["match"], "headers": {"X-Env": r"^test$"}}}
        self.assertTrue(
            rule_matches(
                rule,
                host="api.example.test",
                path="/api/users",
                method="GET",
            )
        )

    def test_disabled_rule_is_skipped(self):
        self.rule["enabled"] = False
        self.assertIsNone(
            find_rule(
                [self.rule],
                host="api.example.test",
                path="/api/users",
                method="GET",
            )
        )

    def test_target_is_validated(self):
        self.assertEqual(parse_target(self.rule), ("http", "127.0.0.1", 8080))
        with self.assertRaises(ConfigError):
            parse_target({"target": "not-a-target"})

    def test_yaml_configuration_is_parsed(self):
        config = parse_config_text(
            "rules:\n"
            "  - enabled: true\n"
            "    match:\n"
            "      host: '^api\\.example\\.com$'\n"
            "    target:\n"
            "      scheme: http\n"
            "      host: localhost\n"
            "      port: 9000\n"
        )
        self.assertEqual(config["rules"][0]["target"]["port"], 9000)
        self.assertEqual(config["rules"][0]["match"]["host"], r"^api\.example\.com$")

    def test_invalid_yaml_is_rejected(self):
        with self.assertRaises(ConfigError):
            parse_config_text("rules: [\n")

    def test_named_regex_captures_are_exposed(self):
        rule = {
            "match": {
                "host": r"^(?P<tenant>[^.]+)\.example\.test$",
                "path": r"^/users/(?P<userId>[^/]+)$",
                "method": r"^(?P<verb>GET)$",
            }
        }
        self.assertEqual(
            capture_rule_values(
                rule,
                host="acme.example.test",
                path="/users/42",
                method="GET",
            ),
            {"tenant": "acme", "userId": "42", "verb": "GET"},
        )

    def test_header_values_render_builtins_and_named_captures(self):
        flow = SimpleNamespace(
            request=SimpleNamespace(
                headers={"Origin": "https://app.example.test"},
                pretty_host="api.example.test",
                path="/users/42?active=1",
                query="active=1",
                method="POST",
            )
        )
        self.assertEqual(
            DevRelayProxy._render_value(
                "$origin|$host|$path|$query|$method|${userId}",
                flow,
                {"userId": "42"},
            ),
            "https://app.example.test|api.example.test|/users/42|?active=1|POST|42",
        )

    def test_header_action_list_can_add_set_and_remove(self):
        flow = SimpleNamespace(
            request=SimpleNamespace(
                headers=http.Headers([(b"X-Existing", b"old"), (b"X-Duplicate", b"first")]),
                pretty_host="api.example.test",
                path="/users/42",
                query="",
                method="GET",
            )
        )
        DevRelayProxy._apply_header_actions(
            flow.request.headers,
            [
                {"action": "set", "name": "X-Existing", "value": "new"},
                {"action": "add", "name": "X-Duplicate", "value": "second"},
                {"action": "remove", "name": "X-Remove"},
            ],
            flow,
            captures={},
        )
        self.assertEqual(flow.request.headers["X-Existing"], "new")
        self.assertEqual(flow.request.headers["X-Duplicate"], "first, second")

    def test_config_files_can_be_selected_and_combined(self):
        from devrelay_agent import AgentManager

        with tempfile.TemporaryDirectory() as directory:
            manager = AgentManager()
            manager.config_dir = Path(directory) / "configs"
            manager.state_path = Path(directory) / "state.json"
            manager.create_config_file("first.yml", "rules:\n  - name: first\n")
            manager.create_config_file("second.yml", "rules:\n  - name: second\n")
            manager.select_configs(["second.yml", "first.yml"])
            combined = manager.combined_config()
            self.assertEqual([rule["name"] for rule in combined["rules"]], ["second", "first"])
            self.assertEqual(manager.onboarding()["selectedConfigs"], ["second.yml", "first.yml"])

    def test_empty_config_selection_blocks_proxy_start(self):
        from devrelay_agent import AgentManager

        with tempfile.TemporaryDirectory() as directory:
            manager = AgentManager()
            manager.config_dir = Path(directory) / "configs"
            manager.state_path = Path(directory) / "state.json"
            manager.create_config_file("empty.yml", "rules: []\n")
            manager.select_configs([])
            with self.assertRaisesRegex(RuntimeError, "至少选择一个配置文件"):
                manager.start_proxy()

if __name__ == "__main__":
    unittest.main()
