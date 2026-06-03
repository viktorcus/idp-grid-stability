from pandapower import control
from pandapower.run import runopp, runpp
from pandapower.diagnostic import Diagnostic
import math

class Battery(control.basic_controller.Controller):
    """
    Baseline battery class, created from the tutorial in
    https://github.com/e2nIEE/pandapower/blob/develop/tutorials/building_a_controller.ipynb
    """
    
    def __init__(self, net, element_index, data_source=None, p_profile=None, in_service=True,
                 recycle=False, order=0, level=0, min_soc_percent=20, charge_efficiency=0.95, 
                 discharge_efficiency=0.95, max_soc_percent=100, **kwargs):
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
        self.data_source = data_source
        self.p_profile = p_profile
        self.last_time_step = None
        self.min_soc_percent = min_soc_percent
        self.max_soc_percent = max_soc_percent
        self.charge_efficiency = charge_efficiency
        self.discharge_efficiency = discharge_efficiency

        # add these to grid-available data        
        net.storage.at[self.element_index, "max_soc_percent"] = self.max_soc_percent
        net.storage.at[self.element_index, "min_soc_percent"] = self.min_soc_percent


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
            # adjust state of charge from the last time step to the current
            rate_of_change = (self.p_mw * (time-self.last_time_step) * 15 / 60) / self.max_e_mwh * 100
            if self.p_mw >= 0:
                self.soc_percent += rate_of_change * self.charge_efficiency 
            else:
                self.soc_percent += rate_of_change / self.discharge_efficiency

        # determine the grid's current power requirement to/from the battery
        """net_dupl = net
        net_dupl.storage.loc[self.element_index, "p_mw"] = 0
        net_dupl.ext_grid.loc[0, "p_mw"] = 0
        net_dupl.gen['controllable'] = False
        net_dupl.ext_grid['controllable'] = False
        try: 
            runopp(net_dupl)
            p_mw_pred = net_dupl.res_storage["p_mw"][self.element_index].item()
            q_mvar_pred = net_dupl.res_storage["q_mvar"][self.element_index].item()
        except: 
            diag = Diagnostic()
            #print(diag.diagnose_network(net, report_style="detailed"))
            try:
                net_dupl.ext_grid['controllable'] = True
                runpp(net_dupl, max_iteration=40)
                batt_count = len(net_dupl[net_dupl.name == 'battery'])
                p_mw_pred = -1 * net_dupl.res_ext_grid["p_mw"][0].item() / batt_count
                q_mvar_pred = -1 * net_dupl.res_ext_grid["q_mvar"][0].item() / batt_count
            except:
                p_mw_pred = self.p_mw
                q_mvar_pred = self.q_mvar

        if p_mw_pred is None or math.isnan(p_mw_pred): 
            p_mw_pred = self.p_mw
            q_mvar_pred = self.q_mvar

        #print("timestep p_mw=" + str(self.p_mw) + " soc=" + str(self.soc_percent) + " pred=" + str(p_mw_pred))

        # upper charging limit reached
        if self.soc_percent >= 100 and p_mw_pred > 0:
            self.soc_percent = 100
            self.max_p_mw = 0       # prevent controllable battery from continuing to charge
            self.max_q_mvar = 0
            self.p_mw = 0
            self.q_mvar = 0
                
        # lower charging limit reached
        elif self.soc_percent <= self.min_soc_percent and p_mw_pred < 0:
            self.soc_percent = self.min_soc_percent
            self.min_p_mw = 0       # prevent controllable battery from continuing to discharge
            self.min_q_mvar = 0
            self.p_mw = 0
            self.q_mvar = 0

        else:
            self.p_mw = p_mw_pred
            self.q_mvar = q_mvar_pred

        # reset charging limits if no longer required 
        if self.max_p_mw == 0 and self.soc_percent < 100:
            self.max_p_mw = self.max_poss_p_mw
            self.max_q_mvar = self.max_poss_q_mvar
        elif self.min_p_mw == 0 and self.min_q_mvar > self.min_soc_percent:
            self.min_p_mw = self.min_poss_p_mw
            self.min_q_mvar = self.min_poss_q_mvar"""

        self.last_time_step = time

        # read new values from a profile, if provided
        if self.data_source:
            if self.p_profile is not None:
                self.p_mw = self.data_source.get_time_step_value(time_step=time, profile_name=self.p_profile)

        self.applied = False