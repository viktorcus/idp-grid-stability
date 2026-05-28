from pathlib import Path
from pandapower.networks.power_system_test_cases import case30
from pandapower.run import runpp, runopp
from pandapower.timeseries.run_time_series import run_timeseries, OutputWriter
from pandapower.diagnostic import Diagnostic
from tools.limits import bus_vm_pu_limits, line_loading_limits
import tools.graphs as graph
import profileloader as pl
import os, shutil    
import pandapower

bus_failures = []
line_failures = []
timestep = 0
test_date = "1/2/2026"

def run_collapse_with_extgrid(net, **kwargs):
    """
        Define extra behavior to wrap each power flow call in the time series.
        Assumes perfect responsiveness of external grid to our grid's conditions: 
        External grid connection will supply power during low demand periods and purchase
        power during excess production periods
    """
    global bus_failures, line_failures, timestep, test_date

    runpp(net=net, **kwargs)

    # detect buses or lines whose power flow results exceed limits
    bus_limits = bus_vm_pu_limits(net, limits=[0.9,1.1])
    line_limits = line_loading_limits(net)

    if(len(bus_limits) > 0 or len(line_limits) > 0):
        graph.plot_powerflow_result(net, test_date, timestep, results_dir="extgrid")
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

def init_run():
    """
        Reset net before a timeseries run, with default case 30 values and timeseries data imported from data files
    """
    # reset global variables
    global bus_failures, line_failures, timestep
    bus_failures = []
    line_failures = []
    timestep = 0

    # reset net
    net = case30()

     # import profiles for timeseries data
    load_control = pl.json_to_net_generic(net, "load", date=test_date)
    gen_control = pl.json_to_net_pv(net, date=test_date)
    tariff_control = pl.json_to_net_generic(net, "poly_cost", date=test_date)
    hydro_control = pl.json_to_net_hydro(net, date=test_date)

    return net


def init_results_dir(results_dir):
    # define the output path, and clear out previous run's data
    # deletion code snippet from https://stackoverflow.com/a/185941
    results_path = f'..\\results\\collapse\\{results_dir}'
    Path(results_path).mkdir(parents=True, exist_ok=True)
    for filename in os.listdir(results_path):
        file_path = os.path.join(results_path, filename)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
        except Exception as e:
            print('Failed to delete %s. Reason: %s' % (file_path, e))

    # define variables to be recorded as csv files
    ow = OutputWriter(net, 
                    output_path=results_path, 
                    output_file_type='.csv', csv_separator=",")
    ow.log_variable("res_gen", "p_mw")
    ow.log_variable("res_gen", "q_mvar")
    ow.log_variable("res_bus", "vm_pu")
    ow.log_variable("res_bus", "p_mw")
    ow.log_variable("res_bus", "q_mvar")
    ow.log_variable("res_line", "loading_percent")
    ow.log_variable("res_ext_grid", "p_mw")

    return net

def collect_results(results_dir):
    global bus_failures, line_failures, test_date

    bus_failures.sort()
    line_failures.sort()
    print(f'Buses exceeding limits: {bus_failures}')
    print(f'Lines exceeding limits: {line_failures}')

    graph.line_loading(line_failures, test_date, results_dir)
    graph.bus_vpu(bus_failures, test_date, results_dir)
    graph.graph_p_mw(test_date, "gen", results_dir)
    graph.graph_p_mw(test_date, "bus", results_dir)
    graph.graph_p_mw(test_date, "ext_grid", results_dir)

if __name__ == '__main__':
    # begin by importing the case 30 and the data controllers
    net = init_run()
    init_results_dir("extgrid")

    
    run_timeseries(net, continue_on_divergence=True, max_iteration=40, verbose=True, run=run_collapse_with_extgrid)
    collect_results("extgrid")



    net = init_run()
    init_results_dir("extgridless")
    
    net.bus["max_vm_pu"] = 10
    net.bus["min_vm_pu"] = 0
    net.line["max_loading_percent"] = 500
    net.ext_grid["max_p_mw"] = 1000
    net.ext_grid["min_p_mw"] = 0
    net.gen["controllable"] = False

    run_timeseries(net, continue_on_divergence=True, max_iteration=80, verbose=True, run=run_collapse_without_extgrid)
    collect_results("extgridless")