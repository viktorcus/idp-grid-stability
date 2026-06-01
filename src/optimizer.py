import numpy as np
import pandas as pd
from pandapower.run import runpp, runopp
from pandapower.timeseries.run_time_series import run_timeseries, OutputWriter
from pandapower.networks.power_system_test_cases import case30
from pandapower.create import create_storage
import profileloader as pl
import scipy.optimize as optimize
from control.battery import Battery
from enum import Enum
import seaborn as sb
from tools import jacobian
import matplotlib.pyplot as plt
        

test_date = "4/10/2026"
bus_violation_cost = 0
line_violation_cost = 0
timestep = 0
mse_temp = 0
rankings = []


def init_run():
    """
        Reset net before a timeseries run, with default case 30 values and timeseries data imported from data files
    """
    # reset global variables
    global bus_violation_cost, line_violation_cost, mse_temp
    bus_violation_cost = 0
    line_violation_cost = 0
    mse_temp = 0

    # reset net
    net = case30()

     # import profiles for timeseries data
    load_control = pl.json_to_net_generic(net, "load", date=test_date)
    net.load["q_mvar"] = 0      # not accounting for this for the time being
    gen_control = pl.json_to_net_pv(net, date=test_date)
    tariff_control = pl.json_to_net_generic(net, "poly_cost", date=test_date)
    hydro_control = pl.json_to_net_hydro(net, date=test_date)
    net.ext_grid["controllable"] = False
    net.gen["controllable"] = False

    return net

def energy_analysis(net):

    totals = 0
    for i, row in net.controller.iterrows():
        ctrl = row.object.data_source.df
        if row.object.element in ['load', 'storage']:
            totals -= ctrl.sum(axis=1)
        elif row.object.element != 'poly_cost':
            totals += ctrl.sum(axis=1)
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

def timeseries_runner(net, **kwargs):
    global bus_violation_cost, line_violation_cost 

    runpp(net, max_iteration=40)
    bus_violation_cost += bus_violations(net)
    line_violation_cost += line_violations(net)



def optimizer_trial(optimizer_params, bus_index):
    """
        Runner function to perform optimization on a particular bus
    """
    global mse_temp

    net = init_run()
    battery1 = create_storage(net, bus_index[0], 
                             p_mw=0, 
                             max_p_mw=optimizer_params[0],
                             max_q_mvar=optimizer_params[0],
                             min_p_mw=-optimizer_params[0],
                             min_q_mvar=-optimizer_params[0],
                             max_e_mwh=optimizer_params[0] * 4,
                             soc_percent=50,
                             controllable=True)
    storage_control = Battery(net=net, element_index=battery1.item())

    if len(optimizer_params) > 1:
        battery2 = create_storage(net, bus_index[1], 
                                p_mw=0, 
                                max_p_mw=optimizer_params[1],
                                max_q_mvar=optimizer_params[1],
                                min_p_mw=-optimizer_params[1],
                                min_q_mvar=optimizer_params[1],
                                min_e_mwh=-optimizer_params[1] * 4,
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
        return 1

    print(f'   current params: {optimizer_params}, current err: {bus_violation_cost + line_violation_cost}')
    return bus_violation_cost + line_violation_cost


def run_optimizer():
    """
        Run optimization on all possible buses in the network
        Store the optimized value at each bus, and then from the set of buses, select
        the bus that had the best results after optimziation
    """

    global mse_temp

    net = init_run()
    num_buses = len(net.bus)

    net_stats = energy_analysis(net)
    max_discrepancy = max(net_stats["Peak Surplus"], abs(net_stats["Peak Deficit"]))

    optimizer_params = [max_discrepancy / 100]      # params representing mwh of 1+ batteries, divided by 100 for optimization 
    optimized_solution = -1
    min_cost = 1000

    print(energy_analysis(net))



    # loop to test all possible locations of storage sites
    for bus1_idx in range(num_buses):    # storage site 1
        print(f'Optimization: Bus {bus1_idx}/{num_buses}')
        optimizer_wrapper = lambda opt_params: optimizer_trial(opt_params * 100, [bus1_idx])

        res = optimize.minimize(optimizer_wrapper, optimizer_params, method='Nelder-Mead')
        print(f'MSE: {mse_temp}, Results: {res}')
        if mse_temp < min_cost:
            min_cost = mse_temp
            optimized_solution = optimizer_params

    optimizer_params.append(100)
    for bus1_idx in range(num_buses):    # storage site 1
        for bus2_idx in range(num_buses):   # storage site 2
            if bus1_idx != bus2_idx:
                print(f'Optimization: Bus {bus1_idx} and {bus2_idx}')
                optimizer_wrapper = lambda opt_params: optimizer_trial([x * 100 for x in opt_params], 
                                                                       [bus1_idx, bus2_idx])

                res = optimize.minimize(optimizer_wrapper, optimizer_params, method='Nelder-Mead')
                print(f'MSE: {mse_temp}, Results: {res}')
                if mse_temp < min_cost:
                    min_cost = mse_temp
                    optimized_solution = optimizer_params

    optimizer_params.append(100)
    for bus1_idx in range(num_buses):    # storage site 1
        for bus2_idx in range(num_buses):   # storage site 2
            for bus3_idx in range(num_buses):   # storage site 3
                # exclude duplicated buses
                if len([bus1_idx, bus2_idx, bus3_idx]) == len(set([bus1_idx, bus2_idx, bus3_idx])):
                    print(f'Optimization: Bus {bus1_idx} and {bus2_idx}')
                    optimizer_wrapper = lambda opt_params: optimizer_trial([x * 100 for x in [opt_params]], 
                                                            [bus1_idx, bus2_idx, bus3_idx])

                    res = optimize.minimize(optimizer_wrapper, optimizer_params, method='Nelder-Mead')
                    print(f'MSE: {mse_temp}, Results: {res}') 
                    if mse_temp < min_cost:
                        min_cost = mse_temp
                        optimized_solution = optimizer_params


if __name__ == '__main__':
    # begin by importing the case 30 and the data controllers
    run_optimizer()
