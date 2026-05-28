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


def csv_to_net(net, net_element_ : _NET_ELEMENT = "load"):
    """
        Provided a set of CSVs representing a timeseries of load data, parses these and allocates them evenly 
        across a net with a variable number of loads.
        Makes the assumption that only one instance of each load profile is being processed in the network, and 
        that there is no preference to which node the load profile belongs to.
    """
    profile_df = pd.read_csv(f'../data/{net_element_}_profiles/csv/{net_element_}_profiles_joined.csv')
    num_profiles = len(profile_df.columns) - 1
    num_spaces = len(net_element(net, net_element_))


    # insufficient load profiles
    if num_spaces < num_profiles:
        raise IndexError(f'{net_element_} profiles ({num_profiles}) exceed number of spaces available in net ({num_spaces})')
    
    # number of loads in the net is a multiple of the number of load profiles:
    # loads can all be split the same number of ways
    elif num_spaces % num_profiles == 0:
        allocations = num_spaces / num_profiles

        for i in range(1, num_profiles):
            pd.to_numeric(profile_df.iloc[:,i])
            profile_df.iloc[:,i] = profile_df.iloc[:,i] / allocations

            for p in range(allocations):
                profile_df[f'{profile_df.columns.values[i]} {p+2}'] = profile_df.iloc[:,i]

    # number of loads in the net is not a multiple of the number of load profiles:
    # a modules m number of load profiles will be divided by a factor of the whole number n + 1, the rest are divided by a factor of n
    else:
        for i in range(1, (num_spaces % num_profiles) + 1):
            allocations = num_spaces // num_profiles
            pd.to_numeric(profile_df.iloc[:,i])
            profile_df.iloc[:,i] = (profile_df.iloc[:,i] / float(allocations))

            for p in range(allocations):
                profile_df[f'{profile_df.columns.values[i]} {p+2}'] = profile_df.iloc[:,i]

        for i in range((num_spaces % num_profiles) + 1, num_profiles + 1):
            allocations = num_spaces // num_profiles -1
            pd.to_numeric(profile_df.iloc[:,i])
            profile_df.iloc[:,i] = profile_df.iloc[:,i] / allocations

            for p in range(allocations):
                profile_df[f'{profile_df.columns.values[i]} {p+2}'] = profile_df.iloc[:,i]

    ds = DFData(profile_df.iloc[:,1:])
    return ConstControl(net, element=net_element_, variable='p_mw' if net_element_ != 'poly_cost' else 'cp1_eur_per_mw', 
                        data_source=ds, element_index=net_element(net, net_element_).index, 
                        profile_name=net_element(net, net_element_).index)


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
            for profile_name, profile_count in d["profiles"].items():
                if profile_name.lower() == "hydro":
                    create_storage(net, 
                            p_mw = profile_df[profile_name][0] * profile_count,
                            max_e_mwh=profile_count, sn_mva=0, soc_percent=50,
                            bus=d["bus_index"] - 1)
                    if len(loading_df.columns) > idx:
                        loading_df[idx] += profile_df[profile_name] * profile_count
                    else:
                        loading_df[len(loading_df.columns)] = profile_df[profile_name] * profile_count

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
            for profile_name, profile_count in d["profiles"].items():
                if profile_name.lower() == "pv":
                    loading_df[idx] += profile_df[profile_name] * profile_count
                elif "pv" not in d["profiles"].items():
                    net.gen.loc[idx, "in_service"] = False

            # update load/gen at index with correct bus number
            if "bus_index" in d:
                net.gen.at[idx, "bus"] = d["bus_index"] - 1

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