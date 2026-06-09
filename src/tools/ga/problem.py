from pymoo.core.problem import ElementwiseProblem
from .solution import Solution
import numpy as np
import os

class GridPlanningProblem(
    ElementwiseProblem
):

    def __init__(self, ga_evaluate, max_p_mw, **kwargs):

        self.ga_evaluate = ga_evaluate

        super().__init__(
            n_var=20,
            n_obj=1,
            n_ieq_constr=20,
            elementwise_evaluation=True if "gdrive" in os.getcwd() else False,
            xl=[
                0,                  # batt_bus1
                0.5,                # batt_p_mw1
                2,                  # batt_e_mwh1

                0,                  # batt_on2
                0,                  # batt_bus2
                0  ,                # batt_p_mw2
                0,                  # batt_e_mwh2

                0,                  # batt_on3
                0,                  # batt_bus3
                0,                  # batt_p_mw3
                0,                  # batt_e_mwh3

                0,                  # h2_bus1
                0,                  # h2_num_electrolyzers1
                0,                  # h2_num_fuelcells1
                0,                  # h2_num_tanks1

                0,                  # h2_on2
                0,                  # h2_bus2
                0,                  # h2_num_electrolyzers2
                0,                  # h2_num_fuelcells2
                0                   # h2_num_tanks1
            ],
            xu=[
                30,                 # batt_bus1
                max_p_mw,           # batt_p_mw1
                max_p_mw * 4,       # batt_e_mwh1

                2,                  # batt_on2
                30,                 # batt_bus2
                max_p_mw,           # batt_p_mw2
                max_p_mw * 4,       # batt_e_mwh2

                2,                  # batt_on3
                29,                 # batt_bus3
                max_p_mw,           # batt_p_mw3
                max_p_mw * 4,       # batt_e_mwh3

                30,                 # h2_bus1
                10000,              # h2_num_electrolyzers1
                10000,              # h2_num_fuelcells1
                10000,               # h2_num_tanks1


                2,                  # h2_on2
                30,                 # h2_bus2
                10000,              # h2_num_electrolyzers2
                10000,              # h2_num_fuelcells2
                10000               # h2_num_tanks2
            ],
            **kwargs
        )

    def _evaluate(
        self,
        x,
        out,
        *args,
        **kwargs
    ):

        sol = Solution(
            batt_bus1=int(x[0]),
            batt_p_mw1=x[1],
            batt_e_mwh1=x[2],

            batt_on2=int(x[3]),
            batt_bus2=int(x[4]),
            batt_p_mw2=x[5],
            batt_e_mwh2=x[6],

            batt_on3=int(x[7]),
            batt_bus3=int(x[8]),
            batt_p_mw3=x[9],
            batt_e_mwh3=x[10],

            h2_bus1=int(x[11]),
            h2_num_electrolyzers1=int(x[12]),
            h2_num_fuelcells1=int(x[13]),
            h2_num_tanks1=int(x[14]),

            h2_on2=int(x[15]),
            h2_bus2=int(x[16]),
            h2_num_electrolyzers2=int(x[17]),
            h2_num_fuelcells2=int(x[18]),
            h2_num_tanks2=int(x[19]),
        )

        out["F"] = np.sum(self.ga_evaluate(sol))

        # batteries must have at least 4 hours' capacity
        g1 = 4 * x[1] - x[2]
        g2 = 0 if int(x[3]) == 0 else 4 * x[5] - x[6]
        g3 = 0 if int(x[7]) == 0 else 4 * x[9] - x[10]

        b1 = int(x[0])
        b2 = int(x[4])
        b3 = int(x[8])
        h1 = int(x[11])
        h2 = int(x[16])

        # Only enforce bus uniqueness for enabled assets
        c12 = 0 if int(x[3]) == 0 else 1 - abs(b1 - b2)
        c13 = 0 if int(x[7]) == 0 else 1 - abs(b1 - b3)
        c23 = 0 if int(x[3]) == 0 or int(x[7]) == 0 else 1 - abs(b2 - b3)

        c1h1 = 1 - abs(b1 - h1)
        c2h1 = 0 if int(x[3]) == 0 else 1 - abs(b2 - h1)
        c3h1 = 0 if int(x[7]) == 0 else 1 - abs(b3 - h1)

        c1h2 = 0 if int(x[15]) == 0 else 1 - abs(b1 - h2)
        c2h2 = 0 if int(x[3]) == 0 or int(x[15]) == 0 else 1 - abs(b2 - h2)
        c3h2 = 0 if int(x[7]) == 0 or int(x[15]) == 0 else 1 - abs(b3 - h2)

        ch1h2 = 0 if int(x[15]) == 0 else 1 - abs(h1 - h2)
    
        g_batt2_p = 0 if int(x[3]) != 0 else abs(x[5])
        g_batt2_e = 0 if int(x[3]) != 0 else abs(x[6])
        g_batt3_p = 0 if int(x[7]) != 0 else abs(x[9])
        g_batt3_e = 0 if int(x[7]) != 0 else abs(x[10])

        g_h2_elec = 0 if int(x[15]) != 0 else x[17]
        g_h2_fc   = 0 if int(x[15]) != 0 else x[18]
        g_h2_t   = 0 if int(x[15]) != 0 else x[19]

        out["G"] = [
            g1, g2, g3,
            c12, c13, c23,
            c1h1, c2h1, c3h1,
            c1h2, c2h2, c3h2,
            ch1h2, 
            g_batt2_p, g_batt2_e,
            g_batt3_p, g_batt3_e,
            g_h2_elec, g_h2_fc, g_h2_t
        ]

        print(f'{out["F"]}:   {sol}')