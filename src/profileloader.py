import pandas as pd
from pandapower.control import ConstControl
from pandapower.timeseries.data_sources.frame_data import DFData
from pandapower.toolbox import drop_out_of_service_elements
from typing import Literal
import json
import numpy as np
import datetime as dt
from pandapower.create import create_storage

_NET_ELEMENT = Literal["load", "pv", "hydro", "poly_cost"]

def net_element(net, net_element_: _NET_ELEMENT):
    """
        Returns relevant dataframe from net.
        Helper to make json_to_net broadly reusable across net element types.
    """
    match net_element_:
        case "load": 
            return net.load
        case "gen":
            return net.gen
        case "pv":
            return net.gen
        case "hydro":
            return net.storage
        case "poly_cost":
            return net.poly_cost
        

def json_to_net_generic(net, net_element_: _NET_ELEMENT = "load", limit: int = None, date = None):
    """
        Reads a JSON file that describes assignments of a set of load/gen profiles to a set of loads/gens in a net. 
        Each element may be a collection of one or more of these profiles, which each may be counted multiple 
        times (e.g., one load may contain one school and twenty houses). 
    """
    profiles_path = f'../data/{net_element_}_profiles/csv/{net_element_}_profiles_joined.csv'
    json_path = f'../data/{net_element_}_profiles/{net_element_}_allocations.json'
    profile_df = pd.read_csv(profiles_path)

    with open(json_path) as f:
        data = json.load(f)
        loading_df = pd.DataFrame(0, index=np.arange(len(profile_df)), 
                                  columns=np.arange(len(net_element(net, net_element_))))
            
        for idx in range(len(data["data"])):
            d = data["data"][idx]

            # add each profile for that node with scaling
            for profile_name, profile_count in d["profiles"].items():
                loading_df[idx] += profile_df[profile_name] * profile_count

            # update load/gen at index with correct bus number
            if "bus_index" in d:
                net_element(net, net_element_).at[idx, "bus"] = d["bus_index"] - 1

            # once all profiles are added to a node, convert from kw to mw if needed
            if "units" in data and data["units"] == "kw":
                loading_df[idx] *= 0.001

        # because tariff data is provided in hourly intervals, pad out rows to create 15-minute intervals like other data 
        if net_element_ == "poly_cost":
            loading_df = pd.DataFrame(np.repeat(loading_df.values, repeats=4, axis=0), columns=loading_df.columns)
            net.poly_cost = net.poly_cost.query("et == 'ext_grid'")
            net.poly_cost.at[0, "cp2_eur_per_mw2"] = 0

        # non-tariff types may need service switched on or off depending on data provided
        elif len(data["data"]) < len(net_element(net, net_element_)) and net_element_ != "poly_cost":
            for i in range(len(net_element(net, net_element_)), len(data["data"]), -1):
                net_element(net, net_element_).loc[i-1, "in_service"] = False
                
    drop_out_of_service_elements(net)
    net_element(net, net_element_).reset_index(drop=True, inplace=True)
    net_element(net, net_element_).index = list(net_element(net, net_element_).index)

    if limit is not None:       # restrict output to a specific number of time intervals
        loading_df = loading_df[0:limit]
        loading_df = loading_df.reset_index(drop=True)
        loading_df.index = list(loading_df.index)
        ds = DFData(loading_df)
    elif date is not None:      # restrict output to values from a specific date
        datenum = dt.datetime.strptime(date,"%d/%m/%Y").timetuple().tm_yday     # row position in df corresponding to date
        startidx = (datenum-1) * 24 * 4
        loading_df = loading_df[startidx:startidx + 24 * 4]
        loading_df = loading_df.reset_index(drop=True)
        loading_df.index = list(loading_df.index)
        ds = DFData(loading_df)
    else:
        ds = DFData(loading_df)

    return ConstControl(net, element=net_element_, variable='p_mw' if net_element_ != 'poly_cost' else 'cp1_eur_per_mw', 
                        data_source=ds, element_index=net_element(net, net_element_).index, 
                        profile_name=net_element(net, net_element_).index)


def json_to_net_hydro(net, limit: int = None, date = None):
    """
        Reads a JSON file that describes assignments of a set of load/gen profiles to a set of loads/gens in a net. 
        Each element may be a collection of one or more of these profiles, which each may be counted multiple 
        times (e.g., one load may contain one school and twenty houses). 
    """
    
    profiles_path = '../data/gen_profiles/csv/gen_profiles_joined.csv'
    json_path = '../data/gen_profiles/gen_allocations.json'

    profile_df = pd.read_csv(profiles_path)

    with open(json_path) as f:
        data = json.load(f)
        loading_df = pd.DataFrame(0, index=np.arange(len(profile_df)), 
                                  columns=np.arange(len(net.storage)))
            
        for idx in range(len(data["data"])):
            d = data["data"][idx]

            # add each profile for that node with scaling
            for profile_name, scaling in d["profiles"].items():
                if profile_name.lower() == "hydro":
                    hydro_idx = create_storage(net, 
                            p_mw = profile_df[profile_name][0] * scaling,
                            max_e_mwh=scaling, sn_mva=0, soc_percent=50,
                            bus=d["bus_index"] - 1, name="hydro")
                    net.poly_cost.loc[len(net.poly_cost.index)] = [
                        hydro_idx.item(),    # element
                        "hydro",    # et
                        20000,      # fixed: 20,000 EUR/year
                        0,          # cp1_eur_per_mw
                        0,          # cp2_eur_per_mw2
                        0,          # cq0_eur
                        0,          # cq1_eur_per_mvar
                        0           # cq2_eur_per_mvar2
                    ]

                    if len(loading_df.columns) > idx:
                        loading_df[idx] += profile_df[profile_name] * scaling * -1
                    else:
                        loading_df[len(loading_df.columns)] = profile_df[profile_name] * scaling * -1

            # once all profiles are added to a node, convert from kw to mw if needed
            if "units" in data and data["units"] == "kw":
                loading_df[idx] *= 0.001


    net.storage = net.storage.reset_index(drop=True)
    net.storage.index = list(net.storage.index)

    if limit is not None:       # restrict output to a specific number of time intervals
        loading_df = loading_df[0:limit]
        loading_df = loading_df.reset_index(drop=True)
        loading_df.index = list(loading_df.index)
        ds = DFData(loading_df)      
    elif date is not None:      # restrict output to values from a specific date
        datenum = dt.datetime.strptime(date,"%d/%m/%Y").timetuple().tm_yday     # row position in df corresponding to date
        startidx = (datenum-1) * 24 * 4
        loading_df = loading_df[startidx:startidx + 24 * 4]
        loading_df = loading_df.reset_index(drop=True)
        loading_df.index = list(loading_df.index)
        ds = DFData(loading_df)
    else:
        ds = DFData(loading_df)

    return ConstControl(net, element="storage", variable='p_mw', data_source=ds, 
                        element_index=net.storage.index, profile_name=net.storage.index)


def json_to_net_pv(net, limit: int = None, date = None):
    """
        Reads a JSON file that describes assignments of a set of load/gen profiles to a set of loads/gens in a net. 
        Each element may be a collection of one or more of these profiles, which each may be counted multiple 
        times (e.g., one load may contain one school and twenty houses). 
    """
    profiles_path = '../data/gen_profiles/csv/gen_profiles_joined.csv'
    json_path = '../data/gen_profiles/gen_allocations.json'

    profile_df = pd.read_csv(profiles_path)

    with open(json_path) as f:
        data = json.load(f)
        loading_df = pd.DataFrame(0, index=np.arange(len(profile_df)), 
                                  columns=np.arange(len(net.gen)))
            
        for idx in range(len(data["data"])):
            d = data["data"][idx]

            # add each profile for that node with scaling
            for profile_name, scaling in d["profiles"].items():
                if profile_name.lower() == "pv":
                    loading_df[idx] += profile_df[profile_name] * scaling
                    net.poly_cost.loc[len(net.poly_cost.index)] = [
                        idx,    # element
                        "pv",   # et
                        # EUR/kWp * kwp OR EUR/kWp * MWp * 1000 kW/MW
                        scaling * 550  * 
                            (1000 if "units" in data and data["units"].lower() == "mw" else 1),  # cp0_eur (EUR/kWp * kwp OR EUR/kWp * MWp * 1000 kW/MW)
                        0,      # cp1_eur_per_mw
                        0,      # cp2_eur_per_mw2
                        0,      # cq0_eur
                        0,      # cq1_eur_per_mvar
                        0       # cq2_eur_per_mvar2
                    ]
                elif "pv" not in d["profiles"].items():
                    net.gen.loc[idx, "in_service"] = False

            # update load/gen at index with correct bus number
            if "bus_index" in d:
                net.gen.at[idx, "bus"] = d["bus_index"] - 1
                net.gen.at[idx, "name"] = "pv"

            # once all profiles are added to a node, convert from kw to mw if needed
            if "units" in data and data["units"] == "kw":
                loading_df[idx] *= 0.001

        # non-tariff types may need service switched on or off depending on data provided
        if len(data["data"]) < len(net.gen):
            for i in range(len(net.gen), len(data["data"]), -1):
                net.gen.loc[i-1, "in_service"] = False

    drop_out_of_service_elements(net)
    net.gen = net.gen.reset_index(drop=True)
    net.gen.index = list(net.gen.index)

    if limit is not None:       # restrict output to a specific number of time intervals
        ds = DFData(loading_df[0:limit])      
    elif date is not None:      # restrict output to values from a specific date
        datenum = dt.datetime.strptime(date,"%d/%m/%Y").timetuple().tm_yday     # row position in df corresponding to date
        startidx = (datenum-1) * 24 * 4
        loading_df = loading_df[startidx:startidx + 24 * 4]
        loading_df = loading_df.reset_index(drop=True)
        loading_df.index = list(loading_df.index)
        ds = DFData(loading_df)
    else:
        ds = DFData(loading_df)

    return ConstControl(net, element='gen', variable='p_mw', data_source=ds, 
                        element_index=net.gen.index, profile_name=net.gen.index)