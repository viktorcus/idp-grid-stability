"""
Filename: limits.py
Author: Victor Seglem
Date: 2026-04-13
Version: 1.0
Description: Contains a custom set of functions for testing a pandapower net's results against each components' defined limits.
"""

def bus_vm_pu_limits(net):
    try:
        err_found = False
        for i in range(len(net.bus)):
            bus = net.bus.iloc[i]
            res = net.res_bus.iloc[i]
            
            if res.vm_pu-bus.min_vm_pu < -0.0001: 
                print(f'Bus #{bus.name}: Result {round(res.vm_pu,4)} V p.u. is less than minimum of {bus.min_vm_pu} V p.u.')
                err_found = True
            elif res.vm_pu-bus.max_vm_pu > 0.0001:
                print(f'Bus #{bus.name}: Result {round(res.vm_pu,4)} V p.u. is greater than maximum of {bus.max_vm_pu} V p.u.')
                err_found = True
            
        if not err_found: print("All buses within limits")
    except AttributeError:
        print("Power flow has not yet been run - no results to analyze")

def line_loading_limits(net):
    try:
        err_found = False
        for i in range(len(net.line)):
            line = net.line.iloc[i]
            res = net.res_line.iloc[i]
            
            if res.loading_percent-line.max_loading_percent > 0.0001:
                print(f'Line #{line.name}: Result {round(res.loading_percent,4)}% loading is greater than maximum of {line.max_loading_percent}% loading')
                err_found = True
            
        if not err_found: print("All line loading within limits")
    except AttributeError:
        print("Power flow has not yet been run - no results to analyze")