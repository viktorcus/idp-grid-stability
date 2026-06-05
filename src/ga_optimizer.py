import numpy as np
import pandas as pd
from pandapower.run import runpp
from pandapower.timeseries.run_time_series import run_timeseries
from pandapower.networks.power_system_test_cases import case30
from pandapower.create import create_storage
import profileloader as pl
import scipy.optimize as optimize
from control.hydrogen import Hydrogen
from control.battery import Battery
from control.timestep import TimeStepTracker
from tools.ga.problem import GridPlanningProblem
from tools.test_runner import *
from pymoo.algorithms.soo.nonconvex.ga import GA
from pymoo.optimize import minimize
from tools.ga.solution import Solution
import tools.ga.representative_day_eval as eval
from tools.ga.unique_bus_repair import UniqueBusRepair
        
# define globals
test_date =None
checkpoints_path = f'..\\results\\optimizer\\rankings.csv'

max_discrepancy = 0
bus_violation_cost = {}
line_violation_cost = {}
ext_grid_penalty_cost = {}
mse_temp = 0
rankings = {}
monthly_profiles = {}
iteration_counter = 0


def init_run():
    """
        Reset net before a timeseries run, with default case 30 values and timeseries data imported from data files
    """
    # reset global variables
    global bus_violation_cost, line_violation_cost, ext_grid_penalty_cost, mse_temp
    bus_violation_cost = {}
    line_violation_cost = {}
    ext_grid_penalty_cost = {}

    # reset net
    net = case30()

     # import profiles for timeseries data
    load_control = pl.json_to_net_generic(net, "load", date=test_date)
    net.load["q_mvar"] = 0      # not accounting for this for the time being
    gen_control = pl.json_to_net_pv(net, date=test_date)
    tariff_control = pl.json_to_net_generic(net, "poly_cost", date=test_date)
    hydro_control = pl.json_to_net_hydro(net, date=test_date)
    tracker_control = TimeStepTracker(net)
    net.ext_grid["controllable"] = False
    net.gen["controllable"] = False

    return net

def maintain_rankings(net, buses, err):
    global rankings
    if err >= 0:    # filter out nonconverged results (-1)
        if len(rankings) < 10:
            rankings[buses] = err
            rankings = dict(sorted(rankings.items(), key=lambda item: item[1]))
        elif err < list(rankings.values())[9]:
            rankings.popitem()
            rankings[buses] = err
            rankings = dict(sorted(rankings.items(), key=lambda item: item[1]))
    print(rankings)

def bus_violations(net):
    vm = net.res_bus.vm_pu.values
    vmin = net.bus.min_vm_pu.values
    vmax = net.bus.max_vm_pu.values

    over_voltage = np.maximum(0.0, vm - vmax)
    under_voltage = np.maximum(0.0, vmin - vm)

    voltage_violation = over_voltage + under_voltage
    return np.sum(voltage_violation ** 2)

def line_violations(net):
    loading = net.res_line.loading_percent.values
    max_loading = net.line.max_loading_percent.values

    line_violation = np.maximum(0.0, loading - max_loading) / 100
    return np.sum(line_violation ** 2)

def grid_penalty(net):
    return (net.res_ext_grid.p_mw / max_discrepancy) ** 2

def timeseries_runner(net, **kwargs):
    global bus_violation_cost, line_violation_cost, ext_grid_penalty_cost

    dispatch_storage(net, strategy='battery_first')
    runpp(net, max_iteration=40)

    ts = net["_timestep"]

    bus_violation_cost[ts] = bus_violations(net).item()
    line_violation_cost[ts] = line_violations(net).item()
    ext_grid_penalty_cost[ts] = grid_penalty(net).item()



def ga_evaluator(solution: Solution):

    global monthly_profiles, iteration_counter
    total_cost = 0
    iteration_counter += 1


    for month in range(1,13):
        net = init_run()
        init_results_dir(net, "ga_optimizer")
        net = extract_monthly_profile(net, monthly_profiles, month)

        # define battery/ies
        battery1 = create_storage(net, bus=solution.batt_bus1, 
                                name="battery",
                                p_mw=0, 
                                max_p_mw=solution.batt_p_mw1,
                                max_q_mvar=solution.batt_p_mw1,
                                min_p_mw=-solution.batt_p_mw1,
                                min_q_mvar=-solution.batt_p_mw1,
                                max_e_mwh=solution.batt_e_mwh1,
                                soc_percent=50,
                                controllable=True)
        storage_control = Battery(net=net, element_index=battery1.item())
        if solution.batt_on2:
            battery2 = create_storage(net, bus=solution.batt_bus2, 
                                name="battery",
                                p_mw=0, 
                                max_p_mw=solution.batt_p_mw2,
                                max_q_mvar=solution.batt_p_mw2,
                                min_p_mw=-solution.batt_p_mw2,
                                min_q_mvar=-solution.batt_p_mw2,
                                max_e_mwh=solution.batt_e_mwh2,
                                soc_percent=50,
                                controllable=True)
            storage_control = Battery(net=net, element_index=battery2.item())
        if solution.batt_on3:
            battery3 = create_storage(net, bus=solution.batt_bus3, 
                                name="battery",
                                p_mw=0, 
                                max_p_mw=solution.batt_p_mw3,
                                max_q_mvar=solution.batt_p_mw3,
                                min_p_mw=-solution.batt_p_mw3,
                                min_q_mvar=-solution.batt_p_mw3,
                                max_e_mwh=solution.batt_e_mwh3,
                                soc_percent=50,
                                controllable=True)
            storage_control = Battery(net=net, element_index=battery3.item())

        hydrogen1 = create_storage(net, bus=solution.h2_bus1, 
                                name="hydrogen",
                                p_mw=0, 
                                max_p_mw=1000,
                                max_q_mvar=1000,
                                min_p_mw=-1000,
                                min_q_mvar=-1000,
                                max_e_mwh=10000,
                                soc_percent=0,
                                vol_h2_nm3=500,
                                controllable=True)
        storage_control = Hydrogen(net=net, element_index=hydrogen1.item())
        hydrogen2 = create_storage(net, bus=solution.h2_bus2, 
                                name="hydrogen",
                                p_mw=0, 
                                max_p_mw=1000,
                                max_q_mvar=1000,
                                min_p_mw=-1000,
                                min_q_mvar=-1000,
                                max_e_mwh=10000,
                                soc_percent=0,
                                vol_h2_nm3=500,
                                controllable=True)
        storage_control = Hydrogen(net=net, element_index=hydrogen2.item())

        try:
            run_timeseries(net, continue_on_divergence=False, max_iteration=40, run=timeseries_runner, verbose=True, time_steps=range(0,96))
        except: 
            print("model not converged")
            return 1e12
        
        total_cost += sum(bus_violation_cost.values()) + sum(line_violation_cost.values()) + sum(ext_grid_penalty_cost.values())
        #print(bus_violation_cost)
        #print(line_violation_cost)
        #print(ext_grid_penalty_cost)
        print(f'generation {math.floor(iteration_counter / 60) + 1}  iteration  {(iteration_counter % 60)}   err {sum(bus_violation_cost.values()) + sum(line_violation_cost.values()) + sum(ext_grid_penalty_cost.values())}   total cost {total_cost}')
    return total_cost


if __name__ == '__main__':

    net = init_run()
    net_stats = energy_analysis(net)
    max_discrepancy = net_stats["Peak Deficit"]

    monthly_profiles = average_day(net)


    evaluator = lambda sol: ga_evaluator(sol)
    problem = GridPlanningProblem(ga_evaluate=evaluator, max_p_mw=abs(net_stats["Peak Deficit"]))


    result = minimize(
        problem,
        GA(pop_size=60),
        termination=('n_gen',100),
        verbose=True
    )


    #target_buses()
    #optimize_targets()