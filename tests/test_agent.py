import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from devrelay_agent import AgentManager


class AgentProxyHealthTest(unittest.TestCase):
    def make_manager(self, directory: str) -> AgentManager:
        manager = AgentManager()
        manager.config_dir = Path(directory) / "configs"
        manager.state_path = Path(directory) / "state.json"
        manager.create_config_file("default.yml", "rules: []\n")
        manager.select_configs(["default.yml"])
        return manager

    def test_status_reports_stopped_proxy_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = self.make_manager(directory)
            status = manager.status()

        self.assertFalse(status["running"])
        self.assertEqual(status["health"], "stopped")
        self.assertFalse(status["listenerReady"])
        self.assertEqual(status["clientIdleTimeout"], 86400)
        self.assertIsNone(status["proxyDiagnostics"]["lastFailure"])

    def test_watchdog_records_exit_and_requests_recovery(self):
        manager = AgentManager()
        process = Mock()
        process.poll.return_value = 17
        stop_event = threading.Event()
        manager.process = process
        manager._proxy_generation = 1
        manager._proxy_monitor_stop = stop_event
        manager.PROXY_HEALTH_CHECK_INTERVAL = 0
        manager._recover_proxy_locked = Mock()

        manager._monitor_proxy(process, 1, stop_event)

        self.assertEqual(manager._last_exit_code, 17)
        self.assertIsNotNone(manager._last_exit_at)
        manager._recover_proxy_locked.assert_called_once_with(1, stop_event)

    def test_start_passes_timeout_and_ssl_options_to_mitmdump(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = self.make_manager(directory)
            process = Mock()
            process.poll.return_value = None
            process.pid = 123
            process.stdout = None
            with patch("devrelay_agent.shutil.which", return_value="/usr/bin/mitmdump"), patch(
                "devrelay_agent.subprocess.Popen", return_value=process
            ) as popen:
                manager.start_proxy()

            command = popen.call_args.args[0]

        self.assertIn("--ssl-insecure", command)
        self.assertIn("devrelay_client_idle_timeout=86400", command)


if __name__ == "__main__":
    unittest.main()
