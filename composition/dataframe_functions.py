
from __future__ import print_function, division
import numpy as np
import pandas as pd
from functools import wraps

from .paths import Paths


# def validate_dataframe(f):
#     @wraps(f)
#     def wrapper(*args, **kwds):
#         print 'Calling decorated function'
#         return f(*args, **kwds)
#     return wrapper

def validate_dataframe(df):
    if not isinstance(df, pd.DataFrame):
        raise TypeError('Expecting a DataFrame, but got {}'.format(type(df)))


def validate_datatype(datatype):
    assert datatype in ['sim', 'data'], 'datatype must be either \'sim\' or \'data\''


def apply_quality_cuts(df, datatype='sim', return_cut_dict=False,
                       dataprocessing=False, verbose=True):
    validate_dataframe(df)
    validate_datatype(datatype)
    # Quality Cuts #
    # Adapted from PHYSICAL REVIEW D 88, 042004 (2013)
    cut_dict = {}
    # MC-level cuts
    if datatype == 'sim':
        cut_dict['MC_IT_containment'] = (
            df['IceTop_FractionContainment'] < 1.0)
        cut_dict['MC_InIce_containment'] = (
            df['InIce_FractionContainment'] < 1.0)
        df['MC_log_energy'] = np.nan_to_num(np.log10(df['MC_energy']))
    # IT specific cuts
    cut_dict['IceTopQualityCuts'] = df['IceTopQualityCuts'].astype(bool)
    cut_dict['lap_fitstatus_ok'] = df['lap_fitstatus_ok']
    cut_dict['lap_IT_containment'] = df[
        'Laputop_IceTop_FractionContainment'] < 0.96
    cut_dict['lap_beta'] = (df['lap_beta'] < 9.5) & (df['lap_beta'] > 1.4)
    cut_dict['lap_rlogl'] = df['lap_rlogl'] < 2
    cut_dict['IceTopMaxSignalInEdge'] = np.logical_not(
        df['IceTopMaxSignalInEdge'].astype(bool))
    cut_dict['IceTopMaxSignal'] = (df['IceTopMaxSignal'] >= 6)
    cut_dict['IceTopNeighbourMaxSignal'] = df['IceTopNeighbourMaxSignal'] >= 4
    cut_dict['NStations'] = df['NStations'] >= 5
    cut_dict['StationDensity'] = df['StationDensity'] >= 0.2
    cut_dict['min_energy_lap'] = df['lap_energy'] > 10**6.3
    cut_dict['max_energy_lap'] = df['lap_energy'] < 10**8.0
    # cut_dict['llhratio'] = np.logical_not(np.isnan(df['llhratio'].values))

    # InIce specific cuts
    cut_dict['InIceQualityCuts'] = df['InIceQualityCuts'].astype(bool)
    for cut in ['MilliNCascAbove2', 'MilliQtotRatio', 'MilliRloglBelow2', 'NCh_CoincLaputopCleanedPulsesAbove7', 'StochRecoSucceeded']:
        cut_dict['InIceQualityCuts_{}'.format(cut)] = df['InIceQualityCuts_{}'.format(cut)].astype(bool)
    for i in ['1_60']:
    # for i in ['1_60', '1_45', '1_30', '1_15', '1_6', '45_60']:
        cut_dict['NChannels_' + i] = df['NChannels_' + i] >= 8
        cut_dict['max_qfrac_' + i] = df['max_qfrac_' + i] < 0.3
    cut_dict['lap_InIce_containment'] = df['Laputop_InIce_FractionContainment'] < 1.0

    # # Millipede specific cuts
    # cut_dict['mil_rlogl'] = df['mil_rlogl'] < 2.0
    # cut_dict['mil_qtot_ratio'] = df['mil_qtot_predicted']/df['mil_qtot_measured'] > -0.03
    # cut_dict['num_millipede_cascades'] = df['num_millipede_cascades'] >= 3

    # Some conbined cuts
    cut_dict['lap_reco_success'] = cut_dict[
        'lap_fitstatus_ok'] & cut_dict['lap_beta'] & cut_dict['lap_rlogl']
    # cut_dict['num_hits_1_60'] = cut_dict['NChannels_1_60'] & cut_dict['NStations']
    for i in ['1_60']:
    # for i in ['1_60', '1_45', '1_30', '1_15', '1_6', '45_60']:
        cut_dict['num_hits_'+i] = cut_dict['NChannels_'+i] & cut_dict['NStations']
    cut_dict['lap_containment'] = cut_dict[
        'lap_IT_containment'] & cut_dict['lap_InIce_containment']
    cut_dict['IT_signal'] = cut_dict['IceTopMaxSignalInEdge'] & cut_dict[
        'IceTopMaxSignal'] & cut_dict['IceTopNeighbourMaxSignal']
    cut_dict['reco_energy_range'] = cut_dict['min_energy_lap'] & cut_dict['max_energy_lap']
    # cut_dict['mil_reco_success'] = cut_dict['mil_rlogl'] & cut_dict[
    #     'mil_qtot_ratio'] & cut_dict['num_millipede_cascades']

    if return_cut_dict:
        return df, cut_dict
    else:
        selection_mask = np.array([True] * len(df))
        if dataprocessing:
            # standard_cut_keys = ['IceTopQualityCuts', 'lap_InIce_containment',
            #     'reco_energy_range', 'num_hits_1_60', 'max_qfrac_1_60']
            standard_cut_keys = ['IceTopQualityCuts', 'lap_InIce_containment']
        else:
            # standard_cut_keys = ['IceTopQualityCuts', 'lap_InIce_containment',
            #     'reco_energy_range', 'num_hits_1_30', 'max_qfrac_1_30',
            #     'InIceQualityCuts']
            standard_cut_keys = ['IceTopQualityCuts', 'lap_InIce_containment',
                'InIceQualityCuts', 'num_hits_1_60']
            # standard_cut_keys = ['IceTopQualityCuts', 'lap_InIce_containment',
            #     'reco_energy_range', 'num_hits_1_30', 'max_qfrac_1_30']
        for key in standard_cut_keys:
            selection_mask *= cut_dict[key]
        # Print cut event flow
        if verbose:
            n_total = len(df)
            cut_eff = {}
            cumulative_cut_mask = np.array([True] * n_total)
            print('{} quality cut event flow:'.format(datatype))
            for key in standard_cut_keys:
                cumulative_cut_mask *= cut_dict[key]
                print('{:>30}:  {:>5.3}  {:>5.3}'.format(key, np.sum(
                    cut_dict[key]) / n_total, np.sum(cumulative_cut_mask) / n_total))
            print('\n')

        df_cut = df[selection_mask]

        return df_cut


def add_convenience_variables(df):
    validate_dataframe(df)

    # Add log-scale columns to df
    df['lap_log_energy'] = np.nan_to_num(np.log10(df['lap_energy']))
    # df['InIce_log_charge_1_60'] = np.nan_to_num(np.log10(df['InIce_charge_1_60']))
    for i in ['1_60']:
    # for i in ['1_60', '1_45', '1_30', '1_15', '1_6', '45_60']:
        # df['InIce_log_charge_'+i] = np.nan_to_num(np.log10(df['InIce_charge_'+i]))
        df['InIce_log_charge_'+i] = np.log10(df['InIce_charge_'+i])
        df['log_NChannels_'+i] = np.log10(df['NChannels_'+i])
        df['log_NHits_'+i] = np.log10(df['NHits_'+i])
    df['lap_cos_zenith'] = np.cos(df['lap_zenith'])
    for dist in ['50', '80', '125', '180', '250', '500']:
        df['log_s'+dist] = np.log10(df['lap_s'+dist])
    df['log_dEdX'] = np.log10(df['eloss_1500_standard'])

    # Add ratio of features (could help improve RF classification)
    # df['charge_nchannels_ratio'] = df['InIce_charge_1_30'] / df['NChannels_1_30']
    # df['charge_nhits_ratio'] = df['InIce_charge_1_30'] / df['NHits_1_30']
    # df['nhits_nchannels_ratio'] =  df['NHits_1_30'] / df['NChannels_1_30']
    # df['stationdensity_charge_ratio'] = df[
    #     'StationDensity'] / df['InIce_charge_1_30']
    # df['stationdensity_nchannels_ratio'] = df[
    #     'StationDensity'] / df['NChannels_1_30']
    # df['stationdensity_nhits_ratio'] = df['StationDensity'] / df['NHits_1_30']

    return df


def load_dataframe(datatype='sim', config='IC79', return_cut_dict=False):
    '''Loads pandas DataFrame object with appropreiate information
    '''
    validate_datatype(datatype)
    # Load simulation dataframe
    mypaths = Paths()
    df_file = '{}/{}_{}/{}_dataframe.hdf5'.format(mypaths.comp_data_dir,
                                                  config, datatype, datatype)
    # df = pd.read_hdf(df_file)
    with pd.HDFStore(df_file) as store:
        df = store['dataframe']

    if return_cut_dict:
        df, cut_dict = apply_quality_cuts(df, datatype, return_cut_dict)
        df = add_convenience_variables(df)
        return df, cut_dict
    else:
        df = apply_quality_cuts(df, datatype, return_cut_dict)
        df = add_convenience_variables(df)
        return df