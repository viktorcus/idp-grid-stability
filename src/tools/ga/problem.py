from pymoo.core.problem import ElementwiseProblem
from pymoo.core.variable import Real, Integer, Binary
from .solution import Solution
import numpy as np
import os

class GridPlanningProblem(ElementwiseProblem):

    def __init__(self, ga_evaluate, max_p_mw, **kwargs):

        self.vars = {
            "batt_bus1": Integer(bounds=(0, 29)),
            "batt_p_mw1": Real(bounds=(0.5, max_p_mw)),
            "batt_e_mwh1": Real(bounds=(2.0, max_p_mw * 4)),

            "batt_on2": Binary(), 
            "batt_bus2": Integer(bounds=(0, 29)),
            "batt_p_mw2": Real(bounds=(0.0, max_p_mw)),
            "batt_e_mwh2": Real(bounds=(0.0, max_p_mw * 4)),

            "batt_on3": Binary(),
            "batt_bus3": Integer(bounds=(0, 29)),
            "batt_p_mw3": Real(bounds=(0.0, max_p_mw)),
            "batt_e_mwh3": Real(bounds=(0.0, max_p_mw * 4)),

            "h2_bus1": Integer(bounds=(0, 29)),
            "h2_num_electrolyzers1": Integer(bounds=(0, 10000)),
            "h2_num_fuelcells1": Integer(bounds=(0, 10000)),
            "h2_num_tanks1": Integer(bounds=(0, 10000)),

            "h2_on2": Binary(),
            "h2_bus2": Integer(bounds=(0, 29)),
            "h2_num_electrolyzers2": Integer(bounds=(0, 10000)),
            "h2_num_fuelcells2": Integer(bounds=(0, 10000)),
            "h2_num_tanks2": Integer(bounds=(0, 10000))
        }

        self.ga_evaluate = ga_evaluate
        self.n_var = 20 
        
        """xl = []
        xu = []
        for name, var in vars.items():
            if isinstance(var, Binary):
                xl.append(0)
                xu.append(1)
            else:
                xl.append(var.bounds[0])
                xu.append(var.bounds[1])
        
        self.xl = np.array(xl)
        self.xu = np.array(xu)"""


        super().__init__(vars, n_var=self.n_var, n_obj=1, n_ieq_constr=13, **kwargs)

    def _evaluate(
        self,
        x,
        out,
        *args,
        **kwargs
    ):

        sol = Solution(
            batt_bus1=x["batt_bus1"],
            batt_p_mw1=x["batt_p_mw1"],
            batt_e_mwh1=x["batt_e_mwh1"],

            batt_on2=x["batt_on2"],
            batt_bus2=x["batt_bus2"],
            batt_p_mw2=x["batt_p_mw2"],
            batt_e_mwh2=x["batt_e_mwh2"],

            batt_on3=x["batt_on3"],
            batt_bus3=x["batt_bus3"],
            batt_p_mw3=x["batt_p_mw3"],
            batt_e_mwh3=x["batt_e_mwh3"],

            h2_bus1=x["h2_bus1"],
            h2_num_electrolyzers1=x["h2_num_electrolyzers1"],
            h2_num_fuelcells1=x["h2_num_fuelcells1"],
            h2_num_tanks1=x["h2_num_tanks1"],

            h2_on2=x["h2_on2"],
            h2_bus2=x["h2_bus2"],
            h2_num_electrolyzers2=x["h2_num_electrolyzers2"],
            h2_num_fuelcells2=x["h2_num_fuelcells2"],
            h2_num_tanks2=x["h2_num_tanks2"]
        )

        out["F"] = np.sum(self.ga_evaluate(sol))

        # batteries must have at least 4 hours' capacity
        g1 = 4 * x["batt_p_mw1"] - x["batt_e_mwh1"]
        g2 = 0 if x["batt_on2"] == 0 else 4 * x["batt_p_mw2"] - x["batt_e_mwh2"]
        g3 = 0 if x["batt_on3"] == 0 else 4 * x["batt_p_mw3"] - x["batt_e_mwh3"]

        b1 = x["batt_bus1"]
        b2 = x["batt_bus2"]
        b3 = x["batt_bus3"]
        h1 = x["h2_bus1"]
        h2 = x["h2_bus2"]

        # enforce bus uniqueness for enabled assets
        c12 = 0 if x["batt_on2"] == 0 else 1 - abs(b1 - b2)
        c13 = 0 if x["batt_on3"] == 0 else 1 - abs(b1 - b3)
        c23 = 0 if x["batt_on2"] == 0 or x["batt_on3"] == 0 else 1 - abs(b2 - b3)

        c1h1 = 1 - abs(b1 - h1)
        c2h1 = 0 if x["batt_on2"] == 0 else 1 - abs(b2 - h1)
        c3h1 = 0 if x["batt_on3"] == 0 else 1 - abs(b3 - h1)

        c1h2 = 0 if x["h2_on2"] == 0 else 1 - abs(b1 - h2)
        c2h2 = 0 if x["batt_on2"] == 0 or x["h2_on2"] == 0 else 1 - abs(b2 - h2)
        c3h2 = 0 if x["batt_on3"] == 0 or x["h2_on2"] == 0 else 1 - abs(b3 - h2)

        ch1h2 = 0 if x["h2_on2"] == 0 else 1 - abs(h1 - h2)
    
        # g_batt2_p = 0 if x["batt_on2"] != 0 else abs(x[5])
        # g_batt2_e = 0 if x["batt_on2"] != 0 else abs(x[6])
        # g_batt3_p = 0 if x["batt_on3"] != 0 else abs(x[9])
        # g_batt3_e = 0 if x["batt_on3"] != 0 else abs(x[10])

        # g_h2_elec = 0 if x["h2_on2"] != 0 else x[17]
        # g_h2_fc   = 0 if x["h2_on2"] != 0 else x[18]
        # g_h2_t   = 0 if x["h2_on2"] != 0 else x[19]

        out["G"] = [
            g1, g2, g3,
            c12, c13, c23,
            c1h1, c2h1, c3h1,
            c1h2, c2h2, c3h2,
            ch1h2# , 
            # g_batt2_p, g_batt2_e,
            # g_batt3_p, g_batt3_e,
            # g_h2_elec, g_h2_fc, g_h2_t
        ]

        print(f'[{out["F"]}:]   {sol}')