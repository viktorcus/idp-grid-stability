from pandapower import control
from pandapower.run import runopp, runpp
from pandapower.diagnostic import Diagnostic
import math

class Hydrogen(control.basic_controller.Controller):
    """
    Baseline hydrogen class
    """
    
    def __init__(self, net, element_index, data_source=None, p_profile=None, in_service=True,
                 electrolyzer_p_per_vol=6.8 / 1000, p_kw_compression_max=75 / 1000, compress_flowrate=3500, recycle=False, order=0, level=0,
                 tank_capacity_kg=4.5, vol_h2_nm3=0, **kwargs):
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

        self.electrolyzer_p_per_vol = electrolyzer_p_per_vol    # MWh/Nm3
        self.p_kw_compression_max = p_kw_compression_max        # MW
        self.compress_flowrate = compress_flowrate        # Nm3/hr
        self.tank_capacity_kg  = tank_capacity_kg       # kg
        self.lhv_h2 = 33.3 / 1000     # MWh/kg
        self.density_h2 = 0.0899    # kg/Nm^3
        self.vol_h2_nm3 =  vol_h2_nm3   # if assuming we start with some predefined amount already stored
        self.stored_e_mwh = vol_h2_nm3 * self.density_h2 * self.lhv_h2
        self.charging = False
        self.discharging = False

        # profile attributes
        self.data_source = data_source
        self.p_profile = p_profile
        self.last_time_step = None

        net.storage.at[self.element_index, "stored_e_mwh"] = self.stored_e_mwh

    def get_energy_per_tank(self):
        """ returns energy in MWh per tank, based on the object's tank size """
        return self.tank_capacity_kg * self.lhv_h2

    def get_max_electrolysis_power(self):
        """ returns the max power that can be drawn for hydrogen production, based on the rated power of the electrolysis (p_sp_electrolyzer_kw)
         and the rated power of the compression (p_sp_compress_kw) """
        return self.electrolyzer_p_per_vol + (self.p_kw_compression_max / self.compress_flowrate)
    
    def hydrogen_vol_per_power(self):
        """ returns the rate at which hydrogen (Nm^3) is produced according to the electrolyzer and compression power rates"""
        return (1 / self.electrolyzer_p_per_vol) + (self.compress_flowrate / self.p_kw_compression_max)
    
    def number_tanks(self):
        """ returns the number of tanks H2 that we would expect to have, based on the stored (compressed) volume of hydrogen"""
        return self.vol_h2_nm3 * self.density_h2 / self.tank_capacity_kg
    
    def get_stored_energy(self):
        return self.number_tanks() * self.get_energy_per_tank()
    
    def check_capacity_available(self, p_mw, timestep_rate = 0.25):
        """ 
        When evaluating whether to consume H2 storage for the grid, first check if stored supply is available.
        If available, returns the p_mw requested. If H2 is insufficient, then returns the 
        """
        if self.vol_h2_nm3 == 0: return 0

        kwh = timestep_rate * p_mw
        if self.get_stored_energy() < abs(kwh):
            return self.get_stored_energy / timestep_rate
        else:
            return p_mw
    
    def is_converged(self, net):
        return self.applied
    
    def write_to_net(self, net):
        #net.storage.at[self.element_index, "p_mw"] = self.p_mw
        #net.storage.at[self.element_index, "q_mvar"] = self.q_mvar
        #net.storage.at[self.element_index, "soc_percent"] = self.soc_percent
        net.storage.at[self.element_index, "stored_e_mwh"] = self.stored_e_mwh

    def control_step(self, net):
        self.write_to_net(net)
        self.applied = True

        self.charging = True if self.p_mw > 0 else False
        self.discharging = True if self.p_mw < 0 else False

    
    def time_step(self, net, time):
        if self.last_time_step is not None:
            self.p_mw = net.storage.loc[self.element_index, "p_mw"]
            # adjust change in H2 stored from the last time period to now
            rate_of_change = (self.p_mw * (time-self.last_time_step) * 15 / 60) * self.hydrogen_vol_per_power()
            self.vol_h2_nm3 += rate_of_change
            self.stored_e_mwh += (self.p_mw * (time-self.last_time_step) * 15 / 60)
            #if self.p_mw >= 0:
            #    self.vol_h2_nm3 += rate_of_change * self.charge_efficiency 
            #else:
            #    self.vol_h2_nm3 += rate_of_change / self.discharge_efficiency

        #print("timestep p_mw=" + str(self.p_mw) + " soc=" + str(self.soc_percent) + " pred=" + str(p_mw_pred))
        

        self.last_time_step = time

        # read new values from a profile, if provided
        if self.data_source:
            if self.p_profile is not None:
                self.p_mw = self.data_source.get_time_step_value(time_step=time, profile_name=self.p_profile)

        self.applied = False