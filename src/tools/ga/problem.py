from pymoo.core.problem import ElementwiseProblem
from .solution import Solution
from ..test_runner import energy_analysis

class GridPlanningProblem(
    ElementwiseProblem
):

    def __init__(self, ga_evaluate, max_p_mw):

        self.ga_evaluate = ga_evaluate

        super().__init__(
            n_var=14,
            n_obj=1,
            n_ieq_constr=13,
            xl=[
                0,                  # batt_bus1
                0.5,                # batt_p_mw1
                2,                  # batt_e_mwh1

                0,                  # batt_on2
                0,                  # batt_bus2
                0.5,                # batt_p_mw2
                2,                  # batt_e_mwh2

                0,                  # batt_on3
                0,                  # batt_bus3
                0.5,                # batt_p_mw3
                2,                  # batt_e_mwh3

                0,                  # h2_bus1

                0,                  # h2_on2
                0                   # h2_bus2
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

                2,                  # h2_on2
                30                  # h2_bus2
            ]
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

            h2_on2=int(x[12]),
            h2_bus2=int(x[13])
        )

        out["F"] = self.ga_evaluate(sol)

        g1 = 4 * x[1] - x[2]
        g2 = 0 if int(x[3]) == 0 else 4 * x[5] - x[6]
        g3 = 0 if int(x[7]) == 0 else 4 * x[9] - x[10]

        b1 = int(x[0])
        b2 = int(x[4])
        b3 = int(x[8])
        h1 = int(x[11])
        h2 = int(x[13])

        # Only enforce uniqueness for enabled assets
        c12 = 0 if int(x[3]) == 0 else 1 - abs(b1 - b2)
        c13 = 0 if int(x[7]) == 0 else 1 - abs(b1 - b3)
        c23 = 0 if int(x[3]) == 0 or int(x[7]) == 0 else 1 - abs(b2 - b3)

        c1h1 = 1 - abs(b1 - h1)
        c2h1 = 0 if int(x[3]) == 0 else 1 - abs(b2 - h1)
        c3h1 = 0 if int(x[7]) == 0 else 1 - abs(b3 - h1)

        c1h2 = 0 if int(x[12]) == 0 else 1 - abs(b1 - h2)
        c2h2 = 0 if int(x[3]) == 0 or int(x[12]) == 0 else 1 - abs(b2 - h2)
        c3h2 = 0 if int(x[7]) == 0 or int(x[12]) == 0 else 1 - abs(b3 - h2)

        ch1h2 = 0 if int(x[12]) == 0 else 1 - abs(h1 - h2)

        out["G"] = [
            g1, g2, g3,
            c12, c13, c23,
            c1h1, c2h1, c3h1,
            c1h2, c2h2, c3h2,
            ch1h2
        ]

        print(f'{out["F"]}:   {sol}')