from pandapower.control.basic_controller import Controller

class TimeStepTracker(Controller):

    element = "timestep"


    def time_step(self, net, time):
        net["_timestep"] = time
        self.applied = True

    def is_converged(self, container):
        return self.applied