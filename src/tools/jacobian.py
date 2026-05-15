"""
Filename: jacobian.py
Author: Victor Seglem
Date: 2026-05-13
Version: 1.0
Description: Contains a custom set of functions for cleaning up the extraction of jacobian matrix data from the power flow
Derived from the pandaspower tutorial at https://github.com/e2nIEE/pandapower/blob/develop/tutorials/internal_datastructure.ipynb. 
"""

import numpy as np
from sklearn.metrics import mean_squared_error

def pv_nodes(net):
    return net._ppc["internal"]["pv"]

def pq_nodes(net):
    return net._ppc["internal"]["pq"]

def jacobian_matrix(net):
    return net._ppc["internal"]["J"]

def voltage_sensitivity_matrix(net):
    """
        Takes the inverse of the Jacobian matrix, and extracts the voltage sensitivity submatrix from the Jacobian inverse
    """
    n_pvpq = len(pv_nodes(net)) + len(pq_nodes(net))
    j_inv = np.linalg.inv(jacobian_matrix(net).toarray())
    return j_inv[n_pvpq:, :n_pvpq]

def vs_mse(net):
    vs_flat = np.ndarray.flatten(voltage_sensitivity_matrix(net))
    zeroes = np.zeros(shape=vs_flat.shape)
    return mean_squared_error(vs_flat, zeroes)

