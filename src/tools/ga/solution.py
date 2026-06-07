from dataclasses import dataclass

@dataclass
class Solution:

    batt_bus1: int
    batt_p_mw1: float
    batt_e_mwh1: float

    batt_on2: int
    batt_bus2: int
    batt_p_mw2: float
    batt_e_mwh2: float

    batt_on3: int
    batt_bus3: int
    batt_p_mw3: float
    batt_e_mwh3: float

    h2_bus1: int
    h2_num_electrolyzers1: int
    h2_num_fuelcells1: int

    h2_on2: int
    h2_bus2: int
    h2_num_electrolyzers2: int
    h2_num_fuelcells2: int

