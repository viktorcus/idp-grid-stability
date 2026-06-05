from pandapower.run import runopp, runpp 
import os, shutil    
from pathlib import Path
from pandapower.timeseries.run_time_series import OutputWriter
from .graphs import *
import math

YEAR = 2021   # year doesn't actually matter, but needed to calculate space between intervals

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
    ow.log_variable("storage", "stored_e_mwh")

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
            total_available = sum(
                abs(net.storage.at[idx, "max_p_mw"])
                for idx in hydrogen_idx
            )
            hydrogen_dispatch = min(remaining, total_available)
            share = hydrogen_dispatch / len(hydrogen_idx)

            for idx in hydrogen_idx:

                limit = net.storage.at[idx, "max_p_mw"]
                actual = min(share, limit)
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


def energy_analysis(net):
    """
    Analyzes all points in the grid for surplus and deficit data
    """
    totals = 0
    for i, row in net.controller.iterrows():
        ctrl = row.object
        if ctrl.element in ['load', 'storage']:
            totals -= ctrl.data_source.df.sum(axis=1)
        elif ctrl.element not in ['poly_cost', 'timestep']:
            totals += ctrl.data_source.df.sum(axis=1)

    peak_surplus_interval = totals.idxmax()
    peak_deficit_interval = totals.idxmin()

    start = pd.Timestamp(f"{YEAR}-01-01 00:00:00")

    peak_surplus_date = start + pd.Timedelta(minutes=15 * peak_surplus_interval)
    peak_deficit_date = start + pd.Timedelta(minutes=15 * peak_deficit_interval)

    return {
        "Peak Surplus": math.ceil(max(totals)), 
        "Peak Surplus Date": peak_surplus_date.strftime("%d/%m/%Y"),
        "Peak Deficit": math.ceil(min(totals)), 
        "Peak Deficit Date": peak_deficit_date.strftime("%d/%m/%Y"),
        "Total Surplus": math.ceil((totals.loc[lambda x : x > 0].sum() * .25).item()),
        "Total Deficit": math.ceil((totals.loc[lambda x : x < 0].sum() * .25).item()),
        "Full Surplus Date": peak_surplus_interval
    }

def average_day(net, span='month', split_weekends=False):
    """
    Get profiles of an average day in a month/quarter.
    If split_weekends is true, then we divide up profiles also according to whether they fall on a weekday or weekend.
    """
    avg_profiles = {}
    for i, row in net.controller.iterrows():
        ctrl = row.object
        excess_columns = ["datetime", "interval_of_day", span]     # to hold columns to be dropped again from the df after completion

        if ctrl.element != "timestep": 

            df = ctrl.data_source.df
            start = pd.Timestamp(f"{YEAR}-01-01 00:00:00")

            # extract date info based on the current time interval
            df["datetime"] = start + pd.to_timedelta(df.index * 15, unit="min")
            df["interval_of_day"] = (df["datetime"].dt.hour * 4
                + df["datetime"].dt.minute // 15
            )

            if split_weekends:  # determine if we also need grouping by weekday/weekend
                df["day_type"] = df["datetime"].dt.dayofweek.map(
                    lambda x: "Weekend" if x >= 5 else "Weekday"
                )
                excess_columns.append("day_type")

                if span == 'month':
                    df["month"] = df["datetime"].dt.month
                    monthly_profile = (   # group data by month and slice of day
                        df.groupby(["month", "interval_of_day", "day_type"])
                        .mean(numeric_only=True)
                        .reset_index()
                    )
                    avg_profiles[ctrl.element] = monthly_profile
                    df.drop(excess_columns, axis=1, inplace=True)
                elif span == 'quarter':
                    df["quarter"] = df["datetime"].dt.quarter
                    quarterly_profile = (   # group data by quarter and slice of day
                        df.groupby(["quarter", "interval_of_day", "day_type"])
                        .mean(numeric_only=True)
                        .reset_index()
                    )
                    avg_profiles[ctrl.element] = quarterly_profile
                    df.drop(excess_columns, axis=1, inplace=True)

            else:
                if span == 'month':
                    df["month"] = df["datetime"].dt.month
                    monthly_profile = (   # group data by month and slice of day
                        df.groupby(["month", "interval_of_day"])
                        .mean(numeric_only=True)
                        .reset_index()
                    )
                    avg_profiles[ctrl.element] = monthly_profile
                    df.drop(excess_columns, axis=1, inplace=True)
                elif span == 'quarter':
                    df["quarter"] = df["datetime"].dt.quarter
                    quarterly_profile = (   # group data by quarter and slice of day
                        df.groupby(["quarter", "interval_of_day"])
                        .mean(numeric_only=True)
                        .reset_index()
                    )
                    avg_profiles[ctrl.element] = quarterly_profile
                    df.drop(excess_columns, axis=1, inplace=True)

    return avg_profiles

def extract_monthly_profile(net, profiles: dict, month: int):
    """
    Given an object containing monthly profiles for each net element type and all months,
    Assign the controllers for just a single month
    """
    
    for i, row in net.controller.iterrows():
        ctrl = row.object
        if ctrl.element != "timestep":

            df = ctrl.data_source.df

            profile = profiles[ctrl.element][profiles[ctrl.element]["month"] == month]
            p = profile.drop(["month", "interval_of_day"], axis=1)
            p = p.reset_index(drop=True)
            net.controller.loc[i].object.data_source.df = p    

    return net
    