# This file is part of BurnMan - a thermoelastic and thermodynamic toolkit for the Earth and Planetary Sciences
# Copyright (C) 2012 - 2017 by the BurnMan team, released under the GNU
# GPL v2 or later.


# This is a standalone program that converts a tabulated version of the
# Stixrude and Lithgow-Bertelloni data format into the standard burnman
# format (printed to stdout)


import sys
import os.path

if os.path.isfile('stx11ver.dat') == False:
    print('This code requires the data file stx11ver.dat.')
    print(
        'This file is bundled with the Perple_X data files, which can be found here:')
    print('http://www.perplex.ethz.ch/perplex/ibm_and_mac_archives/')
    print('')
    print('Please download the file and place it in this directory.')
    exit()


def read_dataset(datafile):
    f = open(datafile, 'r')
    ds = []
    for line in f:
        ds.append(line.split())
    return ds


def read_dataset_utf8(datafile):
    f = open(datafile, 'r')
    ds = []
    for line in f:
        ds.append(line.decode('utf-8').split())
    return ds


def process_stixrude():

    perplex_ds = read_dataset('stx11ver.dat')
    alias_mapping = read_dataset('perplex_slb_2011_names.txt')

    alias = {}
    accurate_values = {}
    configurational_entropies = {}
    for line in alias_mapping:
        alias[line[0]] = line[2]

    process = 0  # flag to process data or not (to cut out first lines)
    n = 0  # line number for each record
    for line in perplex_ds:
        if len(line) != 0:
            if process == 1:
                if line[0] == 'end':
                    n = 0
                else:
                    n = n + 1
                if n == 1:
                    name = alias[line[0]]
                    data = []
                    configurational_entropy = 'None'
                elif n == 3:
                    # F0, (n, ignored), -V0
                    data.extend([float(line[2]), -1.0 * float(line[8])])
                elif n == 4:
                    # K_0, K_prime, Debye_0, grueneisen_0, q_0, eta_s0,
                    # [configurational_and_magnetic_entropy]
                    data.extend(
                        [float(line[2]), float(line[5]), float(line[8]),
                         float(line[11]), float(line[14]), float(line[17])])
                    if len(line) == 21:
                        configurational_entropy = float(line[20])
                elif n == 5:
                    # mu_S0, mu_S0_prime
                    data.extend([float(line[2]), float(line[5])])
                    # Sort into correct order for processing: F, V, K, K',
                    #                        Debye, gruen, q, G, Gprime, etaS0
                    accurate_values[
                        name] = [data[0] / 1.e3, data[1] * 10., data[2] / 1.e4, data[3],
                                 data[4], data[5], data[6], data[8] / 1.e4, data[9], data[7]]
                    configurational_entropies[name] = configurational_entropy

            if line[0] == 'end_components':
                process = 1

    return accurate_values, configurational_entropies


accurate_values, configurational_entropies = process_stixrude()


ds = read_dataset_utf8('slb_2011.txt')
landau = read_dataset_utf8('slb_2011_landau.txt')
landau_params = {}
for line in landau:
    phase = str(line[0]).lower()
    if phase != '#':
        landau_params[phase] = [
            float(line[1]), float(line[2]) * 1.e-6, float(line[3])]

print '# This file is part of BurnMan - a thermoelastic and thermodynamic toolkit for the Earth and Planetary Sciences'
print '# Copyright (C) 2012 - 2017 by the BurnMan team, released under the GNU GPL v2 or later.'
print ''
print ''
print '"""'
print 'SLB_2011'
print 'Minerals from Stixrude & Lithgow-Bertelloni 2011 and references therein'
print 'File autogenerated using SLBdata_to_burnman.py'
print '"""'
print ''
print 'from __future__ import absolute_import'
print ''
print 'from ..mineral import Mineral'
print 'from ..solution import Solution'
print 'from ..solutionmodel import *'
print 'from ..tools.chemistry import dictionarize_formula, formula_mass'
print ''

param_scales = [-1., -1.,  # not numbers, so we won't scale
                1.e3, 1.e3,  # KJ -> J
                1.e-6, 1.e-6,  # cm^3/mol -> m^3/mol
                1.e9, 1.e9,  # GPa -> Pa
                1.0, 1.0,  # no scale for K'
                1.0, 1.0,  # no scale for Debye
                1.0, 1.0,  # no scale for gruneisen
                1.0, 1.0,  # no scale for q
                1.e9, 1.e9,  # GPa -> Pa
                1.0, 1.0,  # no scale for G'
                1.0, 1.0]  # no scale for eta_s


solutionfile = 'slb_2011_solutions.txt'
with open(solutionfile, 'r') as fin:
    print fin.read()
fin.close()

print '"""'
print 'ENDMEMBERS'
print '"""'
print ''
formula = '0'
for idx, m in enumerate(ds):
    if idx == 0:
        param_names = m
    else:
        print 'class', m[0].lower(), '(Mineral):'
        print '    def __init__(self):'
        print ''.join(['        formula=\'', m[1], '\''])
        print '        formula = dictionarize_formula(formula)'
        print '        self.params = {'
        print ''.join(['            \'name\': \'', m[0], '\','])
        print '            \'formula\': formula,'
        print '            \'equation_of_state\': \'slb3\','
        for pid, param in enumerate(accurate_values[m[0].lower()]):
            print '            \'' + param_names[(pid + 1) * 2] + '\':', float(param) * param_scales[(pid + 1) * 2], ','
        print '            \'n\': sum(formula.values()),'
        print '            \'molar_mass\': formula_mass(formula)}'
        print ''
        if landau_params.has_key(m[0].lower()) or configurational_entropies[m[0].lower()] != 'None':
            print '        self.property_modifiers = [',
            if landau_params.has_key(m[0].lower()):
                print '[\'landau\', {\'Tc_0\':', landau_params[m[0].lower()][0], ', \'S_D\':', landau_params[m[0].lower()][2], ', \'V_D\':', landau_params[m[0].lower()][1], '}]',
            if configurational_entropies[m[0].lower()] != 'None':
                print '[\'linear\', {\'delta_E\':', 0., ', \'delta_S\':', configurational_entropies[m[0].lower()], ', \'delta_V\':', 0., '}]',
            print ']'
            print ''
        print '        self.uncertainties = {'
        for pid, param in enumerate(m):
            if pid > 1 and pid % 2 == 1 and pid < 21:
                print '            \'' + param_names[pid] + '\':', float(param) * param_scales[pid], ','
        pid = 21
        param = m[pid]
        print '            \'' + param_names[pid] + '\':', float(param) * param_scales[pid], '}'
        print '        Mineral.__init__(self)'
        print ''


aliasfile = 'slb_2011_aliases.txt'
with open(aliasfile, 'r') as fin:
    print fin.read()
fin.close()
