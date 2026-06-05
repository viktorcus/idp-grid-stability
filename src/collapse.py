from pandapower.networks.power_system_test_cases import case30
from pandapower.run import runpp, runopp
from pandapower.timeseries.run_time_series import run_timeseries
from pandapower.diagnostic import Diagnostic
from tools.limits import bus_vm_pu_limits, line_loading_limits
import tools.graphs as graph
import profileloader as pl
from pandapower.create import create_storage
from control.battery import Battery
from control.hydrogen import Hydrogen
from tools.test_runner import * 

bus_failures = []
line_failures = []
timestep = 0
test_date = None
results_dir = ""

def run_collapse_with_extgrid(net, **kwargs):
    """
        Define extra behavior to wrap each power flow call in the time series.
        Assumes perfect responsiveness of external grid to our grid's conditions: 
        External grid connection will supply power during low demand periods and purchase
        power during excess production periods
    """
    global bus_failures, line_failures, timestep, test_date, results_dir

    dispatch_storage(net, strategy='battery_first')

    try:
        runpp(net=net, **kwargs)
    except: 
        diag = Diagnostic()
        result = diag.diagnose_network(net, report_style="detailed")    

    # detect buses or lines whose power flow results exceed limits
    bus_limits = bus_vm_pu_limits(net, limits=[0.9,1.1])
    line_limits = line_loading_limits(net)

    if(len(bus_limits) > 0 or len(line_limits) > 0):
        graph.plot_powerflow_result(net, test_date, timestep, results_dir=results_dir)
    bus_failures = list(set(bus_failures).union(bus_limits))
    line_failures = list(set(line_failures).union(line_limits))
    timestep += 1

def run_collapse_without_extgrid(net, **kwargs):
    """
        Define extra behavior to wrap each power flow call in the time series.
        Assumes grid is at max capacity when our grid is also at peak production. 
    """
    global bus_failures, line_failures, timestep, test_date


    #runopp(net=net, **kwargs)
    try: 
        runopp(net=net, **kwargs)
    except: 
        diag = Diagnostic()
        result = diag.diagnose_network(net, report_style="detailed")    
    
    # detect buses or lines whose power flow results exceed limits
    bus_limits = bus_vm_pu_limits(net, limits=[0.9,1.1])
    line_limits = line_loading_limits(net)

    if(len(bus_limits) > 0 or len(line_limits) > 0):
        graph.plot_powerflow_result(net, test_date, timestep, results_dir="extgridless")
    bus_failures = list(set(bus_failures).union(bus_limits))
    line_failures = list(set(line_failures).union(line_limits))
    timestep += 1

def init_run(date=None):
    """
        Reset net before a timeseries run, with default case 30 values and timeseries data imported from data files
    """
    # reset global variables
    global bus_failures, line_failures, timestep, test_date
    bus_failures = []
    line_failures = []
    timestep = 0
    test_date=date

    # reset net
    net = case30()

     # import profiles for timeseries data
    load_control = pl.json_to_net_generic(net, "load", date=date)
    gen_control = pl.json_to_net_pv(net, date=date)
    tariff_control = pl.json_to_net_generic(net, "poly_cost", date=date)
    hydro_control = pl.json_to_net_hydro(net, date=date)

    monthly_profiles = average_day(net, span='month')
    #print(monthly_profiles)

    return net


if __name__ == '__main__':
    # begin by importing the case 30 and the data controllers   
    net = init_run(date=None)
    net_stats = energy_analysis(net)
    max_discrepancy = abs(net_stats["Peak Deficit"])
    print(net_stats)

    print(average_day(net))

    results_dir = "collapse\\extgrid"
    init_results_dir(net, results_dir) 
    #run_timeseries(net, continue_on_divergence=True, max_iteration=40, verbose=True, run=run_collapse_with_extgrid)
    #collect_results(net, results_dir, bus_failures, line_failures, test_date)

    net = init_run(date=net_stats["Peak Surplus Date"])
    battery1 = create_storage(net, 6, 
                             name="battery",
                             p_mw=0, 
                             max_p_mw=max_discrepancy,
                             max_q_mvar=max_discrepancy,
                             min_p_mw=-max_discrepancy,
                             min_q_mvar=-max_discrepancy,
                             max_e_mwh=max_discrepancy * 4,
                             soc_percent=50,
                             controllable=True)
    storage_control = Battery(net=net, element_index=battery1.item())
    results_dir = "collapse\\single_storage"
    init_results_dir(net, results_dir) 
    #run_timeseries(net, continue_on_divergence=True, max_iteration=40, verbose=True, run=run_collapse_with_extgrid)
    #collect_results(net, results_dir, bus_failures, line_failures, test_date)


    net = init_run(date=net_stats["Peak Surplus Date"])
    battery1 = create_storage(net, 1, 
                             p_mw=0, 
                             name="battery",
                             max_p_mw=max_discrepancy,
                             max_q_mvar=max_discrepancy,
                             min_p_mw=-max_discrepancy,
                             min_q_mvar=-max_discrepancy,
                             max_e_mwh=max_discrepancy * 4,
                             soc_percent=50,
                             controllable=True)
    storage_control1 = Battery(net=net, element_index=battery1.item())
    battery2 = create_storage(net, 8, 
                             p_mw=0, 
                             name="battery",
                             max_p_mw=max_discrepancy,
                             max_q_mvar=max_discrepancy,
                             min_p_mw=-max_discrepancy,
                             min_q_mvar=-max_discrepancy,
                             max_e_mwh=max_discrepancy * 4,
                             soc_percent=50,
                             controllable=True)
    storage_control2 = Battery(net=net, element_index=battery2.item())
    hydrogen1 = create_storage(net, 4, 
                             name="hydrogen",
                             p_mw=0, 
                             max_p_mw=1000,
                             max_q_mvar=1000,
                             min_p_mw=-1000,
                             min_q_mvar=-1000,
                             max_e_mwh=10000,
                             soc_percent=0,
                             controllable=True)
    storage_control = Hydrogen(net=net, element_index=hydrogen1.item())
    hydrogen2 = create_storage(net, 9, 
                             name="hydrogen",
                             p_mw=0, 
                             max_p_mw=1000,
                             max_q_mvar=1000,
                             min_p_mw=-1000,
                             min_q_mvar=-1000,
                             max_e_mwh=10000,
                             soc_percent=0,
                             controllable=True)
    storage_control = Hydrogen(net=net, element_index=hydrogen2.item())
    results_dir = "collapse\\batt_hydr_storage"
    init_results_dir(net, results_dir) 
    run_timeseries(net, continue_on_divergence=True, max_iteration=60, verbose=True, run=run_collapse_with_extgrid)
    collect_results(net, results_dir, bus_failures, line_failures, test_date)


    """net = init_run()
    init_results_dir(net, "collapse\\extgridless")
    net.bus["max_vm_pu"] = 10
    net.bus["min_vm_pu"] = -10
    net.line["max_loading_percent"] = 1000
    net.ext_grid["max_p_mw"] = 1000
    net.ext_grid["max_q_mvar"] = 1000
    net.ext_grid["min_p_mw"] = 0
    net.ext_grid["min_q_mvar"] = 0
    net.ext_grid["controllable"] = True
    #net.gen["controllable"] = False

    run_timeseries(net, continue_on_divergence=True, max_iteration=80, verbose=True, run=run_collapse_without_extgrid)
    collect_results("collapse\\extgridless", bus_failures, line_failures, test_date)"""