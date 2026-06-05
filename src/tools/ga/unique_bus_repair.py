import numpy as np
from pymoo.core.repair import Repair

class UniqueBusRepair(Repair):

    def _do(self, problem, X, **kwargs):

        for row in X:

            used = set()

            for idx in [0,4,8,11,13]:
                print("here")

                bus = int(round(row[idx]))

                while bus in used:
                    bus = np.random.randint(0, 30)

                row[idx] = bus
                used.add(bus)

        return X