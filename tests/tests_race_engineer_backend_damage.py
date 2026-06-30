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

import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


def _load_car_info_class():
    module_path = Path(__file__).resolve().parents[1] / "apps/backend/state_mgmt_layer/data_per_driver/car_info.py"
    spec = importlib.util.spec_from_file_location("car_info_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.CarInfo


class TestRaceEngineerBackendDamage(unittest.TestCase):
    """Tests for preserving packet 10 damage fields used by the race engineer."""

    def test_car_info_preserves_full_damage_packet(self):
        car_info = _load_car_info_class()(total_laps=58)
        car_info.updateDamage(_damage_packet())

        self.assertEqual(car_info.m_fl_wing_damage, 11)
        self.assertEqual(car_info.m_tyres_damage, [1, 2, 3, 4])
        self.assertEqual(car_info.m_brakes_damage, [5, 6, 7, 8])
        self.assertEqual(car_info.m_tyre_blisters, [0, 1, 0, 2])
        self.assertTrue(car_info.m_drs_fault)
        self.assertFalse(car_info.m_ers_fault)
        self.assertEqual(car_info.m_gear_box_damage, 31)
        self.assertEqual(car_info.m_engine_ice_wear, 45)
        self.assertFalse(car_info.m_engine_blown)
        self.assertTrue(car_info.m_engine_seized)

    def test_damage_json_exposes_full_damage_packet(self):
        car_info = _load_car_info_class()(total_laps=58)
        car_info.updateDamage(_damage_packet())

        result = car_info.getDamageJSON()

        self.assertEqual(result["fl-wing-damage"], 11)
        self.assertEqual(result["fr-wing-damage"], 12)
        self.assertEqual(result["rear-wing-damage"], 13)
        self.assertEqual(result["floor-damage"], 14)
        self.assertEqual(result["diffuser-damage"], 15)
        self.assertEqual(result["sidepod-damage"], 16)
        self.assertEqual(result["tyres-damage"], [1, 2, 3, 4])
        self.assertEqual(result["brakes-damage"], [5, 6, 7, 8])
        self.assertEqual(result["tyre-blisters"], [0, 1, 0, 2])
        self.assertTrue(result["drs-fault"])
        self.assertFalse(result["ers-fault"])
        self.assertEqual(result["gear-box-damage"], 31)
        self.assertEqual(result["engine-damage"], 32)
        self.assertEqual(result["engine-mguh-wear"], 41)
        self.assertEqual(result["engine-es-wear"], 42)
        self.assertEqual(result["engine-ce-wear"], 43)
        self.assertEqual(result["engine-ice-wear"], 45)
        self.assertEqual(result["engine-mguk-wear"], 46)
        self.assertEqual(result["engine-tc-wear"], 47)
        self.assertFalse(result["engine-blown"])
        self.assertTrue(result["engine-seized"])


def _damage_packet():
    return SimpleNamespace(
        m_frontLeftWingDamage=11,
        m_frontRightWingDamage=12,
        m_rearWingDamage=13,
        m_floorDamage=14,
        m_diffuserDamage=15,
        m_sidepodDamage=16,
        m_tyresDamage=[1, 2, 3, 4],
        m_brakesDamage=[5, 6, 7, 8],
        m_tyreBlisters=[0, 1, 0, 2],
        m_drsFault=True,
        m_ersFault=False,
        m_gearBoxDamage=31,
        m_engineDamage=32,
        m_engineMGUHWear=41,
        m_engineESWear=42,
        m_engineCEWear=43,
        m_engineICEWear=45,
        m_engineMGUKWear=46,
        m_engineTCWear=47,
        m_engineBlown=False,
        m_engineSeized=True,
    )
