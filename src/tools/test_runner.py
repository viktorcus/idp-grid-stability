from pandapower.run import runopp, runpp 
import os, shutil    
from pathlib import Path
from pandapower.timeseries.run_time_series import OutputWriter
from .graphs import *

def init_results_dir(net, results_dir):
    """
    Define the output path, and clear out previous run's data
    Deletion code snippet from https://stackoverflow.com/a/185941
    """
    results_path = f'..\\results\\{results_dir}'
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
    ow.log_variable("res_storage", "p_mw")
    ow.log_variable("storage", "soc_percent")

    return net

def collect_results(net, results_dir, bus_failures, line_failures, test_date):
    """
    After a power flow run, produce graphs based on results.
    """

    bus_failures.sort()
    line_failures.sort()
    print(f'Buses exceeding limits: {bus_failures}')
    print(f'Lines exceeding limits: {line_failures}')

    graph_battery_soc(net, test_date, results_dir)
    line_loading(line_failures, test_date, results_dir)
    bus_vpu(bus_failures, test_date, results_dir)
    graph_p_mw(test_date, "gen", results_dir)
    graph_p_mw(test_date, "bus", results_dir)
    graph_p_mw(test_date, "ext_grid", results_dir)
    graph_p_mw(test_date, "storage", results_dir)

def dispatch_storage(net, tolerance_mw=0.0001, strategy='', hydrogen_percentage=None):
    """
    strategy options = ["battery_first", "percentage_split"]
    Default method to determine how to allocate storage between Battery and Hydrogen.
    Calls functions to either allocate by order, or by percentage
    """

    # run initial powerflow to determine how much power discrepancy exists currently based on loads/generation
    net.storage.loc[net.storage["name"] != "hydro", "p_mw"] = 0
    runpp(net)

    power_discrepancy = -1 * net.res_ext_grid.p_mw.sum()

    # break early if loads/supply are already matching
    if abs(power_discrepancy) < tolerance_mw:
        return
    
    # identify elements to target
    hydrogen_idx = net.storage.index[
        net.storage.name.str.lower() == "hydrogen"
    ].tolist()

    battery_idx = net.storage.index[
        net.storage.name.str.lower() == "battery"
    ].tolist()
    battery_idx = [   # filter out batteries that are past their SOC limits
        idx
        for idx in battery_idx
        if (power_discrepancy > 0 and 
            net.storage.loc[idx]["soc_percent"] <= net.storage.loc[idx]["max_soc_percent"])
            or (power_discrepancy < 0 and 
                net.storage.loc[idx]["soc_percent"]>= net.storage.loc[idx]["min_soc_percent"])
    ]

    if strategy == 'battery_first':
        battery_first(net, power_discrepancy, battery_idx, hydrogen_idx, tolerance_mw)
    elif strategy == 'percentage_split':
        percentage_split(net, power_discrepancy, battery_idx, hydrogen_idx, tolerance_mw, hydrogen_percentage)

def percentage_split(net, power_discrepancy, battery_idx, hydrogen_idx, tolerance_mw=0.0001, hydrogen_percentage=40):
    """
    Allocate power between battery and hydrogen based on a specified percentage. 
    """
    
    remaining = abs(power_discrepancy)
    if power_discrepancy > 0:   # excess power: charge BESS
        total_available = sum(
                abs(net.storage.at[idx, "max_p_mw"])
                for idx in battery_idx
            )
        battery_dispatch = min(remaining * (1-hydrogen_percentage), total_available)
        share = battery_dispatch / len(battery_idx)

        for idx in battery_idx:
            limit = net.storage.at[idx, "max_p_mw"]
            actual = min(share, limit)
            net.storage.at[idx, "p_mw"] = actual
            remaining -= actual

        # allocate the specified percentage, plus any that remains, to hydrogen
        if remaining > tolerance_mw:

            for idx in hydrogen_idx:

                limit = net.storage.at[idx, "max_p_mw"]
                actual = min(remaining, limit)
                net.storage.at[idx, "p_mw"] = actual
                remaining -= actual

                if remaining <= tolerance_mw:
                    break

    else:       # discharge BESS
        # draw power from batteries first
        if battery_idx:

            total_available = sum(
                abs(net.storage.at[idx, "min_p_mw"])
                for idx in battery_idx
            )
            battery_dispatch = min(remaining, total_available)
            share = battery_dispatch / len(battery_idx)

            for idx in battery_idx:
                limit = net.storage.at[idx, "min_p_mw"]
                actual = min(share, -limit)
                net.storage.at[idx, "p_mw"] = -actual
                remaining -= actual

        # allocate any power that remains from hydrogen
        if remaining > tolerance_mw:

            for idx in hydrogen_idx:

                limit = net.storage.at[idx, "min_p_mw"]
                actual = min(remaining, -limit)
                if net.storage.at[idx, "stored_e_mwh"] >= abs(actual * 0.25):
                    net.storage.at[idx, "p_mw"] = -actual
                    remaining -= actual

                if remaining <= tolerance_mw:
                    break

    

def battery_first(net, power_discrepancy, battery_idx, hydrogen_idx, tolerance_mw=0.0001):
    """
    Allocate power first to batteries, then any remainder goes to/comes from hydrogen.
    """

    remaining = abs(power_discrepancy)

    if power_discrepancy > 0:   # excess power: charge BESS

        # allocate to batteries first 
        if battery_idx:

            total_available = sum(
                abs(net.storage.at[idx, "max_p_mw"])
                for idx in battery_idx
            )
            battery_dispatch = min(remaining, total_available)
            share = battery_dispatch / len(battery_idx)

            for idx in battery_idx:
                max_e_mwh = net.storage.at[idx, "max_soc_percent"] / 100.0 * net.storage.at[idx, "max_e_mwh"]
                current_e_mwh = net.storage.at[idx, "soc_percent"] / 100.0 * net.storage.at[idx, "max_e_mwh"]
                limit = net.storage.at[idx, "max_p_mw"]
                actual = min(share, limit)

                # if the ideal p_mw rate will cause overcharging by the next cycle, 
                # then set the limit to power the battery only up to the max SOC percent
                if (actual * 0.25) + current_e_mwh > max_e_mwh:
                    actual = (max_e_mwh - current_e_mwh) / 0.25
                net.storage.at[idx, "p_mw"] = actual
                remaining -= actual

        # allocate any power that remains to hydrogen
        if remaining > tolerance_mw:
            for idx in hydrogen_idx:

                limit = net.storage.at[idx, "max_p_mw"]
                actual = min(remaining, limit)
                net.storage.at[idx, "p_mw"] = actual
                remaining -= actual

                if remaining <= tolerance_mw:
                    break
    
    else:       # discharge BESS
        # draw power from batteries first
        if battery_idx:

            total_available = sum(
                abs(net.storage.at[idx, "min_p_mw"])
                for idx in battery_idx
            )
            battery_dispatch = min(remaining, total_available)
            share = battery_dispatch / len(battery_idx)

            for idx in battery_idx:
                min_e_mwh = net.storage.at[idx, "min_soc_percent"] / 100.0 * net.storage.at[idx, "max_e_mwh"]
                current_e_mwh = net.storage.at[idx, "soc_percent"] / 100.0 * net.storage.at[idx, "max_e_mwh"]
                limit = net.storage.at[idx, "min_p_mw"]
                actual = min(share, -limit)

                # if the ideal p_mw rate will cause overcharging by the next cycle, 
                # then set the limit to power the battery only up to the max SOC percent
                if current_e_mwh - (actual * 0.25) < min_e_mwh:
                    actual = (current_e_mwh - min_e_mwh) / 0.25
                net.storage.at[idx, "p_mw"] = -actual
                remaining -= actual

        # allocate any power that remains from hydrogen
        if remaining > tolerance_mw:

            for idx in hydrogen_idx:

                limit = net.storage.at[idx, "min_p_mw"]
                actual = min(remaining, -limit)
                if net.storage.at[idx, "stored_e_mwh"] >= abs(actual * 0.25):
                    net.storage.at[idx, "p_mw"] = -actual
                    remaining -= actual

                if remaining <= tolerance_mw:
                    break



