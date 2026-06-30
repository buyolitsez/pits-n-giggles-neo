# MIT License
#
# Copyright (c) [2026] [Ashwin Natarajan]
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

# pylint: skip-file

import unittest

from lib.race_engineer import (
    clear_local_env_secret,
    local_env_secret_is_set,
    save_local_env_secret,
)


class TestRaceEngineerLocalSecrets(unittest.TestCase):
    def test_save_local_env_secret_updates_process_env_and_user_writer(self):
        environ = {}
        writer = _FakeUserEnvWriter()

        result = save_local_env_secret(
            "PNG_AZURE_SPEECH_KEY",
            "secret-value",
            environ=environ,
            user_env_writer=writer,
        )

        self.assertTrue(result.ok)
        self.assertTrue(result.persisted)
        self.assertEqual(environ["PNG_AZURE_SPEECH_KEY"], "secret-value")
        self.assertEqual(writer.calls, [("PNG_AZURE_SPEECH_KEY", "secret-value")])
        self.assertTrue(local_env_secret_is_set("PNG_AZURE_SPEECH_KEY", environ=environ))

    def test_clear_local_env_secret_updates_process_env_and_user_writer(self):
        environ = {"PNG_AZURE_SPEECH_KEY": "secret-value"}
        writer = _FakeUserEnvWriter()

        result = clear_local_env_secret(
            "PNG_AZURE_SPEECH_KEY",
            environ=environ,
            user_env_writer=writer,
        )

        self.assertTrue(result.ok)
        self.assertNotIn("PNG_AZURE_SPEECH_KEY", environ)
        self.assertEqual(writer.calls, [("PNG_AZURE_SPEECH_KEY", None)])
        self.assertFalse(local_env_secret_is_set("PNG_AZURE_SPEECH_KEY", environ=environ))

    def test_invalid_env_var_name_is_rejected(self):
        environ = {}
        writer = _FakeUserEnvWriter()

        result = save_local_env_secret(
            "not a valid env var",
            "secret-value",
            environ=environ,
            user_env_writer=writer,
        )

        self.assertFalse(result.ok)
        self.assertEqual(environ, {})
        self.assertEqual(writer.calls, [])

    def test_writer_failure_reports_error_without_process_env_update(self):
        environ = {}

        def _writer(_name, _value):
            raise RuntimeError("registry unavailable for secret-value")

        result = save_local_env_secret(
            "PNG_AZURE_SPEECH_KEY",
            "secret-value",
            environ=environ,
            user_env_writer=_writer,
        )

        self.assertFalse(result.ok)
        self.assertIn("registry unavailable", result.error)
        self.assertEqual(environ, {})
        self.assertNotIn("secret-value", result.error or "")


class _FakeUserEnvWriter:
    def __init__(self):
        self.calls = []

    def __call__(self, name, value):
        self.calls.append((name, value))


if __name__ == "__main__":
    unittest.main()
