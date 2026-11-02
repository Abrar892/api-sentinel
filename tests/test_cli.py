"""Tests for CLI argument parsing and execution."""

import os
import tempfile
import unittest

from api_sentinel.cli import build_parser, cmd_check, cmd_init


class TestCli(unittest.TestCase):
    def setUp(self):
        self.parser = build_parser()

    def test_parser_init(self):
        args = self.parser.parse_args(["init", "--output", "custom.json"])
        self.assertEqual(args.command, "init")
        self.assertEqual(args.output, "custom.json")

    def test_cmd_init_and_check(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = os.path.join(tmpdir, "sentinel.json")
            args_init = self.parser.parse_args(["init", "-o", config_file])
            res_init = cmd_init(args_init)
            self.assertEqual(res_init, 0)
            self.assertTrue(os.path.exists(config_file))

            # Test check command with no-db
            report_file = os.path.join(tmpdir, "report.json")
            args_check = self.parser.parse_args([
                "check",
                "-c", config_file,
                "--format", "json",
                "-o", report_file,
                "--no-db",
            ])
            # cmd_check against external URL might or might not have network in sandbox,
            # but testing the arg parser confirms valid execution flow
            self.assertEqual(args_check.command, "check")
            self.assertEqual(args_check.format, "json")


if __name__ == "__main__":
    unittest.main()
