import numpy as np
import multiprocessing
import sys
import dill
import os
import traceback

from pandapower.run import runpp
from pandapower.timeseries.run_time_series import run_timeseries
from pandapower.networks.power_system_test_cases import case30
from pandapower.create import create_storage

import profileloader as pl

from control.hydrogen import Hydrogen
from control.battery import Battery
from control.timestep import TimeStepTracker

from tools.test_runner import *
from tools.ga.problem import GridPlanningProblem
from tools.ga.solution import Solution

from pymoo.algorithms.soo.nonconvex.ga import GA
from pymoo.optimize import minimize
from pymoo.core.callback import Callback
from pymoo.core.mixed import MixedVariableGA
from pymoo.termination import get_termination
from pymoo.parallelization.starmap import StarmapParallelization


# callback class for algorithm checkpoints
class CheckpointCallback(Callback):

    def notify(self, algorithm):
        runner = algorithm.problem.elementwise_runner
        algorithm.problem.elementwise_runner = None

        try:
            with open("checkpoint.pkl", "wb") as f:
                dill.dump({"algorithm": algorithm}, f)
        finally:
            algorithm.problem.elementwise_runner = runner
        

# define globals
test_date = None

max_discrepancy = 0

monthly_profiles = {}
iteration_counter = 0


def init_run(date=None):
    """
        Reset net before a timeseries run, with default case 30 values and timeseries data imported from data files
    """
    # reset global variables
    global test_date
    test_date = date

    # reset net
    net = case30()

     # import profiles for timeseries data
    tariff_control = pl.json_to_net_generic(net, "poly_cost", date=date)
    load_control = pl.json_to_net_generic(net, "load", date=date)
    gen_control = pl.json_to_net_pv(net, date=date)
    hydro_control = pl.json_to_net_hydro(net, date=date)
    tracker_control = TimeStepTracker(net)

    net.load["q_mvar"] = 0      # not accounting for this for the time being
    net.ext_grid["controllable"] = False
    net.gen["controllable"] = False

    return net

def deploy_net_runner(solution: Solution, month=None, date=None):
    """ 
    Dispatches the storage options according to the current GA optimizer solution, and runs the timeseries
    """
    global monthly_profiles

    net = init_run(date)
    if month is not None:
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
    net.poly_cost = storage_control.create_cost_element(net)
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
        net.poly_cost = storage_control.create_cost_element(net)
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
        net.poly_cost = storage_control.create_cost_element(net)


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
    storage_control = Hydrogen(
                                net=net, 
                                element_index=hydrogen1.item(), 
                                num_electrolyzer_units=solution.h2_num_electrolyzers1, 
                                num_fuel_cell_stacks=solution.h2_num_fuelcells1,
                                num_tanks=solution.h2_num_tanks1)
    net.poly_cost = storage_control.create_cost_element(net)

    if solution.h2_on2:
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
        storage_control = Hydrogen(net=net, 
                                element_index=hydrogen2.item(), 
                                    num_electrolyzer_units=solution.h2_num_electrolyzers2, 
                                    num_fuel_cell_stacks=solution.h2_num_fuelcells2,
                                    num_tanks=solution.h2_num_tanks2)
        net.poly_cost = storage_control.create_cost_element(net)

    acc = {
        "bus": 0.0,
        "line": 0.0,
        "grid_penalty": 0.0,
        "grid_price": 0.0
    }

    def local_runner(net, **kwargs):
        timeseries_runner(net, acc)

    run_timeseries(net, continue_on_divergence=False, max_iteration=40, run=local_runner, verbose=True, time_steps=range(0,96))  
    total = (
        acc["bus"]
        + acc["line"]
        + acc["grid_penalty"]
        + acc["grid_price"]
        + grid_component_prices(net)
    )
    print(f'bus err: {acc["bus"]}   line err: {acc["line"]}  grid reliance penalty:  {acc["grid_penalty"]}   grid prices: {acc["grid_price"]}   components: {grid_component_prices(net)}   total cost {total}')    
    
    return total

def bus_violations(net):
    """
    Returns squared error representing the amount by which bus voltages are above or below the bus voltage limits 
    """
    vm = net.res_bus.vm_pu.values
    vmin = net.bus.min_vm_pu.values
    vmax = net.bus.max_vm_pu.values

    over_voltage = np.maximum(0.0, vm - vmax)
    under_voltage = np.maximum(0.0, vmin - vm)

    voltage_violation = over_voltage + under_voltage
    return np.sum((10 * voltage_violation) ** 2)

def line_violations(net):
    """
    Returns squared error representing the amount by which line loading exceeds the maximum 
    """
    loading = net.res_line.loading_percent.values
    max_loading = net.line.max_loading_percent.values

    line_violation = np.maximum(0.0, loading - max_loading)
    return np.sum(line_violation ** 2)

def grid_penalty(net):
    """
    Returns squared error representing the amount by which the system relies on selling/buying power from the grid 
    """
    global max_discrepancy

    return np.sum(net.res_ext_grid.p_mw / max_discrepancy) ** 2

def ext_grid_prices(net):
    return abs(net.poly_cost[net.poly_cost["et"] == "ext_grid"]["cp1_eur_per_mw"].item() * net.res_ext_grid.at[0,"p_mw"])

def grid_component_prices(net):
    return net.poly_cost["cp0_eur"].sum()

def timeseries_runner(net, acc, **kwargs):
    """
    Wrapper function around the pandapower timeseries. 
    Runs each individial step in the timeseries and extracts the violation costs for each step
    """
    dispatch_storage(net, strategy='battery_first')
    runpp(net, max_iteration=40)

    ts = net["_timestep"]

    acc["bus"] += bus_violations(net)
    acc["line"] += line_violations(net)
    acc["grid_penalty"] += grid_penalty(net)
    acc["grid_price"] += ext_grid_prices(net)



def ga_evaluator(solution: Solution):
    """
    Runs the net timeseries for all target trials: the two worst case days, and the typical day for each month
    """

    total_cost = 0

    try:
        for month in range(1,13):
            total_cost += deploy_net_runner(solution, month=month)
        #total_cost += deploy_net_runner(solution, date=net_stats["Peak Surplus Date"])
        #total_cost += deploy_net_runner(solution, date=net_stats["Peak Deficit Date"])
    except Exception as e: 
        # break if the net does not converge on any step in the timeseries, and return the maximum penalty.
        # print(e)
        # print(traceback.format_exc())
        return 1e20
    return total_cost


if __name__ == '__main__':
    continued_flag = "-cont" in sys.argv
    
    net = init_run()
    net_stats = energy_analysis(net)
    max_discrepancy = net_stats["Peak Deficit"]
    monthly_profiles = average_day(net)
    
    problem_kwargs = {
        "ga_evaluate": ga_evaluator,
        "max_p_mw": abs(net_stats["Peak Deficit"])
    }

    pool = None
    # add the runner only when in Colab
    if "gdrive" in os.getcwd():
        n_processes = 8
        pool = multiprocessing.Pool(n_processes)
        problem_kwargs["elementwise_runner"] = StarmapParallelization(pool.starmap)
    
    # initialize problem with or without elementwise_runner as an arg, depending on environment
    problem = GridPlanningProblem(**problem_kwargs)

    # setup for continuation from checkpoint, if requested (script run with "-cont" as argument)
    if continued_flag:
        with open("checkpoint.pkl", "rb") as f:
            ckpt = dill.load(f)
        algorithm = ckpt["algorithm"]

        algorithm.n_gen += 1
        algorithm.termination = get_termination("n_gen", algorithm.n_gen + 5)
        algorithm.problem = problem
        if "gdrive" in os.getcwd(): algorithm.evaluator.elementwise_runner = problem.elementwise_runner

        # re-link the algorithm to the fresh problem (and runner)
        algorithm.setup(problem, progress=True, verbose=True, callback=CheckpointCallback())

        print(f'loading checkpoint at generation {algorithm.n_gen} eval {algorithm.evaluator.n_eval}')
    else:
        algorithm = MixedVariableGA(pop_size=120)
        algorithm.termination = get_termination("n_gen", 1)

    # run Optimization
    result = minimize(
        problem,
        algorithm,
        verbose=True,
        termination=None,
        copy_algorithm=not continued_flag,
        save_history=True,
        callback=CheckpointCallback()
    )

    if pool is not None:
        pool.close()
        pool.join()