# -*- coding: utf-8 -*-
"""
Created on Tue Oct 10

@author: jaehyuk
"""

import numpy as np
import pyfeng as pf
import abc

class ModelABC(abc.ABC):
    beta = 1   # fixed (not used)
    vov, rho = 0.0, 0.0
    sigma, intr = None, None

    ### Numerical Parameters
    dt = 0.1
    n_path = 10000

    def __init__(self, sigma, vov=0, rho=0.0, beta=1.0, intr=0.0):
        self.sigma = sigma
        self.vov = vov
        self.rho = rho
        self.beta = beta
        self.intr = intr

    def base_model(self, sigma=None):
        if sigma is None:
            sigma = self.sigma

        if self.beta == 0:
            return pf.Norm(sigma, intr=self.intr)
        elif self.beta == 1:
            return pf.Bsm(sigma, intr=self.intr)
        else:
            raise ValueError(f'0<beta<1 not supported')

    def vol_smile(self, strike, spot, texp=1.0):
        ''''
        From the price from self.price() compute the implied vol
        Use self.bsm_model.impvol() method
        '''
        price = self.price(strike, spot, texp, cp=1)
        iv = self.base_model().impvol(price, strike, spot, texp, cp=1)
        return iv

    @abc.abstractmethod
    def price(self, strike, spot, texp=1.0, cp=1):
        """
        Vanilla option price

        Args:
            strike:
            spot:
            texp:
            cp:

        Returns:

        """
        return NotImplementedError

    def sigma_path(self, texp):
        """
        Path of sigma_t over the time discretization

        Args:
            texp:

        Returns:

        """
        n_dt = int(np.ceil(texp / self.dt))
        tobs = np.arange(1, n_dt + 1) / n_dt * texp
        dt = texp / n_dt
        assert texp == tobs[-1]

        Z_t = np.cumsum(np.random.standard_normal((n_dt, self.n_path)) * np.sqrt(dt), axis=0)
        sigma_t = np.exp(self.vov * (Z_t - self.vov/2 * tobs[:, None]))
        sigma_t = np.insert(sigma_t, 0, np.ones(sigma_t.shape[1]), axis=0)

        return sigma_t

    def intvar_normalized(self, sigma_path):
        """
        Normalized integraged variance I_t = \int_0^T sigma_t dt / (sigma_0^2 T)

        Args:
            sigma_path: sigma path

        Returns:

        """

        weight = np.ones(sigma_path.shape[0])
        weight[[0, -1]] = 0.5
        weight /= weight.sum()
        intvar = np.sum(weight[:, None] * sigma_path**2, axis=0)
        return intvar

class ModelBsmMC(ModelABC):
    """
    MC for Bsm SABR (beta = 1)
    """

    beta = 1.0   # fixed (not used)

    def price(self, strike, spot, texp=1.0, cp=1):
        '''
        Your MC routine goes here.
        (1) Generate the paths of sigma_t.
        (2) Simulate S_0, ...., S_T.
        (3) Calculate option prices (vector) for all strikes
        '''
        vol_path = self.sigma_path(texp)  # the path of sigma_t
        sigma_t = vol_path[-1, :]  # sigma_t at maturity (t=T)
        I_t = self.intvar_normalized(vol_path)

        Z = np.random.standard_normal(self.n_path)

        s_t = (1 / self.vov) * (sigma_t - 1.0) - 0.5 * self.sigma * self.rho * texp * I_t
        np.exp(self.rho * self.sigma * s_t, out=s_t)
        vol = self.sigma * np.sqrt((1 - self.rho ** 2) * I_t)
        volt = vol * np.sqrt(texp)
        S_t = s_t * spot * np.exp(volt * (Z - volt / 2))

        df = np.exp(-self.intr * texp)
        p = df * np.mean(np.fmax(cp*(S_t - strike[:, None]), 0.0), axis=1)
        return p

class ModelNormMC(ModelBsmMC):
    """
    MC for Normal SABR (beta = 0)
    """

    beta = 0   # fixed (not used)

    def price(self, strike, spot, texp=1.0, cp=1):
        '''
        Your MC routine goes here.
        (1) Generate the paths of sigma_t.
        (2) Simulate S_0, ...., S_T.
        (3) Calculate option prices (vector) for all strikes
        '''
        vol_path = self.sigma_path(texp)  # the path of sigma_t
        sigma_t = vol_path[-1, :]  # sigma_t at maturity (t=T)
        I_t = self.intvar_normalized(vol_path)

        df = np.exp(-self.intr * texp)

        Z = np.random.standard_normal(self.n_path)  # 标准正态随机数

        s_t = (self.rho / self.vov) * (sigma_t - 1) * self.sigma

        # Generate random normals for price paths
        Z = np.random.standard_normal(sigma_t.shape)
        vol = self.sigma * np.sqrt((1 - self.rho ** 2) * I_t)
        volt = vol * np.sqrt(texp)
        S_t = s_t + spot / df + volt * Z

        p = df * np.mean(np.fmax(cp*(S_t - strike[:, None]), 0.0), axis=1)
        return p

class ModelBsmCondMC(ModelBsmMC):
    """
    Conditional MC for Bsm SABR (beta = 1)
    """

    def price(self, strike, spot, texp=1.0, cp=1):
        '''
        Your MC routine goes here.
        (1) Generate the paths of sigma_t and normalized integrated variance
        (2) Calculate the equivalent spot and volatility of the BS model
        (3) Calculate option prices (vector) by averaging the BS prices
        '''


        vol_path = self.sigma_path(texp)  # the path of sigma_t
        sigma_t = vol_path[-1, :]  # sigma_t at maturity (t=T)
        I_t = self.intvar_normalized(vol_path)

        vol = self.sigma * np.sqrt((1 - self.rho ** 2) * I_t)  # Equivalent volatility
        volt = vol * np.sqrt(texp)
        df = np.exp(-self.intr * texp)  # Discount factor
        # Adjusting for conditional forward calculation as per the given formula
        s_t = (1 / self.vov) * (sigma_t - 1.0) - 0.5 * self.sigma * self.rho * texp * I_t
        np.exp(self.rho * self.sigma * s_t, out=s_t)
        c_f_spot = s_t * spot / df

        Z = np.random.standard_normal(self.n_path)
        spot_equiv = c_f_spot * np.exp(volt * (Z - volt / 2))

        m = self.base_model(vol)  # Assuming base_model is set up to use the adjusted volatility
        p = np.mean(m.price(strike[:, None], spot_equiv, texp, cp), axis=1)

        return p

class ModelNormCondMC(ModelNormMC):
    """
    Conditional MC for Normal SABR (beta = 0)
    """

    def price(self, strike, spot, texp=1.0, cp=1):

        vol_path = self.sigma_path(texp)  # the path of sigma_t
        sigma_t = vol_path[-1, :]  # sigma_t at maturity (t=T)
        I_t = self.intvar_normalized(vol_path)
        vol = self.sigma * np.sqrt((1 - self.rho ** 2) * I_t)  # Equivalent volatility

        Z = np.random.standard_normal(self.n_path)
        S_T = spot + sigma_t * np.sqrt(I_t) + sigma_t * np.sqrt(texp) * Z

        m = self.base_model(vol)
        p = np.mean(m.price(strike[:, None], S_T, texp, cp), axis=1)

        return p

