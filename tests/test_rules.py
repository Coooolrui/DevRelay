import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rules import ConfigError, find_rule, parse_target, rule_matches


class RuleMatchingTest(unittest.TestCase):
    def setUp(self):
        self.rule = {
            "name": "api",
            "enabled": True,
            "match": {
                "host": r"^api\.example\.test$",
                "path": r"^/api(?:/|$)",
                "method": r"^(GET|POST)$",
                "headers": {"X-Env": r"^test$"},
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
                headers={"x-env": "test"},
            )
        )

    def test_rejects_wrong_method(self):
        self.assertFalse(
            rule_matches(
                self.rule,
                host="api.example.test",
                path="/api/users",
                method="OPTIONS",
                headers={"X-Env": "test"},
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


if __name__ == "__main__":
    unittest.main()
