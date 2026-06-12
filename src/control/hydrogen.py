from pandapower import control

class Hydrogen(control.basic_controller.Controller):
    """
    Baseline hydrogen class
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

            # electrolyzer parameters 
            electrolyzer_mwh_per_vol= 6.8 / 1000,     # MWh/Nm3 (converted from kWh/Nm3)
            num_electrolyzer_units=1,               # multiplier for electrolyzer data
            electrolyzer_vol_per_h=6,               # Nm3/h
            electrolyzer_cost_per_mw=4600 * 1000,   # EUR/MW (converted from EUR/kW)
            # 6.8 MWh/Nm3 * 6 Nm3/h = 40.8 MW power drawn for electrolysis

            # compressor parameters
            p_mw_compression= 75 / 1000,            # MW (converted from kW)
            compress_flowrate=3500,                 # Nm3/h
            compressor_cost_per_mw=75000,           # EUR (single cost)

            # tank and volume parameters
            tank_capacity_kg=4.5, 
            vol_h2_nm3=0, 
            tank_cost_per_kg=600,                   # EUR/kg
            num_tanks=1,                            # multiplier for tank data

            # fuel cell stack parameters
            num_fuel_cells=1,                       # multiplier for fuel cell stack data
            fc_stack_output_mw=-225 / 1000,         # MW (converted from kW and negated due to discharging)
            fuel_cell_efficiency=0.6,               # multiplier used when calculating storage depletion during discharging
            fuel_cell_cost_per_mw=2400 * 1000,      # EUR/MW (converted from EUR/kW)
            
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

        # storage element attributes
        self.max_e_mwh = net.storage.at[element_index, "max_e_mwh"]
        self.soc_percent = net.storage.at[element_index, "soc_percent"] 
        self.max_p_mw = net.storage.at[element_index, "max_p_mw"]
        self.max_q_mvar = net.storage.at[element_index, "max_q_mvar"]
        self.min_p_mw = net.storage.at[element_index, "min_p_mw"]
        self.min_q_mvar = net.storage.at[element_index, "min_q_mvar"]

        # hydrogen constants
        self.lhv_h2 = 33.3 / 1000     # MWh/kg
        self.density_h2 = 0.0899    # kg/Nm^3

        # electrolyzer data
        self.electrolyzer_mwh_per_vol = electrolyzer_mwh_per_vol    # MWh/Nm3
        self.electrolyzer_vol_per_h = electrolyzer_vol_per_h    # Nm3/h
        self.num_electrolyzer_units = num_electrolyzer_units
        self.electrolyzer_cost_per_mw = electrolyzer_cost_per_mw

        # compressor data
        self.p_mw_compression = p_mw_compression        # MW
        self.compress_flowrate = compress_flowrate        # Nm3/hr
        self.compressor_cost_per_mw = compressor_cost_per_mw

        # tank and volume data
        self.tank_capacity_kg  = tank_capacity_kg       # kg
        self.tank_cost_per_kg = tank_cost_per_kg
        self.num_tanks = num_tanks
        if self.soc_percent > 0 and vol_h2_nm3 == 0:
            self.vol_h2_nm3 = self.soc_percent * num_tanks * tank_capacity_kg / self.density_h2
        else:
            self.vol_h2_nm3 = vol_h2_nm3
        self.stored_e_mwh = self.vol_h2_nm3 * self.density_h2 * self.lhv_h2

        # fuel cell stack data
        self.num_fuel_cells = num_fuel_cells
        self.fc_stack_output_mw = fc_stack_output_mw        # MW
        self.fuel_cell_efficiency = fuel_cell_efficiency
        self.fuel_cell_cost_per_mw = fuel_cell_cost_per_mw

        # profile attributes
        self.data_source = data_source
        self.p_profile = p_profile
        self.last_time_step = None

        # storage elemenet attributres, calculated based on provided data: write these back to net
        self.max_p_mw = self.get_max_power_draw()
        net.storage.at[self.element_index, "max_p_mw"] = self.max_p_mw
        self.min_p_mw = self.get_max_power_out()
        net.storage.at[self.element_index, "min_p_mw"] = self.min_p_mw
        self.max_e_mwh = num_tanks * self.get_energy_per_tank()
        net.storage.at[self.element_index, "max_e_mwh"] = self.max_e_mwh
        net.storage.at[self.element_index, "stored_e_mwh"] = self.stored_e_mwh



    def get_energy_per_tank(self):
        """ returns energy in MWh per tank, based on the object's tank size """
        return self.tank_capacity_kg * self.lhv_h2

    def get_max_power_draw(self):
        """ returns the max power that can be drawn for hydrogen production, based on the rated power of the electrolysis (p_sp_electrolyzer_kw)
         and the rated power of the compression (p_sp_compress_kw) """
        return self.num_electrolyzer_units * self.electrolyzer_vol_per_h * self.total_energy_req_per_nm3()
    
    def get_max_power_out(self):
        """ returns the max power that can be taken from fuel cell consumption, based on the rated power of the fuel cell stack
         and the fuel cell stack efficiency"""
        return self.fc_stack_output_mw * self.num_fuel_cells
    
    def total_energy_req_per_nm3(self):
        """returns the MWh required per Nm3 H2 including compression"""
        compression_energy = self.p_mw_compression / self.compress_flowrate
        return self.electrolyzer_mwh_per_vol + compression_energy
    
    def hydrogen_nm3_per_mwh(self):
        return 1 / self.total_energy_req_per_nm3()
    
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
    
    def create_cost_element(self, net):
        if net.poly_cost.query(f'et == "hydrogen" and element == "{self.element_index}"').empty:
            # create relevant poly_cost elements based on the associated costs of hydrogen elements
                net.poly_cost.loc[len(net.poly_cost.index)] = [
                    self.element_index,                              # element
                    "hydrogen",                                  # et
                    (self.num_electrolyzer_units * self.electrolyzer_cost_per_mw * self.electrolyzer_mwh_per_vol * self.electrolyzer_vol_per_h) +
                        (self.num_tanks * self.tank_capacity_kg * self.tank_cost_per_kg) +
                        (self.num_fuel_cells * self.fuel_cell_cost_per_mw * self.fc_stack_output_mw), 
                    0,                                          # cp1_eur_per_mw
                    0,                                          # cp2_eur_per_mw2
                    0,                                          # cq0_eur
                    0,                                          # cq1_eur_per_mvar
                    0                                           # cq2_eur_per_mvar2
            ]
        return net.poly_cost

    def write_to_net(self, net):
        """ after making calculations in here, write these back to net """
        net.storage.at[self.element_index, "stored_e_mwh"] = self.stored_e_mwh

    def control_step(self, net):
        self.write_to_net(net)
        self.applied = True

    
    def time_step(self, net, time):
        if self.last_time_step is not None:
            # update the values after a successful increment in time step
            dt_hr = (time - self.last_time_step) * 0.25
            self.p_mw = net.storage.at[self.element_index, "p_mw"]

            if self.p_mw > 0:   # Electrolyzer mode

                e_in = self.p_mw * dt_hr
                h2_produced_nm3 = (e_in / self.total_energy_req_per_nm3())
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