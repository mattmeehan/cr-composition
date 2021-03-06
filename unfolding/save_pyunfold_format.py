#!/usr/bin/env python

from __future__ import division, print_function
import os
import argparse
from collections import defaultdict
from itertools import product
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn.apionly as sns
from sklearn.metrics import confusion_matrix
from sklearn.model_selection import train_test_split
from ROOT import TH1F, TH2F, TFile
import dask.array as da
from dask.diagnostics import ProgressBar

from icecube.weighting.weighting import PDGCode
from icecube.weighting.fluxes import GaisserH3a, GaisserH4a, Hoerandel5

import comptools as comp


if 'cvmfs' in os.getenv('ROOTSYS'):
    raise comp.ComputingEnvironemtError('CVMFS ROOT cannot be used for unfolding')


if __name__ == '__main__':

    description = ('Save things needed for unfolding (e.g. response matrix, '
                   'priors, observed counts, etc.)')
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument('-c', '--config', dest='config', default='IC86.2012',
                        choices=comp.simfunctions.get_sim_configs(),
                        help='Detector configuration')
    parser.add_argument('--num_groups', dest='num_groups', type=int,
                        default=4, choices=[2, 3, 4],
                        help='Number of composition groups')
    parser.add_argument('--n_jobs', dest='n_jobs', type=int,
                        default=20,
                        help='Number of jobs to run in parallel')
    args = parser.parse_args()

    config = args.config
    num_groups = args.num_groups
    n_jobs = args.n_jobs

    comp_list = comp.get_comp_list(num_groups=num_groups)
    energybins = comp.get_energybins(config=config)
    log_energy_min = energybins.log_energy_min
    log_energy_max = energybins.log_energy_max

    # Load simulation training/testing DataFrames
    print('Loading simulation training/testing DataFrames...')
    df_sim_train, df_sim_test = comp.load_sim(config=config,
                                              energy_reco=False,
                                              # log_energy_min=energybins.log_energy_min,
                                              # log_energy_max=energybins.log_energy_max,
                                              log_energy_min=None,
                                              log_energy_max=None,
                                              test_size=0.5,
                                              verbose=True)

    feature_list, feature_labels = comp.get_training_features()

    # Energy reconstruction
    print('Loading energy regressor...')
    energy_pipeline = comp.load_trained_model('RF_energy_{}'.format(config))
    for df in [df_sim_train, df_sim_test]:
        df['reco_log_energy'] = energy_pipeline.predict(df[feature_list].values)
        df['reco_energy'] = 10**df['reco_log_energy']

    pipeline_str = 'BDT_comp_{}_{}-groups'.format(config, num_groups)
    # pipeline_str = 'xgboost_comp_{}_{}-groups'.format(config, num_groups)
    # pipeline_str = 'SVC_comp_{}_{}-groups'.format(config, num_groups)
    # pipeline_str = 'linecut_comp_{}_{}-groups'.format(config, num_groups)
    # pipeline_str = 'LinearSVC_comp_{}_{}-groups'.format(config, num_groups)
    # pipeline_str = 'LogisticRegression_comp_{}_{}-groups'.format(config, num_groups)

    print('Loading composition classifier...')
    pipeline = comp.load_trained_model(pipeline_str)

    # Load fitted effective area
    print('Loading detection efficiencies...')
    eff_path = os.path.join(
                    comp.paths.comp_data_dir, config, 'efficiencies',
                    'efficiency_fit_num_groups_{}.hdf'.format(num_groups))
    df_eff = pd.read_hdf(eff_path)
    # Format detection efficiencies for PyUnfold use
    efficiencies = np.empty(num_groups * len(energybins.energy_midpoints))
    efficiencies_err = np.empty(num_groups * len(energybins.energy_midpoints))
    for idx, composition in enumerate(comp_list):
        efficiencies[idx::num_groups] = df_eff['eff_median_{}'.format(composition)]
        efficiencies_err[idx::num_groups] = df_eff['eff_err_low_{}'.format(composition)]

    # Load data DataFrame
    print('Loading data DataFrame...')
    df_data = comp.load_data(config=config,
                             columns=feature_list,
                             energy_cut_key='reco_log_energy',
                             log_energy_min=log_energy_min,
                             log_energy_max=log_energy_max,
                             n_jobs=n_jobs,
                             verbose=True)

    X_data = comp.io.dataframe_to_array(df_data, feature_list + ['reco_log_energy'])
    log_energy_data = X_data[:, -1]
    X_data = X_data[:, :-1]

    print('Making composition predictions on data...')
    # Apply pipeline.predict method in chunks for parallel predicting
    X_da = da.from_array(X_data, chunks=(len(X_data) // 100, X_data.shape[1]))
    data_predictions = da.map_blocks(pipeline.predict, X_da,
                                     dtype=int, drop_axis=1)
    # Convert from target to composition labels
    data_labels = da.map_blocks(comp.decode_composition_groups, data_predictions,
                                dtype=str, num_groups=num_groups)
    with ProgressBar():
        data_labels = data_labels.compute(num_workers=n_jobs)

    # Get number of identified comp in each energy bin
    print('Formatting observed counts...')
    unfolding_df = pd.DataFrame()
    for composition in comp_list:
        comp_mask = data_labels == composition
        counts, _ = np.histogram(log_energy_data[comp_mask],
                                 bins=energybins.log_energy_bins)
        counts_err = np.sqrt(counts)
        unfolding_df['counts_' + composition] = counts
        unfolding_df['counts_' + composition + '_err'] = counts_err

    unfolding_df['counts_total'], _ = np.histogram(log_energy_data,
                                                   bins=energybins.log_energy_bins)
    unfolding_df['counts_total_err'] = np.sqrt(unfolding_df['counts_total'])
    unfolding_df.index.rename('log_energy_bin_idx', inplace=True)

    # Response matrix
    print('Making response matrix...')
    log_reco_energy_sim_test = df_sim_test['reco_log_energy'].values
    log_true_energy_sim_test = df_sim_test['MC_log_energy'].values
    pred_target = pipeline.predict(df_sim_test[feature_list].values)
    true_target = df_sim_test['comp_target_{}'.format(num_groups)].values
    res_normalized, res_normalized_err = comp.normalized_response_matrix(
                                            true_energy=log_true_energy_sim_test,
                                            reco_energy=log_reco_energy_sim_test,
                                            true_target=true_target,
                                            pred_target=pred_target,
                                            efficiencies=efficiencies,
                                            efficiencies_err=efficiencies_err,
                                            energy_bins=energybins.log_energy_bins)
    res_mat_outfile = os.path.join(comp.paths.comp_data_dir, config, 'unfolding',
                                  'response_{}-groups.txt'.format(num_groups))
    res_mat_err_outfile = os.path.join(comp.paths.comp_data_dir, config, 'unfolding',
                                       'response_err_{}-groups.txt'.format(num_groups))
    comp.check_output_dir(res_mat_outfile)
    comp.check_output_dir(res_mat_err_outfile)
    np.savetxt(res_mat_outfile, res_normalized)
    np.savetxt(res_mat_err_outfile, res_normalized_err)

    # Priors array
    print('Calcuating priors...')
    priors_list = ['H3a',
                   'H4a',
                   'simple_power_law',
                   'broken_power_law',
                   ]

    color_dict = comp.get_color_dict()
    for prior_name, marker in zip(priors_list, '.^*ox'):
        model_fluxes = comp.model_flux(model=prior_name,
                                       energy=energybins.energy_midpoints,
                                       num_groups=num_groups)
        for composition in comp_list:
            comp_flux = model_fluxes['flux_{}'.format(composition)].values
            prior_key = '{}_flux_{}'.format(prior_name, composition)
            unfolding_df[prior_key] = comp_flux

    print('Making PyUnfold formatted DataFrame...')
    num_cause_bins = num_groups * len(energybins.energy_midpoints)
    formatted_df = pd.DataFrame({'counts': np.empty(num_cause_bins),
                                 'counts_err': np.empty(num_cause_bins),
                                 'efficiencies': efficiencies,
                                 'efficiencies_err': efficiencies_err,
                                 })

    for idx, composition in enumerate(comp_list):
        formatted_df.loc[idx::num_groups, 'counts'] = unfolding_df['counts_{}'.format(composition)]
        formatted_df.loc[idx::num_groups, 'counts_err'] = np.sqrt(unfolding_df['counts_{}'.format(composition)])

    priors_formatted = {prior_name: np.empty(num_cause_bins) for prior_name in priors_list}
    for prior_name in priors_list:
        for idx, composition in enumerate(comp_list):
            comp_flux = unfolding_df['{}_flux_{}'.format(prior_name, composition)]
            priors_formatted[prior_name][idx::num_groups] = comp_flux

    for prior_name, prior_flux in priors_formatted.iteritems():
        formatted_df['{}_flux'.format(prior_name)] = prior_flux
        # Normalize prior flux in each energy bin to a probability
        formatted_df['{}_prior'.format(prior_name)] = prior_flux / prior_flux.sum()

    formatted_df.index.rename('log_energy_bin_idx', inplace=True)

    # Test that priors sum to 1 (can be used as probabilities)
    prior_cols = [col for col in formatted_df.columns if 'prior' in col]
    prior_sums = formatted_df[prior_cols].sum()
    np.testing.assert_allclose(prior_sums, np.ones_like(prior_sums))

    formatted_df_outfile = os.path.join(
                            comp.paths.comp_data_dir, config, 'unfolding',
                            'unfolding-df_{}-groups.hdf'.format(num_groups))
    comp.check_output_dir(formatted_df_outfile)
    formatted_df.to_hdf(formatted_df_outfile, 'dataframe',
                        format='table', mode='w')

    print('Saving PyUnfold input ROOT file...')
    comp.save_pyunfold_root_file(config, num_groups)
