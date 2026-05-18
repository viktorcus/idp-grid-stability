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

def line_loading(line_list, date):
    lines = pd.read_csv('..\\results\\collapse\\res_line\\loading_percent.csv')
    err_lines = lines[[str(x) for x in line_list]]
    ax = sb.lineplot(data=err_lines)
    ax.set(xlabel=f'time step ({date})', ylabel='loading percent')
    plt.show()
    ax.figure.savefig('..\\results\\collapse\\res_line\\loading_percent.png')

def bus_vpu(bus_list, date):
    lines = pd.read_csv('..\\results\\collapse\\res_bus\\vm_pu.csv')
    err_lines = lines[[str(x) for x in bus_list]]
    ax = sb.lineplot(data=err_lines)
    ax.set(xlabel=f'time step ({date})', ylabel='V (p.u.)')
    ax.hlines(y = [0.95, 1.05], 
        xmin=0, xmax=96, linestyles=["dashed", "dashed"], colors=["gray", "gray"])  
    plt.show()
    ax.figure.savefig('..\\results\\collapse\\res_bus\\vm_pu.png')