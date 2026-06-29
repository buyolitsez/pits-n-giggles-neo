# MIT License
#
# Copyright (c) [2024] [Ashwin Natarajan]
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

# -------------------------------------- IMPORTS -----------------------------------------------------------------------

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from lib.f1_types import CarStatusData, CarDamageData, CarTelemetry2Data
from lib.fuel_rate_recommender import FuelRateRecommender

# -------------------------------------- GLOBALS -----------------------------------------------------------------------

# -------------------------------------- CLASS DEFINITIONS -------------------------------------------------------------

@dataclass(slots=True)
class CarInfo:
    """
    Class that models the car-related data for a race driver.
    """
    total_laps: int = field(repr=False)

    m_ers_perc: Optional[float] = None
    m_drs_activated: Optional[bool] = None
    m_drs_allowed: Optional[bool] = None
    m_drs_distance: Optional[int] = None
    m_fl_wing_damage: Optional[int] = None
    m_fr_wing_damage: Optional[int] = None
    m_rear_wing_damage: Optional[int] = None
    m_floor_damage: Optional[int] = None
    m_diffuser_damage: Optional[int] = None
    m_sidepod_damage: Optional[int] = None
    m_tyres_damage: Optional[List[int]] = None
    m_brakes_damage: Optional[List[int]] = None
    m_tyre_blisters: Optional[List[int]] = None
    m_drs_fault: Optional[bool] = None
    m_ers_fault: Optional[bool] = None
    m_gear_box_damage: Optional[int] = None
    m_engine_damage: Optional[int] = None
    m_engine_mguh_wear: Optional[int] = None
    m_engine_es_wear: Optional[int] = None
    m_engine_ce_wear: Optional[int] = None
    m_engine_ice_wear: Optional[int] = None
    m_engine_mguk_wear: Optional[int] = None
    m_engine_tc_wear: Optional[int] = None
    m_engine_blown: Optional[bool] = None
    m_engine_seized: Optional[bool] = None

    m_curr_lap_ers_harv_mguk_j: Optional[float] = None
    m_curr_lap_ers_harv_mguh_j: Optional[float] = None
    m_curr_lap_ers_deployed_j: Optional[float] = None

    # F1 2026 onwards
    m_ers_harv_limit_per_lap_j: Optional[float] = None

    m_active_aero_mode: Optional[CarTelemetry2Data.ActiveAeroMode] = None
    m_active_aero_avlb: Optional[bool] = None
    m_active_aero_dist: Optional[int] = None
    m_overtake_avlb: Optional[bool] = None
    m_overtake_active: Optional[bool] = None
    m_overtake_dist: Optional[int] = None
    m_2026_regs: Optional[bool] = None

    m_fuel_rate_recommender: "FuelRateRecommender" = field(init=False)

    def __post_init__(self):
        self.m_fuel_rate_recommender = FuelRateRecommender(
            [],
            total_laps=self.total_laps,
            min_fuel_kg=CarStatusData.MIN_FUEL_KG
        )

    def onLapChange(self):
        """Clear the lap-specific data on a lap change"""
        self.m_curr_lap_ers_harv_mguk_j = None
        self.m_curr_lap_ers_harv_mguh_j = None
        self.m_curr_lap_ers_deployed_j = None

    def updateDamage(self, car_damage: CarDamageData) -> None:
        """Update the car damage data fields

        Args:
            car_damage (CarDamageData): The car damage data
        """
        self.m_fl_wing_damage = car_damage.m_frontLeftWingDamage
        self.m_fr_wing_damage = car_damage.m_frontRightWingDamage
        self.m_rear_wing_damage = car_damage.m_rearWingDamage
        self.m_floor_damage = car_damage.m_floorDamage
        self.m_diffuser_damage = car_damage.m_diffuserDamage
        self.m_sidepod_damage = car_damage.m_sidepodDamage
        self.m_tyres_damage = list(car_damage.m_tyresDamage)
        self.m_brakes_damage = list(car_damage.m_brakesDamage)
        self.m_tyre_blisters = list(getattr(car_damage, "m_tyreBlisters", [0] * 4))
        self.m_drs_fault = car_damage.m_drsFault
        self.m_ers_fault = car_damage.m_ersFault
        self.m_gear_box_damage = car_damage.m_gearBoxDamage
        self.m_engine_damage = car_damage.m_engineDamage
        self.m_engine_mguh_wear = car_damage.m_engineMGUHWear
        self.m_engine_es_wear = car_damage.m_engineESWear
        self.m_engine_ce_wear = car_damage.m_engineCEWear
        self.m_engine_ice_wear = car_damage.m_engineICEWear
        self.m_engine_mguk_wear = car_damage.m_engineMGUKWear
        self.m_engine_tc_wear = car_damage.m_engineTCWear
        self.m_engine_blown = car_damage.m_engineBlown
        self.m_engine_seized = car_damage.m_engineSeized

    def getDamageJSON(self) -> Dict[str, Any]:
        """Get the car damage data as a JSON-serializable dictionary."""
        return {
            "fl-wing-damage": self.m_fl_wing_damage,
            "fr-wing-damage": self.m_fr_wing_damage,
            "rear-wing-damage": self.m_rear_wing_damage,
            "floor-damage": self.m_floor_damage,
            "diffuser-damage": self.m_diffuser_damage,
            "sidepod-damage": self.m_sidepod_damage,
            "tyres-damage": self.m_tyres_damage,
            "brakes-damage": self.m_brakes_damage,
            "tyre-blisters": self.m_tyre_blisters,
            "drs-fault": self.m_drs_fault,
            "ers-fault": self.m_ers_fault,
            "gear-box-damage": self.m_gear_box_damage,
            "engine-damage": self.m_engine_damage,
            "engine-mguh-wear": self.m_engine_mguh_wear,
            "engine-es-wear": self.m_engine_es_wear,
            "engine-ce-wear": self.m_engine_ce_wear,
            "engine-ice-wear": self.m_engine_ice_wear,
            "engine-mguk-wear": self.m_engine_mguk_wear,
            "engine-tc-wear": self.m_engine_tc_wear,
            "engine-blown": self.m_engine_blown,
            "engine-seized": self.m_engine_seized,
        }
