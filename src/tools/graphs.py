"""
Filename: graphs.py
Author: Victor Seglem
Date: 2026-05-17
Version: 1.0
Description: Contains a custom set of functions for graphing pandapower results
"""

import pandas as pd
import seaborn as sb
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from pathlib import Path
from pandapower.plotting.plotly import pf_res_plotly

def parse_timestep(date_str, timestep):
    # parse input date string
    day, month, year = map(int, date_str.split('/'))
    base_date = datetime(year, month, day)

    # calculate time offset
    time_offset = timedelta(minutes=timestep * 15)
    final_datetime = base_date + time_offset

    # format to yyyy-mm hh:mm
    return final_datetime.strftime("%m-%d %H-%M")

def line_loading(line_list, date, results_dir):
    lines = pd.read_csv(f'..\\results\\{results_dir}\\res_line\\loading_percent.csv')
    err_lines = lines[[str(x) for x in line_list]]
    ax = sb.lineplot(data=err_lines)
    ax.set(xlabel=f'time step ({date})', ylabel='loading percent', title='Line Loading Exceeding Limits')
    plt.show()
    ax.figure.savefig(f'..\\results\\{results_dir}\\res_line\\loading_percent.png')

def bus_vpu(bus_list, date, results_dir):
    lines = pd.read_csv(f'..\\results\\{results_dir}\\res_bus\\vm_pu.csv')
    err_lines = lines[[str(x) for x in bus_list]]
    ax = sb.lineplot(data=err_lines)
    ax.set(xlabel=f'time step ({date})', ylabel='V (p.u.)', title='Bus Voltages Exceeding Limits')
    ax.hlines(y = [0.95, 1.05], 
        xmin=0, xmax=96, linestyles=["dashed", "dashed"], colors=["gray", "gray"])  
    plt.show()
    ax.figure.savefig(f'..\\results\\{results_dir}\\res_bus\\vm_pu.png')

def graph_p_mw(date, net_element, results_dir):
    results = pd.read_csv(f'..\\results\\{results_dir}\\res_{net_element}\\p_mw.csv')
    results.drop(results.columns[0], axis=1, inplace=True)  # discard timestep column
    ax = sb.lineplot(data=results)
    ax.set(xlabel=f'time step ({date})', ylabel='power [MW]', title=f'Power Flow ({net_element})')
    plt.show()
    ax.figure.savefig(f'..\\results\\{results_dir}\\res_{net_element}\\p_mw.png')

def graph_battery_soc(net, date, results_dir):
    results = pd.read_csv(f'..\\results\\{results_dir}\\storage\\soc_percent.csv')
    battery_idx = net.storage[net.storage["name"] == "battery"].index.values
    results.drop(results.columns[0], axis=1, inplace=True)  # discard timestep column
    for col in reversed(results.columns):
        if int(col) not in battery_idx: results.drop(results.columns[int(col)], axis=1, inplace=True)
    ax = sb.lineplot(data=results)
    ax.set(xlabel=f'time step ({date})', ylabel='SOC', title='Battery SOC Percent')
    plt.show()
    ax.figure.savefig(f'..\\results\\{results_dir}\\storage\\soc_percent.png')

def graph_hydrogen_storage(net, date, results_dir):
    results = pd.read_csv(f'..\\results\\{results_dir}\\storage\\stored_e_mwh.csv')
    battery_idx = net.storage[net.storage["name"] == "hydrogen"].index.values
    results.drop(results.columns[0], axis=1, inplace=True)  # discard timestep column
    for col in reversed(results.columns):
        if int(col) not in battery_idx: results.drop(results.columns[int(col)], axis=1, inplace=True)
    ax = sb.lineplot(data=results)
    ax.set(xlabel=f'time step ({date})', ylabel='Energy (MWh)', title='Hydrogen Stored')
    plt.show()
    ax.figure.savefig(f'..\\results\\{results_dir}\\storage\\stored_e_mwh.png')

def plot_powerflow_result(net, date, timestep, results_dir):
    Path(f'..\\results\\{results_dir}\\pf').mkdir(parents=True, exist_ok=True)
    filename = f'..\\results\\{results_dir}\\pf\\pf_graph_{parse_timestep(date, timestep)}.html'
    pf_res_plotly(net, filename=filename, auto_open=False)