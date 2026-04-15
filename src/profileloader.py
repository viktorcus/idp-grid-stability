import pandas as pd
from pandapower.control import ConstControl
from pandapower.timeseries.data_sources.frame_data import DFData


def datasource_loads(net):
    """
        Handles differences between the number of load profiles given and the number of loads in a net.
        Splits the power from the load profiles as equally as across the available loads.
    """
    load_profile = pd.read_csv('../data/load_profiles/csv/load_profiles_joined.csv')
    num_profiles = len(load_profile.columns) - 1
    num_loads = len(net.load)


    # insufficient load profiles
    if num_loads < num_profiles:
        raise IndexError(f'Load profiles ({num_profiles}) exceed number of loads in net ({num_loads})')
    
    # number of loads in the net is a multiple of the number of load profiles:
    # loads can all be split the same number of ways
    elif num_loads % num_profiles == 0:
        allocations = num_loads / num_profiles

        for i in range(1, num_profiles):
            pd.to_numeric(load_profile.iloc[:,i])
            load_profile.iloc[:,i] = load_profile.iloc[:,i] / allocations

            for p in range(allocations):
                load_profile[f'{load_profile.columns.values[i]} {p+2}'] = load_profile.iloc[:,i]

    # number of loads in the net is not a multiple of the number of load profiles:
    # a modules m number of load profiles will be divided by a factor of the whole number n + 1, the rest are divided by a factor of n
    else:
        for i in range(1, (num_loads % num_profiles) + 1):
            allocations = num_loads // num_profiles
            pd.to_numeric(load_profile.iloc[:,i])
            load_profile.iloc[:,i] = (load_profile.iloc[:,i] / float(allocations))

            for p in range(allocations):
                load_profile[f'{load_profile.columns.values[i]} {p+2}'] = load_profile.iloc[:,i]

        for i in range((num_loads % num_profiles) + 1, num_profiles + 1):
            allocations = num_loads // num_profiles -1
            pd.to_numeric(load_profile.iloc[:,i])
            load_profile.iloc[:,i] = load_profile.iloc[:,i] / allocations

            for p in range(allocations):
                load_profile[f'{load_profile.columns.values[i]} {p+2}'] = load_profile.iloc[:,i]

    print(load_profile.head())
    

