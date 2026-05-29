import numpy as np
from pandapower.run import runpp, runopp
from pandapower.timeseries.run_time_series import run_timeseries, OutputWriter
from pandapower.networks.power_system_test_cases import case30
from pandapower.create import create_storage
import profileloader as pl
import scipy.optimize as optimize
from control.battery import Battery
from enum import Enum
from tools import jacobian
        

test_date = "5/1/2026"
bus_failures = []
line_failures = []
timestep = 0
mse_temp = 0

class OptParams(Enum):
    MAX_P_MW = 0
    MAX_E_MWH = 1
    MAX_Q_MVAR = 2


def init_run():
    """
        Reset net before a timeseries run, with default case 30 values and timeseries data imported from data files
    """
    # reset global variables
    global bus_failures, line_failures, timestep, mse_temp
    bus_failures = []
    line_failures = []
    timestep = 0
    mse_temp = 0

    # reset net
    net = case30()

     # import profiles for timeseries data
    load_control = pl.json_to_net_generic(net, "load", date=test_date)
    gen_control = pl.json_to_net_pv(net, date=test_date)
    tariff_control = pl.json_to_net_generic(net, "poly_cost", date=test_date)
    hydro_control = pl.json_to_net_hydro(net, date=test_date)

    return net

def timeseries_runner(net, **kwargs):
    global mse_temp 

    runpp(net)
    mse_temp += jacobian.vs_mse(net)


def optimizer_trial(optimizer_params, bus_index):
    """
        Runner function to perform optimization on a particular bus
    """
    net = init_run()
    battery = create_storage(net, bus_index, 
                             p_mw=optimizer_params[OptParams.MAX_P_MW.value], 
                             max_p_mw=optimizer_params[OptParams.MAX_P_MW.value],
                             min_p_mw=-optimizer_params[OptParams.MAX_P_MW.value],
                             max_e_mwh=optimizer_params[OptParams.MAX_E_MWH.value],
                             max_q_mvar=optimizer_params[OptParams.MAX_Q_MVAR.value],
                             min_q_mvar=-optimizer_params[OptParams.MAX_Q_MVAR.value],
                             soc_percent=50,
                             controllable=True)
    storage_control = Battery(net=net, element_index=battery.item())

    run_timeseries(net, continue_on_divergence=True, max_iteration=40, run=timeseries_runner, verbose=True)

    print(f'   current params: {optimizer_params}, current mse: {mse_temp}')
    return mse_temp


def run_optimizer():
    """
        Run optimization on all possible buses in the network
        Store the optimized value at each bus, and then from the set of buses, select
        the bus that had the best results after optimziation
    """

    global mse_temp

    optimizer_params = [100, 100, 100]
    min_cost = 1000

    net = init_run()
    num_buses = len(net.bus)

    for bus_idx in range(num_buses):
        print(f'Optimization: Bus {bus_idx}/{num_buses}')
        optimizer_wrapper = lambda opt_params: optimizer_trial(opt_params, bus_idx)
        res = optimize.minimize(optimizer_wrapper, optimizer_params)
        print(f'MSE: {mse_temp}, Results: {res}')



if __name__ == '__main__':
    # begin by importing the case 30 and the data controllers
    run_optimizer()
