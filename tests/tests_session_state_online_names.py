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

import logging
import unittest
from types import SimpleNamespace

from apps.backend.state_mgmt_layer import SessionState
from lib.config import PngSettings
from lib.f1_types import (F1PacketType, Nationality, PacketHeader,
                          ParticipantData, Platform, TeamID24,
                          TelemetrySetting)


class TestSessionStateOnlineNames(unittest.TestCase):
    @staticmethod
    def _build_header() -> PacketHeader:
        return PacketHeader.from_values(
            packet_format=2024,
            game_year=24,
            game_major_version=1,
            game_minor_version=0,
            packet_version=1,
            packet_type=F1PacketType.PARTICIPANTS,
            session_uid=1,
            session_time=0.0,
            frame_identifier=1,
            overall_frame_identifier=1,
            player_car_index=0,
            secondary_player_car_index=255,
        )

    def test_process_participants_update_prefers_best_available_name(self):
        state = SessionState(
            logger=logging.getLogger("tests_session_state_online_names"),
            settings=PngSettings(),
            ver_str="test",
        )
        header = self._build_header()
        participant = ParticipantData.from_values(
            header,
            ai_controlled=False,
            driver_id=255,
            network_id=7,
            team_id=TeamID24.F1_GENERIC,
            my_team=False,
            race_number=2,
            nationality=Nationality.Unspecified,
            name="HiddenNick",
            your_telemetry=TelemetrySetting.PUBLIC,
            show_online_names=False,
            platform=Platform.STEAM,
            tech_level=0,
        )
        packet = SimpleNamespace(
            m_header=SimpleNamespace(m_playerCarIndex=0),
            m_participants=[participant],
        )

        state.processParticipantsUpdate(packet)

        driver = state.m_driver_data[0]
        self.assertIsNotNone(driver)
        self.assertEqual(driver.m_driver_info.name, "HiddenNick")
        self.assertEqual(driver.m_tyre_info.m_tyre_wear_extrapolator.name, "HiddenNick")
