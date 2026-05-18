from pandapower.networks.power_system_test_cases import case30
from pandapower.run import runpp, runopp
from pandapower.timeseries.run_time_series import run_timeseries, OutputWriter
from tools.limits import bus_vm_pu_limits, line_loading_limits
import tools.graphs as graph
import profileloader as pl
import os, shutil    
from pandapower.plotting.plotly import pf_res_plotly

bus_failures = []
line_failures = []
timestep = 0
test_date = "1/5/2026"

def run_test(net, **kwargs):
    '''
        Define extra behavior to wrap each power flow call in the time series
    '''
    global bus_failures, line_failures, timestep, test_date

    runpp(net=net, **kwargs)

    # detect buses or lines whose power flow results exceed limits
    bus_limits = bus_vm_pu_limits(net)
    line_limits = line_loading_limits(net)

    if(len(bus_limits) > 0 or len(line_limits) > 0):
        graph.plot_powerflow_result(net, test_date, timestep)
    bus_failures = list(set(bus_failures).union(bus_limits))
    line_failures = list(set(line_failures).union(line_limits))
    timestep += 1

if __name__ == '__main__':
    # begin by importing the case 30
    net = case30()

    # define the output path, and clear out previous run's data
    # deletion code snippet from https://stackoverflow.com/a/185941
    results_dir = "..\\results\\collapse"
    for filename in os.listdir(results_dir):
        file_path = os.path.join(results_dir, filename)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
        except Exception as e:
            print('Failed to delete %s. Reason: %s' % (file_path, e))

    # import profiles for timeseries data
    load_control = pl.json_to_net(net, "load", date=test_date)
    gen_control = pl.json_to_net(net, "gen", date=test_date)
    tariff_control = pl.json_to_net(net, "poly_cost", date=test_date)


    ow = OutputWriter(net, 
                    output_path=results_dir, 
                    output_file_type='.csv', csv_separator=",")
    ow.log_variable("res_gen", "p_mw")
    ow.log_variable("res_gen", "q_mvar")
    ow.log_variable("res_bus", "vm_pu")
    ow.log_variable("res_bus", "p_mw")
    ow.log_variable("res_bus", "q_mvar")
    ow.log_variable("res_line", "loading_percent")
    
    run_timeseries(net, continue_on_divergence=True, max_iteration=40, verbose=True, run=run_test)

    bus_failures.sort()
    line_failures.sort()
    print(f'Buses exceeding limits: {bus_failures}')
    print(f'Lines exceeding limits: {line_failures}')

    graph.line_loading(line_failures, test_date)
    graph.bus_vpu(bus_failures, test_date)
    