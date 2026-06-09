from pandapower import control
import pandas as pd

class Battery(control.basic_controller.Controller):
    """
    Baseline battery class, created from the tutorial in
    https://github.com/e2nIEE/pandapower/blob/develop/tutorials/building_a_controller.ipynb
    """
    
    def __init__(
            # controller required parameters
            self, 
            net, 
            element_index, 
            data_source=None, 
            p_profile=None, 
            in_service=True,
            recycle=False, 
            order=0, 
            level=0, 
                 
            # charging/discharging characteristics
            min_soc_percent=20, 
            max_soc_percent=90, 
            charge_efficiency=0.95, 
            discharge_efficiency=0.95, 

            # cost characteristics
            battery_cost_per_mwh=200 * 1000,       # EUR/MWh (converted from EUR/kWh)
            
            **kwargs):
        super().__init__(net, in_service=in_service, recycle=recycle, order=order, level=level,
                         initial_run=True)
        
        # read generator attributes from net
        self.element_index = element_index
        self.bus = net.storage.at[element_index, "bus"]
        self.p_mw = net.storage.at[element_index, "p_mw"]
        self.q_mvar = net.storage.at[element_index, "q_mvar"]
        self.sn_mva = net.storage.at[element_index, "sn_mva"]
        self.name = net.storage.at[element_index, "name"]
        self.gen_type = net.storage.at[element_index, "type"]
        self.in_service = net.storage.at[element_index, "in_service"]
        self.applied = False

        # specific attributes
        self.max_e_mwh = net.storage.at[element_index, "max_e_mwh"]
        self.soc_percent = net.storage.at[element_index, "soc_percent"]
        self.max_p_mw = net.storage.at[element_index, "max_p_mw"]
        self.max_q_mvar = net.storage.at[element_index, "max_q_mvar"]
        self.min_p_mw = net.storage.at[element_index, "min_p_mw"]
        self.min_q_mvar = net.storage.at[element_index, "min_q_mvar"]

        # profile attributes
        self.data_source = data_source
        self.p_profile = p_profile
        self.last_time_step = None
        self.min_soc_percent = min_soc_percent
        self.max_soc_percent = max_soc_percent
        self.charge_efficiency = charge_efficiency
        self.discharge_efficiency = discharge_efficiency
        self.battery_cost_per_mwh = battery_cost_per_mwh

        # add these to grid-available data        
        net.storage.at[self.element_index, "max_soc_percent"] = self.max_soc_percent
        net.storage.at[self.element_index, "min_soc_percent"] = self.min_soc_percent


    def get_stored_energy(self):
        """ returns the current energy content of the battery, based on the percent to which it is currently charged """
        return self.max_e_mwh * self.soc_percent / 100
    
    def is_converged(self, net):
        return self.applied
    
    def write_to_net(self, net):
        """ after making calculations in here, write these back to net """
        net.storage.at[self.element_index, "soc_percent"] = self.soc_percent

    def control_step(self, net):
        self.write_to_net(net)
        self.applied = True

    def create_cost_element(self, net):
        if net.poly_cost.query(f'et == "battery" and element == "{self.element_index}"').empty:
            # create relevant poly_cost elements based on the associated costs of battery elements
                net.poly_cost.loc[len(net.poly_cost.index)] = [
                    self.element_index,                              # element
                    "battery",                                  # et
                    self.battery_cost_per_mwh * self.max_e_mwh, 
                    0,                                          # cp1_eur_per_mw
                    0,                                          # cp2_eur_per_mw2
                    0,                                          # cq0_eur
                    0,                                          # cq1_eur_per_mvar
                    0                                           # cq2_eur_per_mvar2
            ]
        return net.poly_cost

    
    def time_step(self, net, time):
        if self.last_time_step is not None:
            self.p_mw = net.storage.loc[self.element_index, "p_mw"]
            # adjust state of charge from the last time step to the current
            # for the time being, this is a simplified charging/discharging model using linear changes
            rate_of_change = (self.p_mw * (time-self.last_time_step) * 15 / 60) / self.max_e_mwh * 100
            if self.p_mw >= 0:
                self.soc_percent += rate_of_change * self.charge_efficiency 
            else:
                self.soc_percent += rate_of_change / self.discharge_efficiency
            

        self.last_time_step = time

        # read new values from a profile, if provided
        if self.data_source:
            if self.p_profile is not None:
                self.p_mw = self.data_source.get_time_step_value(time_step=time, profile_name=self.p_profile)

        self.applied = False