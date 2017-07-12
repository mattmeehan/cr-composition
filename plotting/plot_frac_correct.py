#!/usr/bin/env python

from __future__ import division, print_function
import os
import argparse
import numpy as np
import matplotlib.pyplot as plt

import comptools as comp
import comptools.analysis.plotting as plotting

color_dict = comp.analysis.get_color_dict()


if __name__ == '__main__':

    parser = argparse.ArgumentParser(
        description='Extracts and saves desired information from simulation/data .i3 files')
    parser.add_argument('-c', '--config', dest='config',
                   choices=comp.simfunctions.get_sim_configs(),
                   help='Detector configuration')
    parser.add_argument('-n', '--n_splits', dest='n_splits', type=int,
                   default=10,
                   help='Detector configuration')
    args = parser.parse_args()

    comp_class = True
    comp_key = 'MC_comp_class' if comp_class else 'MC_comp'
    comp_list = ['light', 'heavy'] if comp_class else ['P', 'He', 'O', 'Fe']

    pipeline_str = 'GBDT'
    pipeline = comp.get_pipeline(pipeline_str)

    energybins = comp.analysis.get_energybins()
    feature_list, feature_labels = comp.analysis.get_training_features()

    sim_train, sim_test = comp.load_dataframe(datatype='sim',
                                    config=args.config, comp_key=comp_key)

    frac_correct_folds = comp.analysis.get_CV_frac_correct(sim_train,
        feature_list, pipeline_str, comp_list, n_splits=args.n_splits)
    frac_correct_gen_err = {key: np.std(frac_correct_folds[key], axis=0) for key in frac_correct_folds}

    fig, ax = plt.subplots()
    for composition in comp_list:
    # for composition in comp_list + ['total']:
        performance_mean = np.mean(frac_correct_folds[composition], axis=0)
        performance_std = np.std(frac_correct_folds[composition], axis=0)
    #     err = np.sqrt(frac_correct_gen_err[composition]**2 + reco_frac_stat_err[composition]**2)
        plotting.plot_steps(energybins.log_energy_bins, performance_mean, yerr=performance_std,
                            ax=ax, color=color_dict[composition], label=composition)
    ax.set_xlabel('$\mathrm{\log_{10}(E_{reco}/GeV)}$')
    ax.set_ylabel('Classification accuracy')
    # ax.set_ylabel('Classification accuracy \n (statistical + 10-fold CV error)')
    ax.set_ylim([0.0, 1.0])
    ax.set_xlim(energybins.log_energy_min, energybins.log_energy_max)
    ax.grid()
    leg = plt.legend(loc='upper center', frameon=False,
              bbox_to_anchor=(0.5,  # horizontal
                              1.1),# vertical
              ncol=len(comp_list)+1, fancybox=False)
    # set the linewidth of each legend object
    for legobj in leg.legendHandles:
        legobj.set_linewidth(3.0)

    cv_str = 'Total accuracy:\n{:0.2f}\% (+/- {:0.1f}\%)'.format(np.nanmean(frac_correct_folds['total'])*100,
                                                          np.nanstd(frac_correct_folds['total'])*100)
    ax.text(7.4, 0.2, cv_str,
            ha="center", va="center", size=14,
            bbox=dict(boxstyle='round', fc="white", ec="gray", lw=0.8))
    outfile = os.path.join(comp.paths.figures_dir,
                'model_evaluation/frac-correct-{}.png'.format(args.config))
    comp.check_output_dir(outfile)
    plt.savefig(outfile)
