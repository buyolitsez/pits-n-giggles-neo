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

import importlib.util
from pathlib import Path
import sys
import types
import unittest


_READER = None


class TestRaceEngineerTraceReader(unittest.TestCase):
    def test_negative_lap_distance_is_not_wrapped_to_track_end(self):
        self.assertIsNone(_reader()._wrap_lap_distance(-3.0, 5800.0))

    def test_lap_distance_after_finish_line_still_wraps(self):
        self.assertEqual(_reader()._wrap_lap_distance(5805.0, 5800.0), 5.0)


def _reader():
    global _READER  # pylint: disable=global-statement
    if _READER is not None:
        return _READER

    package = types.ModuleType("race_engineer_trace_reader_under_test")
    package.__path__ = []
    readers_package = types.ModuleType("race_engineer_trace_reader_under_test.readers")
    readers_package.__path__ = []
    base_module = types.ModuleType("race_engineer_trace_reader_under_test.base")
    base_module.BaseAPI = object
    sys.modules[package.__name__] = package
    sys.modules[readers_package.__name__] = readers_package
    sys.modules[base_module.__name__] = base_module

    module_name = "race_engineer_trace_reader_under_test.readers.race_engineer_trace"
    reader_path = (
        Path(__file__).resolve().parents[1]
        / "apps"
        / "backend"
        / "state_mgmt_layer"
        / "intf"
        / "readers"
        / "race_engineer_trace.py"
    )
    spec = importlib.util.spec_from_file_location(module_name, reader_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    _READER = module
    return module


if __name__ == "__main__":
    unittest.main()
