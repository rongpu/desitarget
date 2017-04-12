# Licensed under a 3-clause BSD style license - see LICENSE.rst
# -*- coding: utf-8 -*-
"""
=======================
desitarget.mock.spectra
=======================

Functions dealing with assigning template spectra to mock targets.

"""
from __future__ import (absolute_import, division, print_function)

import numpy as np
from time import time

from desisim.io import read_basis_templates, empty_metatable

class TemplateKDTree(object):
    """Build a KD Tree for each object type.

    """
    def __init__(self):
        from scipy.spatial import KDTree

        self.bgs_meta = read_basis_templates(objtype='BGS', onlymeta=True)
        self.elg_meta = read_basis_templates(objtype='ELG', onlymeta=True)
        self.lrg_meta = read_basis_templates(objtype='LRG', onlymeta=True)
        self.star_meta = read_basis_templates(objtype='STAR', onlymeta=True)
        self.qso_meta = read_basis_templates(objtype='QSO', onlymeta=True)
        self.wd_da_meta = read_basis_templates(objtype='WD', subtype='DA', onlymeta=True)
        self.wd_db_meta = read_basis_templates(objtype='WD', subtype='DB', onlymeta=True)

        self.bgs_tree = KDTree(self._bgs())
        self.elg_tree = KDTree(self._elg())
        #self.lrg_tree = KDTree(self._lrg())
        self.star_tree = KDTree(self._star())
        #self.qso_tree = KDTree(self._qso())
        self.wd_da_tree = KDTree(self._wd_da())
        self.wd_db_tree = KDTree(self._wd_db())

    def _bgs(self):
        """Quantities we care about: redshift (z), M_0.1r, and 0.1(g-r).  This needs to
        be generalized to accommodate other mocks!

        """
        zobj = self.bgs_meta['Z'].data
        mabs = self.bgs_meta['SDSS_UGRIZ_ABSMAG_Z01'].data
        rmabs = mabs[:, 2]
        gr = mabs[:, 1] - mabs[:, 2]
        return np.vstack((zobj, rmabs, gr)).T

    def _elg(self):
        """Quantities we care about: redshift, g-r, r-z."""
        
        zobj = self.elg_meta['Z'].data
        gr = self.elg_meta['DECAM_G'].data - self.elg_meta['DECAM_R'].data
        rz = self.elg_meta['DECAM_R'].data - self.elg_meta['DECAM_Z'].data
        #W1W2 = self.elg_meta['W1'].data - self.elg_meta['W2'].data
        return np.vstack((zobj, gr, rz)).T

    def _lrg(self):
        """Quantities we care about: r-z, r-W1."""
        
        zobj = self.elg_meta['Z'].data
        gr = self.elg_meta['DECAM_G'].data - self.elg_meta['DECAM_R'].data
        rz = self.elg_meta['DECAM_R'].data - self.elg_meta['DECAM_Z'].data
        #W1W2 = self.elg_meta['W1'].data - self.elg_meta['W2'].data
        return np.vstack((zobj, gr, rz)).T

    def _star(self):
        """Quantities we care about: Teff, logg, and [Fe/H].

        """
        teff = self.star_meta['TEFF'].data
        logg = self.star_meta['LOGG'].data
        feh = self.star_meta['FEH'].data
        return np.vstack((teff, logg, feh)).T

    #def qso(self):
    #    """Quantities we care about: redshift, XXX"""
    #    pass 

    def _wd_da(self):
        """DA white dwarf.  Quantities we care about: Teff and logg.

        """
        teff = self.wd_da_meta['TEFF'].data
        logg = self.wd_da_meta['LOGG'].data
        return np.vstack((teff, logg)).T

    def _wd_db(self):
        """DB white dwarf.  Quantities we care about: Teff and logg.

        """
        teff = self.wd_db_meta['TEFF'].data
        logg = self.wd_db_meta['LOGG'].data
        return np.vstack((teff, logg)).T

    def query(self, objtype, matrix, subtype=''):
        """Return the nearest template number based on the KD Tree.

        Args:
          objtype (str): object type
          matrix (numpy.ndarray): (M,N) array (M=number of properties,
            N=number of objects) in the same format as the corresponding
            function for each object type (e.g., self.bgs).
          subtype (str, optional): subtype (only for white dwarfs)

        Returns:
          dist: distance to nearest template
          indx: index of nearest template
        
        """
        if objtype.upper() == 'BGS':
            dist, indx = self.bgs_tree.query(matrix)
            
        elif objtype.upper() == 'ELG':
            dist, indx = self.elg_tree.query(matrix)
            
        elif objtype.upper() == 'LRG':
            dist, indx = self.lrg_tree.query(matrix)
            
        elif objtype.upper() == 'STAR':
            dist, indx = self.star_tree.query(matrix)
            
        elif objtype.upper() == 'QSO':
            dist, indx = self.qso_tree.query(matrix)
            
        elif objtype.upper() == 'WD':
            if subtype.upper() == 'DA':
                dist, indx = self.wd_da_tree.query(matrix)
            elif subtype.upper() == 'DB':
                dist, indx = self.wd_db_tree.query(matrix)
            else:
                log.warning('Unrecognized SUBTYPE {}!'.format(subtype))
                raise ValueError
                
        return dist, indx

class MockSpectra(object):
    """Generate spectra for each type of mock.  Currently just choose the closest
    template; we can get fancier later.

    ToDo (@moustakas): apply Galactic extinction.

    """
    def __init__(self, wavemin=None, wavemax=None, dw=0.2, rand=None, verbose=False):

        from desimodel.io import load_throughput
        
        self.tree = TemplateKDTree()

        # Build a default (buffered) wavelength vector.
        if wavemin is None:
            wavemin = load_throughput('b').wavemin - 10.0
        if wavemax is None:
            wavemax = load_throughput('z').wavemax + 10.0
            
        self.wavemin = wavemin
        self.wavemax = wavemax
        self.dw = dw
        self.wave = np.arange(round(wavemin, 1), wavemax, dw)

        self.rand = rand
        self.verbose = verbose

        #self.__normfilter = 'decam2014-r' # default normalization filter

        # Initialize the templates once:
        from desisim.templates import BGS, ELG, LRG, QSO, STAR, WD
        self.bgs_templates = BGS(wave=self.wave, normfilter='sdss2010-r') # Need to generalize this!
        self.elg_templates = ELG(wave=self.wave, normfilter='decam2014-r')
        self.lrg_templates = LRG(wave=self.wave, normfilter='decam2014-z')
        self.qso_templates = QSO(wave=self.wave, normfilter='decam2014-r')
        self.lya_templates = QSO(wave=self.wave, normfilter='decam2014-g')
        self.star_templates = STAR(wave=self.wave, normfilter='decam2014-r')
        self.wd_da_templates = WD(wave=self.wave, normfilter='decam2014-g', subtype='DA')
        self.wd_db_templates = WD(wave=self.wave, normfilter='decam2014-g', subtype='DB')
        
    def bgs(self, data, index=None, mockformat='durham_mxxl_hdf5'):
        """Generate spectra for BGS.

        Currently only the MXXL (durham_mxxl_hdf5) mock is supported.  DATA
        needs to have Z, SDSS_absmag_r01, SDSS_01gr, VDISP, and SEED, which are
        assigned in mock.io.read_durham_mxxl_hdf5.  See also
        TemplateKDTree.bgs().

        """
        objtype = 'BGS'
        if index is None:
            index = np.arange(len(data['Z']))
            
        input_meta = empty_metatable(nmodel=len(index), objtype=objtype)
        for inkey, datakey in zip(('SEED', 'MAG', 'REDSHIFT', 'VDISP'),
                                  ('SEED', 'MAG', 'Z', 'VDISP')):
            input_meta[inkey] = data[datakey][index]

        if mockformat.lower() == 'durham_mxxl_hdf5':
            alldata = np.vstack((data['Z'][index],
                                 data['SDSS_absmag_r01'][index],
                                 data['SDSS_01gr'][index])).T
            _, templateid = self.tree.query(objtype, alldata)
        else:
            raise ValueError('Unrecognized mockformat {}!'.format(mockformat))

        input_meta['TEMPLATEID'] = templateid
        flux, _, meta = self.bgs_templates.make_templates(input_meta=input_meta,
                                                          nocolorcuts=True, novdisp=True,
                                                          verbose=self.verbose)

        return flux, meta

    def elg(self, data, index=None, mockformat='gaussianfield'):
        """Generate spectra for the ELG sample.

        Currently only the GaussianField mock sample is supported.  DATA needs
        to have Z, GR, RZ, VDISP, and SEED, which are assigned in
        mock.io.read_gaussianfield.  See also TemplateKDTree.elg().

        """
        objtype = 'ELG'
        if index is None:
            index = np.arange(len(data['Z']))

        input_meta = empty_metatable(nmodel=len(index), objtype=objtype)
        for inkey, datakey in zip(('SEED', 'MAG', 'REDSHIFT', 'VDISP'),
                                  ('SEED', 'MAG', 'Z', 'VDISP')):
            input_meta[inkey] = data[datakey][index]

        if mockformat.lower() == 'gaussianfield':
            alldata = np.vstack((data['Z'][index],
                                 data['GR'][index],
                                 data['RZ'][index])).T
            _, templateid = self.tree.query(objtype, alldata)
        else:
            raise ValueError('Unrecognized mockformat {}!'.format(mockformat))

        input_meta['TEMPLATEID'] = templateid
        flux, _, meta = self.elg_templates.make_templates(input_meta=input_meta,
                                                          nocolorcuts=True, novdisp=True,
                                                          verbose=self.verbose)

        return flux, meta

    def lrg(self, data, index=None, mockformat='gaussianfield'):
        """Generate spectra for the LRG sample.

        Currently only the GaussianField mock sample is supported.  DATA needs
        to have Z, GR, RZ, VDISP, and SEED, which are assigned in
        mock.io.read_gaussianfield.  See also TemplateKDTree.lrg().

        """
        objtype = 'LRG'
        if index is None:
            index = np.arange(len(data['Z']))
        nobj = len(index)

        input_meta = empty_metatable(nmodel=len(index), objtype=objtype)
        for inkey, datakey in zip(('SEED', 'MAG', 'REDSHIFT', 'VDISP'),
                                  ('SEED', 'MAG', 'Z', 'VDISP')):
            input_meta[inkey] = data[datakey][index]

        if mockformat.lower() == 'gaussianfield':
            # This is wrong: choose a template with equal probability.
            templateid = self.rand.choice(self.tree.lrg_meta['TEMPLATEID'], len(index))
        else:
            raise ValueError('Unrecognized mockformat {}!'.format(mockformat))

        input_meta['TEMPLATEID'] = templateid
        flux, _, meta = self.lrg_templates.make_templates(input_meta=input_meta,
                                                          nocolorcuts=True, novdisp=True,
                                                          verbose=self.verbose)

        return flux, meta

    def mws(self, data, index=None, mockformat='galaxia'):
        """Generate spectra for the MWS_NEARBY and MWS_MAIN samples.

        """
        objtype = 'STAR'
        if index is None:
            index = np.arange(len(data['Z']))

        input_meta = empty_metatable(nmodel=len(index), objtype=objtype)
        for inkey, datakey in zip(('SEED', 'MAG', 'REDSHIFT', 'TEFF', 'LOGG', 'FEH'),
                                  ('SEED', 'MAG', 'Z', 'TEFF', 'LOGG', 'FEH')):
            input_meta[inkey] = data[datakey][index]

        if mockformat.lower() == '100pc':
            alldata = np.vstack((data['TEFF'][index],
                                 data['LOGG'][index],
                                 data['FEH'][index])).T
            _, templateid = self.tree.query(objtype, alldata)
            
        elif mockformat.lower() == 'galaxia':
            alldata = np.vstack((data['TEFF'][index],
                                 data['LOGG'][index],
                                 data['FEH'][index])).T
            _, templateid = self.tree.query(objtype, alldata)
        else:
            raise ValueError('Unrecognized mockformat {}!'.format(mockformat))

        input_meta['TEMPLATEID'] = templateid
        flux, _, meta = self.star_templates.make_templates(input_meta=input_meta,
                                                          verbose=self.verbose) # Note! No colorcuts.

        return flux, meta

    def mws_nearby(self, data, index=None, mockformat='100pc'):
        """Generate spectra for the MWS_NEARBY sample.

        """
        flux, meta = self.mws(data, index=index, mockformat=mockformat)
        return flux, meta

    def mws_main(self, data, index=None, mockformat='galaxia'):
        """Generate spectra for the MWS_MAIN sample.

        """
        flux, meta = self.mws(data, index=index, mockformat=mockformat)
        return flux, meta

    def faintstar(self, data, index=None, mockformat='galaxia'):
        """Generate spectra for the FAINTSTAR (faint stellar) sample.

        """
        flux, meta = self.mws(data, index=index, mockformat=mockformat)
        return flux, meta

    def mws_wd(self, data, index=None, mockformat='wd'):
        """Generate spectra for the MWS_WD sample.  Deal with DA vs DB white dwarfs
        separately.

        """
        objtype = 'WD'
        if index is None:
            index = np.arange(len(data['Z']))
        nobj = len(index)

        input_meta = empty_metatable(nmodel=nobj, objtype=objtype)
        for inkey, datakey in zip(('SEED', 'MAG', 'REDSHIFT', 'TEFF', 'LOGG', 'SUBTYPE'),
                                  ('SEED', 'MAG', 'Z', 'TEFF', 'LOGG', 'TEMPLATESUBTYPE')):
            input_meta[inkey] = data[datakey][index]

        if mockformat.lower() == 'wd':
            meta = empty_metatable(nmodel=nobj, objtype=objtype)
            flux = np.zeros([nobj, len(self.wave)], dtype='f4')
            
            for subtype in ('DA', 'DB'):
                these = np.where(input_meta['SUBTYPE'] == subtype)[0]
                if len(these) > 0:
                    alldata = np.vstack((data['TEFF'][index][these],
                                         data['LOGG'][index][these])).T
                    _, templateid = self.tree.query(objtype, alldata, subtype=subtype)

                    input_meta['TEMPLATEID'][these] = templateid
                    
                    template_function = 'wd_{}_templates'.format(subtype.lower())
                    flux1, _, meta1 = getattr(self, template_function).make_templates(input_meta=input_meta[these],
                                                          verbose=self.verbose)
                    
                    meta[these] = meta1
                    flux[these, :] = flux1
            
        else:
            raise ValueError('Unrecognized mockformat {}!'.format(mockformat))

        return flux, meta

    def qso(self, data, index=None, mockformat='gaussianfield'):
        """Generate spectra for the QSO or QSO/LYA samples.

        Note: We need to make sure NORMFILTER matches!

        """
        objtype = 'QSO'
        if index is None:
            index = np.arange(len(data['Z']))
        nobj = len(index)

        if mockformat.lower() == 'gaussianfield':
            # Build spectra for tracer QSOs.
            input_meta = empty_metatable(nmodel=nobj, objtype=objtype)
            for inkey, datakey in zip(('SEED', 'MAG', 'REDSHIFT'),
                                      ('SEED', 'MAG', 'Z')):
                input_meta[inkey] = data[datakey][index]

            flux, _, meta = self.qso_templates.make_templates(input_meta=input_meta,
                                                              nocolorcuts=True,
                                                              verbose=self.verbose)
        elif mockformat.lower() == 'lya':
            # Build spectra for Lyman-alpha QSOs.
            from astropy.table import vstack
            from desisim.lya_spectra import get_spectra
            from desitarget.mock.io import decode_rownum_filenum

            meta = empty_metatable(nmodel=nobj, objtype=objtype)
            flux = np.zeros([nobj, len(self.wave)], dtype='f4')
            
            rowindx, fileindx = decode_rownum_filenum(data['MOCKID'][index])
            for indx1 in set(fileindx):
                lyafile = data['FILES'][indx1]
                these = np.where(indx1 == fileindx)[0]
                templateid = rowindx[these].astype('int')
            
                flux1, _, meta1 = get_spectra(lyafile, templateid=templateid,
                                              normfilter=data['FILTERNAME'],
                                              rand=self.rand, qso=self.lya_templates)
                meta[these] = meta1
                flux[these, :] = flux1
        else:
            raise ValueError('Unrecognized mockformat {}!'.format(mockformat))

        return flux, meta

    def sky(self, data, index=None, mockformat=None):
        """Generate spectra for SKY.

        """
        objtype = 'SKY'
        if index is None:
            index = np.arange(len(data['Z']))
        nobj = len(index)
            
        meta = empty_metatable(nmodel=nobj, objtype=objtype)
        for inkey, datakey in zip(('SEED', 'REDSHIFT'),
                                  ('SEED', 'Z')):
            meta[inkey] = data[datakey][index]
        flux = np.zeros((nobj, len(self.wave)), dtype='f4')

        return flux, meta
