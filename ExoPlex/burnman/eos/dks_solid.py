# This file is part of BurnMan - a thermoelastic and thermodynamic toolkit for the Earth and Planetary Sciences
# Copyright (C) 2012 - 2015 by the BurnMan team, released under the GNU
# GPL v2 or later.

from __future__ import absolute_import

import numpy as np
import scipy.optimize as opt
import scipy.integrate as integrate
import warnings

# Try to import the jit from numba.  If it is
# not available, just go with the standard
# python interpreter
try:
    from numba import jit
except ImportError:
    def jit(fn):
        return fn


from . import birch_murnaghan as bm
from . import debye
from . import equation_of_state as eos
from ..utils.math import bracket


@jit
def _grueneisen_parameter_fast(V_0, volume, gruen_0, q_0):
    """global function with plain parameters so jit will work"""
    x = V_0 / volume
    f = 1. / 2. * (pow(x, 2. / 3.) - 1.)
    a1_ii = 6. * gruen_0  # EQ 47
    a2_iikk = -12. * gruen_0 + 36. * \
        gruen_0 * gruen_0 - 18. * q_0 * gruen_0  # EQ 47
    nu_o_nu0_sq = 1. + a1_ii * f + (1. / 2.) * a2_iikk * f * f  # EQ 41
    return 1. / 6. / nu_o_nu0_sq * (2. * f + 1.) * (a1_ii + a2_iikk * f)

def _intgroverVdV(V_0, volume, gruen_0, q_0):
    return integrate.quad(lambda x: _grueneisen_parameter_fast(V_0, x, gruen_0, q_0)/x, V_0, volume)[0]

@jit
def _delta_pressure(x, pressure, temperature, V_0, T_0, Cv, a1_ii, a2_iikk, b_iikk, b_iikkmm):
    f = 0.5 * (pow(V_0 / x, 2. / 3.) - 1.)
    nu_o_nu0_sq = 1. + a1_ii * f + (1. / 2.) * a2_iikk * f * f  # EQ 41
    gr = 1. / 6. / nu_o_nu0_sq * (2. * f + 1.) * (a1_ii + a2_iikk * f)

    return (1. / 3.) * (pow(1. + 2. * f, 5. / 2.)) * ((b_iikk * f) + (0.5 * b_iikkmm * f * f)) \
        + gr * Cv * (temperature - T_0) / x - pressure  # EQ 21


class DKS_S(eos.EquationOfState):

    """
    Base class for the finite strain solid equation of state detailed
    in :cite:`deKoker2013` (supplementary materials).
    """

    def volume_dependent_q(self, x, params):
        """
        Finite strain approximation for :math:`q`, the isotropic volume strain
        derivative of the grueneisen parameter.
        """
        f = 1. / 2. * (pow(x, 2. / 3.) - 1.)
        a1_ii = 6. * params['grueneisen_0']  # EQ 47
        a2_iikk = -12. * params['grueneisen_0'] + 36. * pow(
            params['grueneisen_0'], 2.) - 18. * params['q_0'] * params['grueneisen_0']  # EQ 47
        nu_o_nu0_sq = 1. + a1_ii * f + (1. / 2.) * a2_iikk * f * f  # EQ 41
        gr = 1. / 6. / nu_o_nu0_sq * (2. * f + 1.) * (a1_ii + a2_iikk * f)
        if np.abs(params['grueneisen_0']) < 1.e-10:  # avoids divide by zero if grueneisen_0 = 0.
            q = 1. / 9. * (18. * gr - 6.)
        else:
            q = 1. / 9. * \
                (18. * gr - 6. - 1. / 2. / nu_o_nu0_sq *
                 (2. * f + 1.) * (2. * f + 1.) * a2_iikk / gr)
        return q

    def _isotropic_eta_s(self, x, params):
        """
        Finite strain approximation for :math:`eta_{s0}`, the isotropic shear
        strain derivative of the grueneisen parameter.
        """
        f = 1. / 2. * (pow(x, 2. / 3.) - 1.)
        a2_s = -2. * params['grueneisen_0'] - 2. * params['eta_s_0']  # EQ 47
        a1_ii = 6. * params['grueneisen_0']  # EQ 47
        a2_iikk = -12. * params['grueneisen_0'] + 36. * pow(
            params['grueneisen_0'], 2.) - 18. * params['q_0'] * params['grueneisen_0']  # EQ 47
        nu_o_nu0_sq = 1. + a1_ii * f + \
            (1. / 2.) * a2_iikk * pow(f, 2.)  # EQ 41
        gr = 1. / 6. / nu_o_nu0_sq * (2. * f + 1.) * (a1_ii + a2_iikk * f)
        # EQ 46 NOTE the typo from Stixrude 2005:
        eta_s = - gr - \
            (1. / 2. * pow(nu_o_nu0_sq, -1.) * pow((2. * f) + 1., 2.) * a2_s)

        return eta_s

    # calculate isotropic thermal pressure, see
    # Matas et. al. (2007) eq B4
    def _thermal_pressure(self, T, V, params):
        gr = self.grueneisen_parameter(0., T, V, params)  # P not important
        return params['Cv'] * (T - params['T_0']) * gr

    def volume(self, pressure, temperature, params):
        """
        Returns molar volume. :math:`[m^3]`
        """
        T_0 = params['T_0']
        V_0 = params['V_0']
        Cv = params['Cv']

        a1_ii = 6. * params['grueneisen_0']  # EQ 47
        a2_iikk = -12. * params['grueneisen_0'] + 36. * pow(
            params['grueneisen_0'], 2.) - 18. * params['q_0'] * params['grueneisen_0']  # EQ 47

        b_iikk = 9. * params['K_0']  # EQ 28
        b_iikkmm = 27. * params['K_0'] * (params['Kprime_0'] - 4.)  # EQ 29z

        # we need to have a sign change in [a,b] to find a zero. Let us start with a
        # conservative guess:
        args = (pressure, temperature, V_0, T_0,
                Cv, a1_ii, a2_iikk, b_iikk, b_iikkmm)
        try:
            sol = bracket(_delta_pressure, params[
                          'V_0'], 1.e-2 * params['V_0'], args)
        except ValueError:
            raise Exception(
                'Cannot find a volume, perhaps you are outside of the range of validity for the equation of state?')
        return opt.brentq(_delta_pressure, sol[0], sol[1], args=args)

    def pressure(self, temperature, volume, params):
        """
        Returns the pressure of the mineral at a given temperature and volume [Pa]
        """
        gr = self.grueneisen_parameter(
            0.0, temperature, volume, params)  # does not depend on pressure

        b_iikk = 9. * params['K_0']  # EQ 28
        b_iikkmm = 27. * params['K_0'] * (params['Kprime_0'] - 4.)  # EQ 29
        f = 0.5 * (pow(params['V_0'] / volume, 2. / 3.) - 1.)  # EQ 24
        P = (1. / 3.) * (pow(1. + 2. * f, 5. / 2.)) \
            * ((b_iikk * f) + (0.5 * b_iikkmm * pow(f, 2.)))\
            + gr * params['Cv'] * (temperature - params['T_0']) / volume  # EQ 21

        return P

    def grueneisen_parameter(self, pressure, temperature, volume, params):
        """
        Returns grueneisen parameter :math:`[unitless]`
        """
        return _grueneisen_parameter_fast(params['V_0'], volume, params['grueneisen_0'], params['q_0'])

    def isothermal_bulk_modulus(self, pressure, temperature, volume, params):
        """
        Returns isothermal bulk modulus :math:`[Pa]`
        """

        E_th_diff = params['Cv'] * (temperature - params['T_0'])
        gr = self.grueneisen_parameter(pressure, temperature, volume, params)
        q = self.volume_dependent_q(params['V_0'] / volume, params)
        K = bm.bulk_modulus(volume, params) \
            + (gr + 1. - q) * (gr / volume) * E_th_diff \
            - (pow(gr, 2.) / volume) * E_th_diff

        return K

    def adiabatic_bulk_modulus(self, pressure, temperature, volume, params):
        """
        Returns adiabatic bulk modulus. :math:`[Pa]`
        """
        K_T = self.isothermal_bulk_modulus(
            pressure, temperature, volume, params)
        alpha = self.thermal_expansivity(pressure, temperature, volume, params)
        gr = self.grueneisen_parameter(pressure, temperature, volume, params)
        K_S = K_T * (1. + gr * alpha * temperature)
        return K_S

    def shear_modulus(self, pressure, temperature, volume, params):
        """
        Returns shear modulus. :math:`[Pa]`
        """
        T_0 = params['T_0']
        eta_s = self._isotropic_eta_s(params['V_0'] / volume, params)

        E_th_diff = params['Cv'] * (temperature - params['T_0'])
        return bm.shear_modulus_third_order(volume, params) - eta_s * (E_th_diff) / volume

    def molar_heat_capacity_v(self, pressure, temperature, volume, params):
        """
        Returns heat capacity at constant volume. :math:`[J/K/mol]`
        """
        return params['Cv']

    def molar_heat_capacity_p(self, pressure, temperature, volume, params):
        """
        Returns heat capacity at constant pressure. :math:`[J/K/mol]`
        """
        alpha = self.thermal_expansivity(pressure, temperature, volume, params)
        gr = self.grueneisen_parameter(pressure, temperature, volume, params)
        C_v = self.molar_heat_capacity_v(pressure, temperature, volume, params)
        C_p = C_v * (1. + gr * alpha * temperature)
        return C_p

    def thermal_expansivity(self, pressure, temperature, volume, params):
        """
        Returns thermal expansivity. :math:`[1/K]`
        """
        C_v = self.molar_heat_capacity_v(pressure, temperature, volume, params)
        gr = self.grueneisen_parameter(pressure, temperature, volume, params)
        K = self.isothermal_bulk_modulus(pressure, temperature, volume, params)
        alpha = gr * C_v / K / volume
        return alpha

    def gibbs_free_energy(self, pressure, temperature, volume, params):
        """
        Returns the Gibbs free energy at the pressure and temperature of the mineral [J/mol]
        """
        G = self.helmholtz_free_energy(
            pressure, temperature, volume, params) + pressure * volume
        return G

    def molar_internal_energy(self, pressure, temperature, volume, params):
        """
        Returns the internal energy at the pressure and temperature of the mineral [J/mol]
        """
        return self.helmholtz_free_energy(pressure, temperature, volume, params) + \
            temperature * \
            self.entropy(pressure, temperature, volume, params)

    def entropy(self, pressure, temperature, volume, params):
        """
        Returns the entropy at the pressure and temperature of the mineral [J/K/mol]
        """
        S_0 = params['S_0']
        gruen_0 = params['grueneisen_0']
        q_0 = params['q_0']
        S_th = params['Cv'] * (np.log(temperature/params['T_0']) +
                               _intgroverVdV(params['V_0'], volume, gruen_0, q_0))

        return S_0 + S_th

    def enthalpy(self, pressure, temperature, volume, params):
        """
        Returns the enthalpy at the pressure and temperature of the mineral [J/mol]
        """

        return self.helmholtz_free_energy(pressure, temperature, volume, params) + \
            temperature * self.entropy(pressure, temperature, volume, params) + \
            pressure * volume

    def helmholtz_free_energy(self, pressure, temperature, volume, params):
        """
        Returns the Helmholtz free energy at the pressure and temperature of the mineral [J/mol]
        """
        V_0 = params['V_0']
        gruen_0 = params['grueneisen_0']
        q_0 = params['q_0']
        x = V_0 / volume
        f = 1. / 2. * (pow(x, 2. / 3.) - 1.)
        b_iikk = 9. * params['K_0']  # EQ 28
        b_iikkmm = 27. * params['K_0'] * (params['Kprime_0'] - 4.)  # EQ 29

        T_0 = params['T_0']
        T = temperature
        S_0 = params['S_0']
        Cv = params['Cv']
        F_0 = params['E_0'] - T_0 * S_0
        F_cmp = 0.5 * b_iikk * f * f * V_0 + (1. / 6.) * V_0 * b_iikkmm * f * f * f
        F_th = - S_0 * (T - T_0) - \
               Cv * (T * np.log(T/T_0) - (T - T_0)) - \
               Cv * (T - T_0) * _intgroverVdV(V_0, volume, gruen_0, q_0)

        return F_0 + F_cmp + F_th

    def validate_parameters(self, params):
        """
        Check for existence and validity of the parameters
        """
        if 'T_0' not in params:
            params['T_0'] = 300.

        # If eta_s_0 is not included this is presumably deliberate,
        # as we can model density and bulk modulus just fine without it,
        # so just add it to the dictionary as nan
        # The same goes for the standard state Helmholtz free energy
        if 'eta_s_0' not in params:
            params['eta_s_0'] = float('nan')
        if 'E_0' not in params:
            params['E_0'] = float('nan')

        # First, let's check the EoS parameters for Tref
        bm.BirchMurnaghanBase.validate_parameters(
            bm.BirchMurnaghanBase(), params)

        # Now check all the required keys for the
        # thermal part of the EoS are in the dictionary
        expected_keys = ['Cv', 'grueneisen_0', 'q_0', 'eta_s_0']
        for k in expected_keys:
            if k not in params:
                raise KeyError('params object missing parameter : ' + k)

        # Finally, check that the values are reasonable.
        if params['T_0'] < 0.:
            warnings.warn('Unusual value for T_0', stacklevel=2)
        if params['Cv'] < 0. or params['Cv'] > 1000.:
            warnings.warn('Unusual value for Cv', stacklevel=2)
        if params['grueneisen_0'] < -0.005 or params['grueneisen_0'] > 10.:
            warnings.warn('Unusual value for grueneisen_0', stacklevel=2)
        if params['q_0'] < -10. or params['q_0'] > 10.:
            warnings.warn('Unusual value for q_0', stacklevel=2)
        if params['eta_s_0'] < -10. or params['eta_s_0'] > 10.:
            warnings.warn('Unusual value for eta_s_0', stacklevel=2)
