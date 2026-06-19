import numpy as np
import multiprocessing
import sys
import dill
import os
import traceback
import csv

from pandapower.run import runpp
from pandapower.timeseries.run_time_series import run_timeseries
from pandapower.networks.power_system_test_cases import case30
from pandapower.create import create_storage
from pandapower.toolbox import set_isolated_areas_out_of_service
from pandapower import LoadflowNotConverged

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
            # write checkpoints for algorithm to resume
            with open("checkpoint.pkl", "wb") as f:
                dill.dump({"algorithm": algorithm}, f)
        finally:
            algorithm.problem.elementwise_runner = runner

        try: 
            # write checkpoints for historical data (current optimized result at each iteration)
            active_buses = [0, 1, 2, 3, 4, 6, 7, 9, 11, 14, 15, 16, 17, 19, 22, 23, 25, 28, 29]  # hard-coded temporarily
            with open('..\\results\\checkpoints.csv', 'a', newline='') as f:
                writer = csv.writer(f)
                opt = algorithm.opt[0]
                writer.writerow([
                    algorithm.n_gen, algorithm.evaluator.n_eval, opt.F,
                    active_buses[opt.X["batt_bus1"]], opt.X["batt_p_mw1"], opt.X["batt_e_mwh1"],
                    opt.X["batt_on2"], active_buses[opt.X["batt_bus2"]], opt.X["batt_p_mw2"], opt.X["batt_e_mwh2"],
                    opt.X["batt_on3"], active_buses[opt.X["batt_bus3"]], opt.X["batt_p_mw3"], opt.X["batt_e_mwh3"],
                    active_buses[opt.X["h2_bus1"]], opt.X["h2_num_electrolyzers1"], opt.X["h2_num_fuelcells1"], opt.X["h2_num_tanks1"],
                    opt.X["h2_on2"], active_buses[opt.X["h2_bus2"]], opt.X["h2_num_electrolyzers2"], opt.X["h2_num_fuelcells2"], opt.X["h2_num_tanks2"]
                ])
            f.close()
        except:
            print("failed to write to checkpoints.csv")
            

        

# define globals
test_date = None

max_discrepancy = 0

monthly_profiles = {}
iteration_counter = 0


net_master = None

weights = {
    "bus": 0.05,
    "line": 0.01,
    "grid_penalty": 0,
    "grid_price": 0.002,
    "components": 5e-11
}

acc_totals = {
        "bus": 0.0,
        "line": 0.0,
        "grid_penalty": 0.0,
        "grid_price": 0.0,
        "components": 0.0
}


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
    net = pl.json_to_bus_coords(net)
    net = pl.json_to_lines(net)
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
    active_buses = net.bus[net.bus.in_service.values].index
    if month is not None:
        net = extract_monthly_profile(net, monthly_profiles, month)

    # define battery/ies
    battery1 = create_storage(net, bus=active_buses[solution.batt_bus1], 
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
        battery2 = create_storage(net, bus=active_buses[solution.batt_bus2], 
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
        battery3 = create_storage(net, bus=active_buses[solution.batt_bus3], 
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


    hydrogen1 = create_storage(net, bus=active_buses[solution.h2_bus1], 
                                name="hydrogen",
                                p_mw=0, 
                                max_p_mw=1000,
                                max_q_mvar=1000,
                                min_p_mw=-1000,
                                min_q_mvar=-1000,
                                max_e_mwh=10000,
                                soc_percent=50,
                                controllable=True)
    storage_control = Hydrogen(
                                net=net, 
                                element_index=hydrogen1.item(), 
                                num_electrolyzer_units=solution.h2_num_electrolyzers1, 
                                num_fuel_cells=solution.h2_num_fuelcells1,
                                num_tanks=solution.h2_num_tanks1)
    net.poly_cost = storage_control.create_cost_element(net)

    if solution.h2_on2:
        hydrogen2 = create_storage(net, bus=active_buses[solution.h2_bus2], 
                                    name="hydrogen",
                                    p_mw=0, 
                                    max_p_mw=1000,
                                    max_q_mvar=1000,
                                    min_p_mw=-1000,
                                    min_q_mvar=-1000,
                                    max_e_mwh=10000,
                                    soc_percent=50,
                                    controllable=True)
        storage_control = Hydrogen(net=net, 
                                element_index=hydrogen2.item(), 
                                    num_electrolyzer_units=solution.h2_num_electrolyzers2, 
                                    num_fuel_cells=solution.h2_num_fuelcells2,
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

    try:
        run_timeseries(net, continue_on_divergence=False, max_iteration=20, run=local_runner, verbose=False, time_steps=range(0,96))  
    except LoadflowNotConverged as e:
        # punish non-convering grids by a factor of 1000 multiplied against how many steps remained in the day after non-convergence
        return (1 - (net["_timestep"]  / 96)) * 1000
    
    acc_totals["bus"] += acc["bus"] * weights["bus"]
    acc_totals["line"] += acc["line"] * weights["line"]
    acc_totals["grid_price"] += acc["grid_price"] * weights["grid_price"]
    acc_totals["components"] += grid_component_prices(net) * weights["components"] if month == 1 else 0

    total = (
        acc["bus"] * weights["bus"]
        + acc["line"] * weights["line"]
        + acc["grid_price"] * weights["grid_price"]
    )
    # count grid components cost only once
    if month == 1: total += (grid_component_prices(net) * weights["components"])
    print(f'bus err: {acc["bus"] * weights["bus"]}   line err: {acc["line"] * weights["line"]}  price penalty:  {acc["grid_price"] * weights["grid_price"]}    components: {grid_component_prices(net) * weights["components"]}   total cost {total}')    
    
    return total

def bus_violations(net):
    """
    Returns squared error representing the amount by which bus voltages are above or below the bus voltage limits 
    """
    active_buses = net.bus.in_service.values

    vm = net.res_bus.vm_pu.values[active_buses]
    vmin = net.bus.min_vm_pu.values[active_buses]
    vmax = net.bus.max_vm_pu.values[active_buses]

    over_voltage = np.maximum(0.0, vm - 1.0)
    under_voltage = np.maximum(0.0, 1.0 - vm)

    voltage_violation = over_voltage + under_voltage
    bus_results = np.sum(voltage_violation)
    return bus_results

def line_violations(net):
    """
    Returns squared error representing the amount by which line loading exceeds the maximum 
    """
    loading = net.res_line.loading_percent.values
    max_loading = net.line.max_loading_percent.values

    line_violation = np.maximum(0.0, loading) # - max_loading)
    regularized_line_violation = [line / 100 for line in line_violation]
    line_results = np.sum(regularized_line_violation) / len(net.res_line)
    return line_results 

def grid_penalty(net):
    """
    Returns squared error representing the amount by which the system relies on selling/buying power from the grid 
    """
    global max_discrepancy

    return np.sum(net.res_ext_grid.p_mw / max_discrepancy) ** 2

def ext_grid_prices(net):
    price_paid = net.poly_cost[net.poly_cost["et"] == "ext_grid"]["cp1_eur_per_mw"].item() * net.res_ext_grid.at[0,"p_mw"]
    return abs(price_paid)

def grid_component_prices(net):
    return net.poly_cost[~net.poly_cost["et"].isin(["hydro", "pv"])]["cp0_eur"].sum()

def timeseries_runner(net, acc, **kwargs):
    """
    Wrapper function around the pandapower timeseries. 
    Runs each individial step in the timeseries and extracts the violation costs for each step
    """
    dispatch_storage(net, hydrogen_percentage=0.6)
    runpp(net, max_iteration=10, init="dc")

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
        # print(traceback.format_exc())
        return 1e12
    return total_cost


if __name__ == '__main__':
    continued_flag = "-cont" in sys.argv
    results_flag = "-results" in sys.argv
    
    net = init_run()
    net_stats = energy_analysis(net)

    max_discrepancy = net_stats["Peak Deficit MW"]
    monthly_profiles = average_day(net)
    
    problem_kwargs = {
        "ga_evaluate": ga_evaluator,
        "max_p_mw": abs(net_stats["Peak Deficit MW"]),
        "active_nodes_idx": net.bus[net.bus.in_service.values].index
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
    elif results_flag:
        with open("checkpoint.pkl", "rb") as f:
            ckpt = dill.load(f)
        algorithm = ckpt["algorithm"]
    else:
        algorithm = MixedVariableGA(pop_size=100)
        algorithm.termination = get_termination("n_gen", 1)

        # take a backup and clear our checkpoints csv file
        try:
            os.rename('..\\results\\checkpoints.csv', '..\\results\\checkpoints_backup.csv') 
        except FileExistsError:   # backup file already exists - remove then rename
            os.remove('..\\results\\checkpoints_backup.csv')
            os.rename('..\\results\\checkpoints.csv', '..\\results\\checkpoints_backup.csv') 
        # begin the new checkpoints csv file
        with open('..\\results\\checkpoints.csv', 'w+', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                        "n_gen", "n_eval", "F",
                        "batt_bus1", "batt_p_mw1", "batt_e_mwh1",
                        "bat_on2", "batt_bus2", "batt_p_mw2", "batt_e_mwh2",
                        "bat_on3", "batt_bus3", "batt_p_mw3", "batt_e_mwh3",
                        "h2_bus1", "h2_num_electrolyzers1", "h2_num_fuelcells1", "h2_num_tanks1",
                        "h2_on2", "h2_bus2", "h2_num_electrolyzers2", "h2_num_fuelcells2", "h2_num_tanks2"
                    ])
            f.close()

    # run Optimization
    try:
        result = minimize(
            problem,
            algorithm,
            verbose=True,
            termination=None,
            copy_algorithm=not continued_flag,
            save_history=True,
            callback=CheckpointCallback()
        )
    except KeyboardInterrupt:
        acc_sum = acc_totals["bus"] + acc_totals["components"] + acc_totals["grid_price"] + acc_totals["line"]
        print(f'Bus percentage: {acc_totals["bus"] / acc_sum}')
        print(f'Line percentage: {acc_totals["line"] / acc_sum}')
        print(f'Components percentage: {acc_totals["components"] / acc_sum}')
        print(f'Grid Price percentage: {acc_totals["grid_price"] / acc_sum}')

    print(f'Optimized result: {result.X}')

    if pool is not None:
        pool.close()
        pool.join()