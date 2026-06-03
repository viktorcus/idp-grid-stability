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
from tools.test_runner import dispatch_storage
        
# define globals
test_date = "4/10/2026"
checkpoints_path = f'..\\results\\optimizer\\checkpoints.csv'

max_discrepancy = 0
bus_violation_cost = {}
line_violation_cost = {}
ext_grid_penalty_cost = {}
mse_temp = 0
rankings = {}


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


def energy_analysis(net):
    totals = 0
    for i, row in net.controller.iterrows():
        ctrl = row.object
        if ctrl.element in ['load', 'storage']:
            totals -= ctrl.data_source.df.sum(axis=1)
        elif ctrl.element not in ['poly_cost', 'timestep']:
            totals += ctrl.data_source.df.sum(axis=1)
    print(totals[0])

    return {
        "Peak Surplus": max(totals), 
        "Peak Deficit": min(totals),
        "Total Surplus": (totals.loc[lambda x : x > 0].sum() * .25).item(),
        "Total Deficit": (totals.loc[lambda x : x < 0].sum() * .25).item()
    }

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
    print(net.storage)

    ts = net["_timestep"]

    bus_violation_cost[ts] = bus_violations(net).item()
    line_violation_cost[ts] = line_violations(net).item()
    ext_grid_penalty_cost[ts] = grid_penalty(net).item()
    #print(ext_grid_penalty_cost)



def optimizer_trial(optimizer_params, bus_index):
    """
        Runner function to perform optimization on a particular bus
    """
    global timestep

    net = init_run()
    if len(optimizer_params) > 0:
        battery1 = create_storage(net, bus_index[0], 
                                name="battery",
                                p_mw=0, 
                                max_p_mw=optimizer_params[0],
                                max_q_mvar=optimizer_params[0],
                                min_p_mw=-optimizer_params[0],
                                min_q_mvar=-optimizer_params[0],
                                max_e_mwh=optimizer_params[0] * 4,
                                soc_percent=50,
                                controllable=True)
        storage_control = Battery(net=net, element_index=battery1.item())

        hydrogen1 = create_storage(net, bus_index[0] + 3,
                                   name="hydrogen",
                                   max_e_mwh=1000,
                                   p_mw=0,
                                   soc_percent=0,
                                   controllable=True)
        hydrogen_control = Hydrogen(net=net, element_index=hydrogen1.item())

    if len(optimizer_params) > 1:
        battery2 = create_storage(net, bus_index[1], 
                                p_mw=0, 
                                max_p_mw=optimizer_params[1],
                                max_q_mvar=optimizer_params[1],
                                min_p_mw=-optimizer_params[1],
                                min_q_mvar=optimizer_params[1],
                                max_e_mwh=-optimizer_params[1] * 4,
                                soc_percent=50,
                                controllable=True)
        storage_control = Battery(net=net, element_index=battery2.item())

    if len(optimizer_params) > 2:
        battery3 = create_storage(net, bus_index[2], 
                                p_mw=0, 
                                max_p_mw=optimizer_params[2],
                                max_q_mvar=optimizer_params[2],
                                min_p_mw=-optimizer_params[2],
                                min_q_mvar=-optimizer_params[2],
                                max_e_mwh=optimizer_params[2] * 4,
                                soc_percent=50,
                                controllable=True)
        storage_control = Battery(net=net, element_index=battery3.item())


    try:
        run_timeseries(net, continue_on_divergence=False, max_iteration=40, run=timeseries_runner, verbose=True)
    except: 
        print("model not converged")
        return -1

    total_cost = sum(bus_violation_cost.values()) + sum(line_violation_cost.values()) + sum(ext_grid_penalty_cost.values())
    print(f'   current params: {optimizer_params}, current err: {total_cost}')
    return total_cost


def target_buses():
    """
        Run optimization on all possible buses in the network
        Store the optimized value at each bus, and then from the set of buses, select
        the bus that had the best results after optimziation
    """

    global mse_temp, max_discrepancy

    net = init_run()
    net_stats = energy_analysis(net)
    max_discrepancy = max(net_stats["Peak Surplus"], abs(net_stats["Peak Deficit"]))
    num_buses = len(net.bus)

    optimizer_params = [max_discrepancy / 100]      # params representing mwh of 1+ batteries, divided by 100 for optimization 
    optimized_solution = -1
    min_cost = 1000

    print(energy_analysis(net))

    err = optimizer_trial((), [])
    maintain_rankings(net, (-1), err)

    # loop to test all possible locations of storage sites
    for bus1_idx in range(num_buses):    # storage site 1
        print(f'Optimization: Bus {bus1_idx}/{num_buses}')
        optimizer_wrapper = lambda opt_params: optimizer_trial([x * 100 for x in opt_params], [bus1_idx])

        err = optimizer_wrapper(optimizer_params)
        maintain_rankings(net, (bus1_idx), err)

        """res = optimize.minimize(optimizer_wrapper, optimizer_params, method='Nelder-Mead', tol=0.0000001)
        print(f'MSE: {mse_temp}, Results: {res}')
        if mse_temp < min_cost:
            min_cost = mse_temp
            optimized_solution = optimizer_params"""

    optimizer_params = [max_discrepancy / 100 / 2, max_discrepancy / 100 / 2]
    for bus1_idx in range(num_buses):    # storage site 1
        for bus2_idx in range(num_buses):   # storage site 2
            if bus1_idx != bus2_idx:
                print(f'Optimization: Bus {bus1_idx} and {bus2_idx}')
                optimizer_wrapper = lambda opt_params: optimizer_trial([x * 100 for x in opt_params], 
                                                                       [bus1_idx, bus2_idx])

                err = optimizer_wrapper(optimizer_params)
                maintain_rankings(net, (bus1_idx, bus2_idx), err)

                """res = optimize.minimize(optimizer_wrapper, optimizer_params, method='Nelder-Mead')
                print(f'MSE: {mse_temp}, Results: {res}')
                if mse_temp < min_cost:
                    min_cost = mse_temp
                    optimized_solution = optimizer_params"""

    optimizer_params = [max_discrepancy / 100 / 3, max_discrepancy / 100 / 3]
    for bus1_idx in range(num_buses):    # storage site 1
        for bus2_idx in range(num_buses):   # storage site 2
            for bus3_idx in range(num_buses):   # storage site 3
                # exclude duplicated buses
                if len([bus1_idx, bus2_idx, bus3_idx]) == len(set([bus1_idx, bus2_idx, bus3_idx])):
                    print(f'Optimization: Bus {bus1_idx}, {bus2_idx}, {bus3_idx}')
                    optimizer_wrapper = lambda opt_params: optimizer_trial([x * 100 for x in [opt_params]], 
                                                            [bus1_idx, bus2_idx, bus3_idx])

                    err = optimizer_wrapper(optimizer_params)
                    maintain_rankings(net, (bus1_idx, bus2_idx, bus3_idx), err)

                    """res = optimize.minimize(optimizer_wrapper, optimizer_params, method='Nelder-Mead')
                    print(f'MSE: {mse_temp}, Results: {res}') 
                    if mse_temp < min_cost:
                        min_cost = mse_temp
                        optimized_solution = optimizer_params"""

def optimize_targets():
    global rankings

    for bus_list, err in rankings:
        net = init_run()

        optimizer_params = [bus_list[0]]
        if len(bus_list) > 1: 
            optimizer_params.append(bus_list[1])
        if len(bus_list) > 2: 
            optimizer_params.append(bus_list[2])

        optimizer_wrapper = lambda opt_params: optimizer_trial([x * 100 for x in [opt_params]], 
                                                            list(bus_list))
        res = optimize.minimize(optimizer_wrapper, optimizer_params, method='Nelder-Mead')
        

        # store optimized values from target bus combinations
        rankings[bus_list] = res
    
        

if __name__ == '__main__':

    target_buses()
    optimize_targets()