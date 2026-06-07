from pandapower import control

class Hydrogen(control.basic_controller.Controller):
    """
    Baseline hydrogen class
    """
    
    def __init__(self, net, element_index, data_source=None, p_profile=None, in_service=True,
                 electrolyzer_p_per_vol=6.8 / 1000, p_kw_compression=75 / 1000, compress_flowrate=3500, recycle=False, order=0, level=0,
                 tank_capacity_kg=4.5, vol_h2_nm3=0, num_electrolyzer_units=1, num_fuel_cell_stacks=1, fc_stack_output_mw=-225 / 1000,
                 fuel_cell_efficiency=0.6, electrolyzer_vol_per_h=6, **kwargs):
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
        self.electrolyzer_vol_per_h = electrolyzer_vol_per_h    # Nm3/h
        self.p_kw_compression = p_kw_compression        # MW
        self.compress_flowrate = compress_flowrate        # Nm3/hr
        self.tank_capacity_kg  = tank_capacity_kg       # kg
        self.lhv_h2 = 33.3 / 1000     # MWh/kg
        self.density_h2 = 0.0899    # kg/Nm^3
        self.vol_h2_nm3 =  vol_h2_nm3   # if assuming we start with some predefined amount already stored
        self.num_electrolyzer_units = num_electrolyzer_units
        self.num_fuel_cell_stacks = num_fuel_cell_stacks
        self.stored_e_mwh = vol_h2_nm3 * self.density_h2 * self.lhv_h2
        self.fc_stack_output_mw = fc_stack_output_mw        # MW
        self.fuel_cell_efficiency = fuel_cell_efficiency
        self.charging = False
        self.discharging = False

        # profile attributes
        self.data_source = data_source
        self.p_profile = p_profile
        self.last_time_step = None

        # write these back to net
        self.max_p_mw = self.get_max_power_draw()
        net.storage.at[self.element_index, "max_p_mw"] = self.max_p_mw
        self.min_p_mw = self.get_max_power_out()
        net.storage.at[self.element_index, "min_p_mw"] = self.min_p_mw
        net.storage.at[self.element_index, "stored_e_mwh"] = self.stored_e_mwh


    def get_energy_per_tank(self):
        """ returns energy in MWh per tank, based on the object's tank size """
        return self.tank_capacity_kg * self.lhv_h2

    def get_max_power_draw(self):
        """ returns the max power that can be drawn for hydrogen production, based on the rated power of the electrolysis (p_sp_electrolyzer_kw)
         and the rated power of the compression (p_sp_compress_kw) """
        return self.num_electrolyzer_units * self.electrolyzer_vol_per_h * self.total_energy_per_nm3()
    
    def get_max_power_out(self):
        """ returns the max power that can be taken from fuel cell consumption, based on the rated power of the fuel cell stack
         and the fuel cell stack efficiency"""
        return self.fc_stack_output_mw * self.num_fuel_cell_stacks
    
    def total_energy_per_nm3(self):
        """returns the MWh required per Nm3 H2 including compression"""
        compression_energy = self.p_kw_compression / self.compress_flowrate
        return self.electrolyzer_p_per_vol + compression_energy
    
    def hydrogen_nm3_per_mwh(self):
        return 1 / self.total_energy_per_nm3()
    
    def number_tanks(self):
        """ returns the number of tanks H2 that we would expect to have, based on the stored kg of hydrogen"""
        return self.vol_h2_nm3 * self.density_h2 / self.tank_capacity_kg
    
    def get_stored_energy(self):
        return self.vol_h2_nm3 * self.density_h2 * self.lhv_h2

    
    def check_capacity_available(self, p_mw, timestep_rate = 0.25):
        """ 
        When evaluating whether to consume H2 storage for the grid, first check if stored supply is available.
        If available, returns the p_mw requested. If H2 is insufficient, then returns the amount of power to drain the H2 left
        """
        if self.vol_h2_nm3 == 0: return 0

        max_power = self.get_max_power_out()

        # power from fuel cells
        if p_mw < max_power:
            p_mw = max_power

        kwh = timestep_rate * p_mw
        if self.get_stored_energy() < abs(kwh):
            return -self.get_stored_energy() / timestep_rate
        else:
            return p_mw
    
    def is_converged(self, net):
        return self.applied
    
    def write_to_net(self, net):
        net.storage.at[self.element_index, "stored_e_mwh"] = self.stored_e_mwh

    def control_step(self, net):
        self.write_to_net(net)
        self.applied = True

        self.charging = True if self.p_mw > 0 else False
        self.discharging = True if self.p_mw < 0 else False

    
    def time_step(self, net, time):
        if self.last_time_step is not None:

            dt_hr = (time - self.last_time_step) * 0.25

            self.p_mw = net.storage.at[self.element_index, "p_mw"]

            if self.p_mw > 0:   # Electrolyzer mode

                e_in = self.p_mw * dt_hr
                h2_produced_nm3 = (e_in / self.total_energy_per_nm3())
                self.vol_h2_nm3 += h2_produced_nm3

            elif self.p_mw < 0:   # Fuel cell mode

                e_out = abs(self.p_mw) * dt_hr
                h2_energy_needed = (e_out / self.fuel_cell_efficiency)

                kg_h2 = (h2_energy_needed / self.lhv_h2 )
                nm3_h2 = (kg_h2 / self.density_h2)
                self.vol_h2_nm3 -= nm3_h2

            self.vol_h2_nm3 = max(0, self.vol_h2_nm3)
            self.stored_e_mwh = self.get_stored_energy()

        self.last_time_step = time

        # read new values from a profile, if provided
        if self.data_source:
            if self.p_profile is not None:
                self.p_mw = self.data_source.get_time_step_value(time_step=time, profile_name=self.p_profile)

        self.applied = False