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
from control.timestep import TimeStepTracker
from tools.test_runner import * 
import traceback
import copy

bus_failures = []
line_failures = []
timestep = 0
test_date = None
results_dir = ""
monthly_profiles = {}

all_power = []

benchmarks = {
    "line_overload_intervals": 0,
    "bus_overload_intervals": 0,
    "power_sold_to_ext_grid_mwh": 0,
    "power_bought_from_ext_grid_mwh": 0,
    "h2_produced_kg": 0,
    "h2_consumed_kg": 0,
    "battery_charged_mwh": 0,
    "battery_discharged_mwh": 0,
    "max_line_loading_percent": 0,
    "max_bus_vpu_fluctuation": 0,
    "power_purchase_cost_eur": 0,
    "ext_grid_p_mw": 0
}
benchmark_holder = copy.deepcopy(benchmarks)
benchmark_holder["timestep"] = 0

def run_collapse_with_extgrid(net, **kwargs):
    """
        Define extra behavior to wrap each power flow call in the time series.
        Assumes perfect responsiveness of external grid to our grid's conditions: 
        External grid connection will supply power during low demand periods and purchase
        power during excess production periods
    """
    global bus_failures, line_failures, timestep, test_date, results_dir

    dispatch_storage(net, hydrogen_percentage=0.4)

    try:
        runpp(net=net, init="dc", **kwargs)
    except: 
        diag = Diagnostic()
        result = diag.diagnose_network(net, report_style="detailed")
        #print(traceback.format_exc())    

    # detect buses or lines whose power flow results exceed limits
    bus_limits, _ = bus_vm_pu_limits(net, limits=[0.95,1.05])
    line_limits, _ = line_loading_limits(net)

    if(len(bus_limits) > 0 or len(line_limits) > 0):
        graph.plot_powerflow_result(net, test_date, timestep, results_dir=results_dir)
    bus_failures = list(set(bus_failures).union(bus_limits))
    line_failures = list(set(line_failures).union(line_limits))
    timestep += 1

def run_benchmarks(element_runner = None, solution = None, date = None):
    global benchmark_holder, benchmarks, all_power

    if date == None:

        for month in range(1,13):
            net = init_net()
            net = extract_monthly_profile(net, monthly_profiles, month)
            if element_runner is not None:
                net = element_runner(net, solution)

            run_timeseries(net, continue_on_divergence=True, max_iteration=40, verbose=True, run=run_benchmarks_test)

            # get final timestep values
            """benchmarks["battery_charged_mwh"] += benchmark_holder["battery_charged_mwh"]
            benchmarks["battery_discharged_mwh"] += benchmark_holder["battery_discharged_mwh"]
            benchmarks["bus_overload_intervals"] += benchmark_holder["bus_overload_intervals"]
            benchmarks["h2_consumed_kg"] += benchmark_holder["h2_consumed_kg"]
            benchmarks["h2_produced_kg"] += benchmark_holder["h2_produced_kg"]
            benchmarks["line_overload_intervals"] += benchmark_holder["line_overload_intervals"]
            benchmarks["power_bought_from_ext_grid_mwh"] += benchmark_holder["power_bought_from_ext_grid_mwh"]
            benchmarks["power_sold_to_ext_grid_mwh"] += benchmark_holder["power_sold_to_ext_grid_mwh"]
            benchmarks["power_purchase_cost_eur"] += benchmark_holder["power_purchase_cost_eur"]
            all_power.append(net.res_ext_grid["p_mw"][0])
            all_power"""
    else:
        net = init_net(date)
        if element_runner is not None:
            net = element_runner(net, solution)
        run_timeseries(net, continue_on_divergence=True, max_iteration=40, verbose=True, run=run_benchmarks_test)

        benchmarks["battery_charged_mwh"] += benchmark_holder["battery_charged_mwh"]
        benchmarks["battery_discharged_mwh"] += benchmark_holder["battery_discharged_mwh"]
        benchmarks["bus_overload_intervals"] += benchmark_holder["bus_overload_intervals"]
        benchmarks["h2_consumed_kg"] += benchmark_holder["h2_consumed_kg"]
        benchmarks["h2_produced_kg"] += benchmark_holder["h2_produced_kg"]
        benchmarks["line_overload_intervals"] += benchmark_holder["line_overload_intervals"]
        benchmarks["power_bought_from_ext_grid_mwh"] += benchmark_holder["power_bought_from_ext_grid_mwh"]
        benchmarks["power_sold_to_ext_grid_mwh"] += benchmark_holder["power_sold_to_ext_grid_mwh"]
        benchmarks["power_purchase_cost_eur"] += benchmark_holder["power_purchase_cost_eur"]

    print(benchmarks)
    print(line_failures)
    print(bus_failures)

def run_benchmarks_test(net, **kwargs):
    """
        Define extra behavior to wrap each power flow call in the time series.
        Assumes perfect responsiveness of external grid to our grid's conditions: 
        External grid connection will supply power during low demand periods and purchase
        power during excess production periods
    """
    global bus_failures, line_failures, test_date, results_dir, benchmark_holder, benchmarks, all_power

    dispatch_storage(net, hydrogen_percentage=0.4)

    # net may run a powerflow one or a few times per time step, depending on the number of controllers
    # as a result, necessary to control for the current time step, so stats are only updated after a time step has completed
    if net["_timestep"] != benchmark_holder["timestep"]:
        benchmarks["battery_charged_mwh"] += benchmark_holder["battery_charged_mwh"]
        benchmarks["battery_discharged_mwh"] += benchmark_holder["battery_discharged_mwh"]
        benchmarks["bus_overload_intervals"] += benchmark_holder["bus_overload_intervals"]
        benchmarks["h2_consumed_kg"] += benchmark_holder["h2_consumed_kg"]
        benchmarks["h2_produced_kg"] += benchmark_holder["h2_produced_kg"]
        benchmarks["line_overload_intervals"] += benchmark_holder["line_overload_intervals"]
        benchmarks["power_bought_from_ext_grid_mwh"] += benchmark_holder["power_bought_from_ext_grid_mwh"]
        benchmarks["power_sold_to_ext_grid_mwh"] += benchmark_holder["power_sold_to_ext_grid_mwh"]
        benchmarks["power_purchase_cost_eur"] += benchmark_holder["power_purchase_cost_eur"]
        all_power.append(-1 * benchmark_holder["ext_grid_p_mw"])


    try:
        runpp(net=net, init="dc", **kwargs)
    except: 
        diag = Diagnostic()
        result = diag.diagnose_network(net, report_style="detailed")
        #print(traceback.format_exc())    

    # detect buses or lines whose power flow results exceed limits
    bus_limits, max_bus_err = bus_vm_pu_limits(net, limits=[0.95,1.05])
    line_limits, max_line_err = line_loading_limits(net)

    # get sum of hydrogen/BESS power currently in system
    h2_mw = net.storage[net.storage["name"] == "hydrogen"]["p_mw"].sum()
    batt_mw = net.storage[net.storage["name"] == "battery"]["p_mw"].sum()

    # create lists of buses/lines exceeding threshholds
    bus_failures = list(set(bus_failures).union(bus_limits))
    line_failures = list(set(line_failures).union(line_limits))

    # get the cost to purchase power from the grid at the time-dependent rates
    power_purchase_cost = net.poly_cost[net.poly_cost["et"] == "ext_grid"]["cp1_eur_per_mw"].item() * max(net.res_ext_grid["p_mw"][0], 0) * .25

    # store stats in a temporary holding structure until we know the timestep is complete
    benchmark_holder["timestep"] = net["_timestep"]
    benchmark_holder["line_overload_intervals"] = len(line_limits)
    benchmark_holder["bus_overload_intervals"] = len(bus_limits)
    benchmark_holder["power_bought_from_ext_grid_mwh"] = max(net.res_ext_grid["p_mw"][0], 0) * .25
    benchmark_holder["power_sold_to_ext_grid_mwh"] = min(net.res_ext_grid["p_mw"][0], 0) * -.25
    benchmark_holder["h2_produced_kg"] = max(h2_mw, 0) * .25
    benchmark_holder["h2_consumed_kg"] = min(h2_mw, 0) * -.25
    benchmark_holder["battery_charged_mwh"] = max(batt_mw, 0) * .25
    benchmark_holder["battery_discharged_mwh"] = min(batt_mw, 0) * -.25
    benchmark_holder["line_overload_intervals"] = len(line_limits)
    benchmark_holder["bus_overload_intervals"] = len(bus_limits)
    benchmark_holder["power_purchase_cost_eur"] = power_purchase_cost
    benchmark_holder["ext_grid_p_mw"] = net.res_ext_grid["p_mw"][0]

    if abs(max_bus_err) > abs(benchmarks["max_bus_vpu_fluctuation"]): benchmarks["max_bus_vpu_fluctuation"] = max_bus_err
    if max_line_err > benchmarks["max_line_loading_percent"]: benchmarks["max_line_loading_percent"] = max_line_err


    #if benchmarks["max_bus_vpu_fluctuation_percent"] 

def init_net(date=None):
    # reset net
    net = case30()

     # import profiles for timeseries data
    load_control = pl.json_to_net_generic(net, "load", date=date)
    gen_control = pl.json_to_net_pv(net, date=date)
    tariff_control = pl.json_to_net_generic(net, "poly_cost", date=date)
    hydro_control = pl.json_to_net_hydro(net, date=date)
    net = pl.json_to_bus_coords(net)
    net = pl.json_to_lines(net)
    tracker_control = TimeStepTracker(net)

    return net

def init_run(date=None):
    """
        Reset net before a timeseries run, with default case 30 values and timeseries data imported from data files
    """
    # reset global variables
    global bus_failures, line_failures, timestep, test_date, monthly_profiles, benchmark_holder, benchmarks, all_power
    bus_failures = []
    line_failures = []
    all_power.clear()
    timestep = 0
    test_date=date

    print(all_power)

    benchmarks = {
        "line_overload_intervals": 0,
        "bus_overload_intervals": 0,
        "power_sold_to_ext_grid_mwh": 0,
        "power_bought_from_ext_grid_mwh": 0,
        "h2_produced_kg": 0,
        "h2_consumed_kg": 0,
        "battery_charged_mwh": 0,
        "battery_discharged_mwh": 0,
        "max_line_loading_percent": 0,
        "max_bus_vpu_fluctuation": 0,
        "power_purchase_cost_eur": 0
    }
    benchmark_holder = copy.deepcopy(benchmarks)
    benchmark_holder["timestep"] = 0

    # reset net
    net = init_net(date)

    if monthly_profiles == {}:
        monthly_profiles = average_day(net, span='month')
    #print(monthly_profiles)

    return net

def element_runner(net, solution): 
        battery1 = create_storage(net, bus=solution["batt_bus1"], 
                                name="battery",
                                p_mw=0, 
                                max_p_mw=solution["batt_p_mw1"],
                                max_q_mvar=solution["batt_p_mw1"],
                                min_p_mw=-solution["batt_p_mw1"],
                                min_q_mvar=-solution["batt_p_mw1"],
                                max_e_mwh=solution["batt_e_mwh1"],
                                soc_percent=50,
                                controllable=True)
        storage_control = Battery(net=net, element_index=battery1.item())
        net.poly_cost = storage_control.create_cost_element(net)
        if solution["bat_on2"]:
            battery2 = create_storage(net, bus=solution["batt_bus2"], 
                                    name="battery",
                                    p_mw=0,
                                    max_p_mw=solution["batt_p_mw2"],
                                    max_q_mvar=solution["batt_p_mw2"],
                                    min_p_mw=-solution["batt_p_mw2"],
                                    min_q_mvar=-solution["batt_p_mw2"],
                                    max_e_mwh=solution["batt_e_mwh2"],
                                    soc_percent=50,
                                    controllable=True)
            storage_control = Battery(net=net, element_index=battery2.item())
            net.poly_cost = storage_control.create_cost_element(net)
        if solution["bat_on3"]:
            battery3 = create_storage(net, bus=solution["batt_bus3"], 
                                    name="battery",
                                    p_mw=0, 
                                    max_p_mw=solution["batt_p_mw3"],
                                    max_q_mvar=solution["batt_p_mw3"],
                                    min_p_mw=-solution["batt_p_mw3"],
                                    min_q_mvar=-solution["batt_p_mw3"],
                                    max_e_mwh=solution["batt_e_mwh3"],
                                    soc_percent=50,
                                    controllable=True)
            storage_control = Battery(net=net, element_index=battery3.item())
            net.poly_cost = storage_control.create_cost_element(net)


        hydrogen1 = create_storage(net, bus=solution["h2_bus1"], 
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
                                        num_electrolyzer_units=solution["h2_num_electrolyzers1"], 
                                        num_fuel_cells=solution["h2_num_fuelcells1"],
                                        num_tanks=solution["h2_num_tanks1"])
        net.poly_cost = storage_control.create_cost_element(net)

        if solution["h2_on2"]:
            hydrogen2 = create_storage(net, bus=solution["h2_bus2"], 
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
                                        num_electrolyzer_units=solution["h2_num_electrolyzers2"], 
                                        num_fuel_cells=solution["h2_num_fuelcells2"],
                                        num_tanks=solution["h2_num_tanks2"])
            net.poly_cost = storage_control.create_cost_element(net)
        return net


if __name__ == '__main__':
    # begin by importing the case 30 and the data controllers   
    net = init_run(date=None)
    net_stats = energy_analysis(net)
    max_discrepancy = abs(net_stats["Peak Deficit MW"])
    print(net_stats)

    results_dir = "collapse\\extgrid"
    init_results_dir(net, results_dir) 
    #run_timeseries(net, continue_on_divergence=True, max_iteration=40, verbose=True, run=run_collapse_with_extgrid)
    #collect_results(net, results_dir, bus_failures, line_failures, test_date)


    """ ********* FAILURE SCENARIOS ************** """
    """net = init_run(date=net_stats["Peak Surplus Date"])
    results_dir = "collapse\\single_storage_surplus"
    init_results_dir(net, results_dir) 
    run_timeseries(net, continue_on_divergence=True, max_iteration=40, verbose=True, run=run_collapse_with_extgrid)
    collect_results(net, results_dir, bus_failures, line_failures, test_date, scenario="Peak Surplus Date (MW): ")

    net = init_run(date=net_stats["Peak Deficit Date"])
    results_dir = "collapse\\single_storage_deficit"
    init_results_dir(net, results_dir) 
    run_timeseries(net, continue_on_divergence=True, max_iteration=40, verbose=True, run=run_collapse_with_extgrid)
    collect_results(net, results_dir, bus_failures, line_failures, test_date, scenario="Peak Deficit Date (MW): ")

    net = init_run(date=net_stats["Max Surplus Date"])
    results_dir = "collapse\\single_storage_surplus"
    init_results_dir(net, results_dir) 
    run_timeseries(net, continue_on_divergence=True, max_iteration=40, verbose=True, run=run_collapse_with_extgrid)
    collect_results(net, results_dir, bus_failures, line_failures, test_date, scenario="Peak Surplus Date (MWh): ")

    net = init_run(date=net_stats["Max Deficit Date"])
    results_dir = "collapse\\single_storage_deficit"
    init_results_dir(net, results_dir) 
    run_timeseries(net, continue_on_divergence=True, max_iteration=40, verbose=True, run=run_collapse_with_extgrid)
    collect_results(net, results_dir, bus_failures, line_failures, test_date, scenario="Peak Deficit Date (MWh): ")
"""
    
    net = init_run()
    results_dir = "collapse\\benchmarks"
    init_results_dir(net, results_dir) 
    run_benchmarks()
    all_power_benchmarks = copy.deepcopy(all_power)

    net = init_run()
    solution = {
            "batt_bus1": 4, "batt_p_mw1": 137.1530294, "batt_e_mwh1": 629.9683536, 
            "bat_on2": False, "batt_bus2": 14, "batt_p_mw2": 3.172117686, "batt_e_mwh2": 485.7060271,
            "bat_on3": True, "batt_bus3": 1, "batt_p_mw3": 111.8631245, "batt_e_mwh3": 720.2613741,
            "h2_bus1": 0, "h2_num_electrolyzers1": 4, "h2_num_fuelcells1": 141, "h2_num_tanks1": 98,
            "h2_on2": True, "h2_bus2": 16, "h2_num_electrolyzers2": 1, "h2_num_fuelcells2": 1470, "h2_num_tanks2": 99
        }
    results_dir = "collapse\\batt_hydr_storage"
    init_results_dir(net, results_dir) 
    run_benchmarks(element_runner, solution)

    net = init_run()
    solution = {
            "batt_bus1": 4, "batt_p_mw1": 142.3937268, "batt_e_mwh1": 746.8505773, 
            "bat_on2": True, "batt_bus2": 7, "batt_p_mw2": 71.118185, "batt_e_mwh2": 752.2437894,
            "bat_on3": True, "batt_bus3": 1, "batt_p_mw3": 116.7462569, "batt_e_mwh3": 774.9057081,
            "h2_bus1": 0, "h2_num_electrolyzers1": 2, "h2_num_fuelcells1": 693, "h2_num_tanks1": 267,
            "h2_on2": False, "h2_bus2": 16, "h2_num_electrolyzers2": 2, "h2_num_fuelcells2": 1470, "h2_num_tanks2": 99
        }
    results_dir = "collapse\\batt_hydr_storage"
    init_results_dir(net, results_dir) 
    run_benchmarks(element_runner, solution)
    all_power_test = copy.deepcopy(all_power)

    net = init_run()
    solution = {
            "batt_bus1": 6, "batt_p_mw1": 38.4, "batt_e_mwh1": 76.8, 
            "bat_on2": True, "batt_bus2": 13, "batt_p_mw2": 71.118185, "batt_e_mwh2": 752.2437894,
            "bat_on3": True, "batt_bus3": 1, "batt_p_mw3": 4.5, "batt_e_mwh3": 9.9,
            "h2_bus1": 6, "h2_num_electrolyzers1": 1, "h2_num_fuelcells1": 171, "h2_num_tanks1": 2,
            "h2_on2": False, "h2_bus2": 13, "h2_num_electrolyzers2": 1, "h2_num_fuelcells2": 22, "h2_num_tanks2": 1
        }
    results_dir = "collapse\\batt_hydr_storage2"
    init_results_dir(net, results_dir) 
    run_benchmarks(element_runner, solution)

    ax = sb.lineplot(data={"Baseline": all_power_benchmarks, "Optimized": all_power_test})
    ax.set(xlabel=f'time step/month', ylabel='power [MW]', title=f'Excess Power Flow: Comparison')
    month_labels = [
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
    ]
    month_ticks = [i * 96 + 48 for i in range(12)]
    ax.set_xticks(month_ticks)
    ax.set_xticklabels(month_labels)
    plt.show()

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