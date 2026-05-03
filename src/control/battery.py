from pandapower import control

class Battery(control.basic_controller.Controller):
    """
    Baseline battery class, created from the tutorial in
    https://github.com/e2nIEE/pandapower/blob/develop/tutorials/building_a_controller.ipynb
    """

    MIN_SOC = 20        # min percent to prevent deep discharge
    
    def __init__(self, net, element_index, data_source=None, p_profile=None, in_service=True,
                 recycle=False, order=0, level=0, **kwargs):
        super().__init__(net, in_service=in_service, recycle=recycle, order=order, level=level,
                         initial_run=True)
        
        # read generator attributes from net
        self.element_index = element_index
        self.bus = net.storage.at[element_index, "bus"]
        self.p_mw = net.storage.at[element_index, "p_mw"]
        self.q_mvar = net.storage.at[element_index, "q_mvar"]
        self.sn_mva = net.storage.at[element_index, "sn_mva"]
        self.name = net.storage.at[element_index, "name"]
        self.gen_type = net.storage.at[element_index, "gen_type"]
        self.in_service = net.storage.at[element_index, "in_service"]
        self.applied = False

        # specific attributes
        self.max_e_mwh = net.storage.at[element_index, "max_e_mwh"]
        self.soc_percent = net.storage.at[element_index, "soc_percent"] = 0
        self.max_poss_p_mw = net.storage.at[element_index, "max_p_mw"]
        self.max_poss_q_mvar = net.storage.at[element_index, "max_q_mvar"]
        self.min_poss_p_mw = net.storage.at[element_index, "min_p_mw"]
        self.min_poss_q_mvar = net.storage.at[element_index, "min_q_mvar"]

        # changeable (to enforce charging/discharging limits)
        self.max_p_mw = net.storage.at[element_index, "max_p_mw"]
        self.max_q_mvar = net.storage.at[element_index, "max_q_mvar"]
        self.min_p_mw = net.storage.at[element_index, "min_p_mw"]
        self.min_q_mvar = net.storage.at[element_index, "min_q_mvar"]

        self.charging = False
        self.discharging = False

        # profile attributes
        self.data_source = self.data_source
        self.p_profile = p_profile
        self.last_time_step = None

    def get_stored_energy(self):
        return self.max_e_mwh * self.soc_percent / 100
    
    def is_converged(self, net):
        return self.applied
    
    def write_to_net(self, net):
        net.storage.at[self.element_index, "p_mw"] = self.p_mw
        net.storage.at[self.element_index, "q_mvar"] = self.q_mvar
        net.storage.at[self.element_index, "soc_percent"] = self.soc_percent

    def control_step(self, net):
        self.write_to_net(net)
        self.applied = True

        self.charging = True if self.p_mw > 0 else False
        self.discharging = True if self.p_mw < 0 else False

    
    def time_step(self, net, time):
        if self.last_time_step is not None:
            self.soc_percent += (self.p_mw * (time-self.last_time_step) * 15 / 60) / self.max_e_mwh * 100

            # upper charging limit reached
            if self.soc_percent >= 100:
                self.soc_percent = 100
                self.max_p_mw = 0       # prevent controllable battery from continuing to charge
                self.max_q_mvar = 0
                self.p_mw = 0
                
            # lower charging limit reached
            elif self.soc_percent <= self.MIN_SOC:
                self.soc_perc = self.MIN_SOC
                self.min_p_mw = 0       # prevent controllable battery from continuing to discharge
                self.min_q_mvar = 0
                self.p_mw = 0

            # reset charging limits if no longer required 
            if self.max_p_mw == 0 and self.soc_percent < 100:
                self.max_p_mw = self.max_poss_p_mw
                self.max_q_mvar = self.max_poss_q_mvar
            elif self.min_p_mw == 0 and self.min_q_mvar > self.MIN_SOC:
                self.min_p_mw = self.min_poss_p_mw
                self.min_q_mvar = self.min_poss_q_mvar

        self.last_time_step = time

        # read new values from a profile
        if self.data_source:
            if self.p_profile is not None:
                self.p_mw = self.data_source.get_time_step_value(time_step=time, profile_name=self.p_profile)

        self.applied = False