#!/usr/bin/env python3
"""Regression tests for the Discord gateway ownership/restart incident (ORG-48)."""

import os
import pathlib
import subprocess
import sys
import unittest
import uuid


ROOT = pathlib.Path(__file__).resolve().parents[1]
QUEUE_DIR = ROOT / "scripts" / "queue"
SUPERVISOR = ROOT / "scripts" / "_daemons" / "supervise_daemons.ps1"

CHILD = r"""
import os
import sys
import time

sys.path.insert(0, sys.argv[1])
import discord_gateway as gateway

gateway.GW_LOCK = sys.argv[2]
gateway.LOG_FILE = sys.argv[2] + ".log"
gateway.GATEWAY_MUTEX_NAME = sys.argv[3]
acquired = gateway.claim_singleton()
print("ACQUIRED" if acquired else "BUSY", flush=True)
if not acquired:
    raise SystemExit(3)
try:
    time.sleep(float(sys.argv[4]))
finally:
    gateway.release_singleton()
"""


class GatewaySingletonTests(unittest.TestCase):
    def setUp(self):
        test_tmp = ROOT / "local" / "_test_tmp"
        test_tmp.mkdir(parents=True, exist_ok=True)
        self.lock = str(test_tmp / ("gateway-" + uuid.uuid4().hex + ".lock"))
        # Local namespace is enough for the child processes in this test and avoids
        # colliding with the real production mutex.
        self.mutex = "Local\\Go5GatewayTest." + uuid.uuid4().hex

    def tearDown(self):
        for suffix in ("", ".log", ".guard"):
            try:
                pathlib.Path(self.lock + suffix).unlink()
            except OSError:
                pass

    def child_args(self, hold="0.05"):
        return [
            sys.executable,
            "-c",
            CHILD,
            str(QUEUE_DIR),
            self.lock,
            self.mutex,
            str(hold),
        ]

    def run_child(self, hold="0.05"):
        return subprocess.run(
            self.child_args(hold), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=10)

    def start_holder(self):
        proc = subprocess.Popen(
            self.child_args("30"), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(proc.stdout.readline().strip(), "ACQUIRED")
        return proc

    @staticmethod
    def stop_holder(holder):
        if holder.poll() is None:
            holder.terminate()
        holder.communicate(timeout=5)

    def test_second_process_is_rejected_while_owner_is_alive(self):
        holder = self.start_holder()
        try:
            contender = self.run_child()
            self.assertEqual(contender.returncode, 3, contender.stderr)
            self.assertIn("BUSY", contender.stdout)
        finally:
            self.stop_holder(holder)

    def test_force_kill_releases_os_lock_despite_stale_pid_file(self):
        holder = self.start_holder()
        self.stop_holder(holder)
        self.assertTrue(pathlib.Path(self.lock).read_text(encoding="utf-8").startswith("v2 "))

        replacement = self.run_child()
        self.assertEqual(replacement.returncode, 0, replacement.stderr)
        self.assertIn("ACQUIRED", replacement.stdout)

    def test_v2_stale_file_with_reused_live_pid_cannot_block_recovery(self):
        pathlib.Path(self.lock).write_text(f"v2 {os.getpid()}\n", encoding="utf-8")
        replacement = self.run_child()
        self.assertEqual(replacement.returncode, 0, replacement.stderr)
        self.assertIn("ACQUIRED", replacement.stdout)

    def test_legacy_live_pid_is_respected_during_one_time_migration(self):
        pathlib.Path(self.lock).write_text(f"{os.getpid()}\n", encoding="utf-8")
        contender = self.run_child()
        self.assertEqual(contender.returncode, 3, contender.stderr)
        self.assertIn("BUSY", contender.stdout)

    def test_terminated_legacy_pid_does_not_block(self):
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait(timeout=5)
        pathlib.Path(self.lock).write_text(f"{dead.pid}\n", encoding="utf-8")
        replacement = self.run_child()
        self.assertEqual(replacement.returncode, 0, replacement.stderr)
        self.assertIn("ACQUIRED", replacement.stdout)


class SupervisorContractTests(unittest.TestCase):
    def test_gateway_version_stops_at_reaction_subprocess_boundary(self):
        sys.path.insert(0, str(ROOT / "scripts" / "_daemons"))
        import daemon_code_version

        files = {pathlib.Path(p).name for p in daemon_code_version.closure(
            "scripts/queue/discord_gateway.py")}
        self.assertIn("reaction_watch.py", files)
        self.assertIn("process_liveness.py", files)
        self.assertNotIn("session_relay.py", files)
        self.assertNotIn("dept_daemon.py", files)

    def test_gateway_and_waiter_share_liveness_authority(self):
        gateway = (QUEUE_DIR / "discord_gateway.py").read_text(encoding="utf-8")
        waiter = (ROOT / "scripts" / "llm" / "inbox_waiter.py").read_text(encoding="utf-8")
        authority = "from process_liveness import pid_alive as _pid_alive"
        self.assertIn(authority, gateway)
        self.assertIn(authority, waiter)
        self.assertNotIn("def _pid_alive(", gateway)
        self.assertNotIn("def _pid_alive(", waiter)

    def test_launch_is_verified_before_code_version_is_recorded(self):
        text = SUPERVISOR.read_text(encoding="utf-8")
        launch = text[text.index("$cmd = "):text.index("# boot report")]
        self.assertIn("$attempt -le 2", launch)
        self.assertIn("launch verified", launch)
        self.assertIn("START FAILED after immediate retry", launch)
        self.assertLess(launch.index("if (-not $verified)"),
                        launch.index("Set-Content -LiteralPath $verFile"))

    def test_every_forced_stop_waits_for_exit(self):
        text = SUPERVISOR.read_text(encoding="utf-8")
        body = text[text.index("foreach ($d in $daemons)"):text.index("# boot report")]
        self.assertNotIn("Stop-Process -Id", body)
        self.assertGreaterEqual(body.count("Stop-And-Wait"), 4)


if __name__ == "__main__":
    unittest.main()
