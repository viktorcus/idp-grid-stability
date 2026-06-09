import numpy as np
from pandapower.run import runpp
from pandapower.timeseries.run_time_series import run_timeseries
from pandapower.networks.power_system_test_cases import case30
from pandapower.create import create_storage
import profileloader as pl
from control.hydrogen import Hydrogen
from control.battery import Battery
from control.timestep import TimeStepTracker
from tools.ga.problem import GridPlanningProblem
from tools.test_runner import *
from pymoo.algorithms.soo.nonconvex.ga import GA
from pymoo.optimize import minimize
from tools.ga.solution import Solution
import multiprocessing
from pymoo.parallelization.starmap import StarmapParallelization
from pymoo.operators.sampling.rnd import FloatRandomSampling
import sys
import dill
import traceback
from pymoo.core.callback import Callback
from pymoo.termination import get_termination

# callback class for algorithm checkpoints
class CheckpointCallback(Callback):

    def notify(self, algorithm):

        with open("checkpoint.pkl", "wb") as f:
            dill.dump({"algorithm": algorithm}, f)
        

# define globals
test_date = None

max_discrepancy = 0
bus_violation_cost = {}
line_violation_cost = {}
ext_grid_penalty_cost = {}
ext_grid_prices_cost = {}

monthly_profiles = {}
iteration_counter = 0


def init_run(date=None):
    """
        Reset net before a timeseries run, with default case 30 values and timeseries data imported from data files
    """
    # reset global variables
    global bus_violation_cost, line_violation_cost, ext_grid_penalty_cost, ext_grid_prices_cost, test_date
    bus_violation_cost = {}
    line_violation_cost = {}
    ext_grid_penalty_cost = {}
    ext_grid_prices_cost = {}
    test_date = date

    # reset net
    net = case30()

     # import profiles for timeseries data
    tariff_control = pl.json_to_net_generic(net, "poly_cost", date=date)
    load_control = pl.json_to_net_generic(net, "load", date=date)
    net.load["q_mvar"] = 0      # not accounting for this for the time being
    gen_control = pl.json_to_net_pv(net, date=date)
    hydro_control = pl.json_to_net_hydro(net, date=date)
    tracker_control = TimeStepTracker(net)
    net.ext_grid["controllable"] = False
    net.gen["controllable"] = False

    return net

def deploy_net_runner(solution: Solution, month=None, date=None):
    """ 
    Dispatches the storage options according to the current GA optimizer solution, and runs the timeseries
    """
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

    run_timeseries(net, continue_on_divergence=False, max_iteration=40, run=timeseries_runner, verbose=True, time_steps=range(0,96))  
    return sum(bus_violation_cost.values()) + sum(line_violation_cost.values()) + sum(ext_grid_penalty_cost.values()) + sum(ext_grid_prices_cost.values())

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

    line_violation = np.maximum(0.0, loading - max_loading) / 100
    return np.sum(line_violation ** 2)

def grid_penalty(net):
    """
    Returns squared error representing the amount by which the system relies on selling/buying power from the grid 
    """
    return (net.res_ext_grid.p_mw / max_discrepancy) ** 2

def ext_grid_prices(net):
    return abs(net.poly_cost[net.poly_cost["et"] == "ext_grid"]["cp1_eur_per_mw"].item() * net.res_ext_grid.at[0,"p_mw"])

def grid_component_prices(net):
    return net.poly_cost["cp0_eur"].sum()

def timeseries_runner(net, **kwargs):
    """
    Wrapper function around the pandapower timeseries. 
    Runs each individial step in the timeseries and extracts the violation costs for each step
    """
    global bus_violation_cost, line_violation_cost, ext_grid_penalty_cost, ext_grid_prices_cost

    dispatch_storage(net, strategy='battery_first')
    runpp(net, max_iteration=40)

    ts = net["_timestep"]

    bus_violation_cost[ts] = bus_violations(net).item()
    line_violation_cost[ts] = line_violations(net).item()
    ext_grid_penalty_cost[ts] = grid_penalty(net).item()
    ext_grid_prices_cost[ts] = ext_grid_prices(net).item()



def ga_evaluator(solution: Solution):
    """
    Runs the net timeseries for all target trials: the two worst case days, and the typical day for each month
    """

    global monthly_profiles, iteration_counter, net_stats
    total_cost = 0
    iteration_counter += 1

    try:

        for month in range(1,13):
            total_cost += deploy_net_runner(solution, month=month)
        #total_cost += deploy_net_runner(solution, date=net_stats["Peak Surplus Date"])
        #total_cost += deploy_net_runner(solution, date=net_stats["Peak Deficit Date"])
    except Exception as e: 
        # break if the net does not converge on any step in the timeseries, and return the maximum penalty.
        #print(e)
        return 1e20


    print(f'generation {math.floor(iteration_counter / 60) + 1}  iteration  {(iteration_counter % 60)}')
    print(f'bus err: {sum(bus_violation_cost.values())}   line err: {sum(line_violation_cost.values())}  grid reliance penalty:  {sum(ext_grid_penalty_cost.values())}   grid prices: {sum(ext_grid_prices_cost.values())}   components: {grid_component_prices(net)}   total cost {total_cost}')    
    
     # add in the last remaining penalty for the cost of components required for this iteration's solution
    total_cost += grid_component_prices(net)        
    return total_cost


if __name__ == '__main__':
    continued_flag = "-cont" in sys.argv

    net = init_run()
    net_stats = energy_analysis(net)
    print(net_stats)
    max_discrepancy = net_stats["Peak Deficit"]
    monthly_profiles = average_day(net)

    algorithm = GA(pop_size=120, sampling=FloatRandomSampling())

    start_pop = None

    if continued_flag:
        with open("checkpoint.pkl", "rb") as f:
            ckpt = dill.load(f)

        algorithm = ckpt["algorithm"]
        algorithm.n_gen += 1
        algorithm.termination = get_termination("n_gen", algorithm.n_gen + 5)
        print(f'resuming at {algorithm.n_gen} generations ({algorithm.evaluator.n_eval} evals)')
    else:
        algorithm = GA(pop_size=120, sampling=FloatRandomSampling())
        algorithm.termination = get_termination("n_gen", 2)
    result = []

    # if running as a Colab, execute the program using 8 processes
    if "gdrive" in os.getcwd():
        n_processes = 8
        pool = multiprocessing.Pool(n_processes)
        runner = StarmapParallelization(pool.starmap)

        problem = GridPlanningProblem(ga_evaluate=ga_evaluator, max_p_mw=abs(net_stats["Peak Deficit"]), elementwise_runner=runner)
        result = minimize(
            problem, 
            algorithm, 
            verbose=True, 
            termination=None, 
            copy_algorithm=not continued_flag, 
            save_history=True, 
            callback=CheckpointCallback())
    # otherwise, execute as only a single process 
    else:
        problem = GridPlanningProblem(ga_evaluate=ga_evaluator, max_p_mw=abs(net_stats["Peak Deficit"]))
        result = minimize(
            problem, 
            algorithm, 
            verbose=True, 
            termination=None, 
            copy_algorithm=not continued_flag, 
            save_history=True,
            callback=CheckpointCallback())

    print(f'Oprimized result: {result.X}')

    if "gdrive" in os.getcwd():     # close multiprocess pools
        pool.close()
    
