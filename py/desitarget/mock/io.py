# Licensed under a 3-clause BSD style license - see LICENSE.rst
# -*- coding: utf-8 -*-
"""
desitarget.mock.io
==================

Code to read in all the mock data.

"""
from __future__ import absolute_import, division, print_function

import os
import numpy as np

import fitsio
from scipy import constants

from desitarget.io import check_fitsio_version, iter_files
from desitarget.mock.sample import SampleGMM
from desispec.brick import brickname as get_brickname_from_radec

from desiutil.log import get_logger, DEBUG
log = get_logger(DEBUG)

"""How to distribute 52 user bits of targetid.

Used to generate target IDs as combination of input file and row in input file.
Sets the maximum number of rows per input file for mocks using this scheme to
generate target IDs

"""
# First 32 bits are row
ENCODE_ROW_END     = 32
ENCODE_ROW_MASK    = 2**ENCODE_ROW_END - 2**0
ENCODE_ROW_MAX     = ENCODE_ROW_MASK
# Next 20 bits are file
ENCODE_FILE_END    = 52
ENCODE_FILE_MASK   = 2**ENCODE_FILE_END - 2**ENCODE_ROW_END
ENCODE_FILE_MAX    = ENCODE_FILE_MASK >> ENCODE_ROW_END

try:
    C_LIGHT = constants.c/1000.0
except TypeError:
    #
    # This can happen during documentation builds.
    #
    C_LIGHT = 299792458.0/1000.0

def print_all_mocks_info(params):
    """Prints parameters to read mock files.

    Parameters
    ----------
        params : dict
            The different kind of sources are stored under the 'sources' key.

    """
    log.info('Paths and targets:')
    for source_name in params['sources'].keys():
        source_format = params['sources'][source_name]['format']
        source_path = params['sources'][source_name]['mock_dir_name']
        target_name = params['sources'][source_name]['target_name']
        log.info('source_name: {}\n format: {} \n target_name {} \n path: {}'.format(source_name,
                                                                                  source_format,
                                                                                  target_name,
                                                                                  source_path))

def load_all_mocks(params, rand=None, bricksize=0.25, nproc=1):
    """Read all the mocks.

    Parameters
    ----------
    params : dict
        The different kind of sources are stored under the 'sources' key.
    rand : numpy.RandomState
        RandomState object used for the random number generation.

    Returns
    -------
    source_data_all : dict
        The keys correspond to the different input 'sources' stored under
        params['sources'].keys()

    """
    if rand is None:
        rand = np.random.RandomState()

    check_fitsio_version() # Make sure fitsio is up to date.

    #loaded_mocks = list()

    source_data_all = {}
    for source_name in sorted(params['sources'].keys()):

        target_name = params['sources'][source_name]['target_name']
        source_format = params['sources'][source_name]['format']
        mock_dir_name = params['sources'][source_name]['mock_dir_name']
        bounds = params['sources'][source_name]['bounds']

        if 'magcut' in params['sources'][source_name].keys():
            magcut = params['sources'][source_name]['magcut']
        else:
            magcut = None

        read_function = 'read_{}'.format(source_format)

        log.info('Source: {}, target: {}, format: {}'.format(source_name, target_name.upper(), source_format))
        log.info('Reading {} with mock.io.{}'.format(mock_dir_name, read_function))

        func = globals()[read_function]
        if 'LYA' in params['sources'][source_name].keys():
            result = func(mock_dir_name, target_name, rand=rand, bricksize=bricksize,
                          bounds=bounds, magcut=magcut, nproc=nproc, lya=params['sources'][source_name]['LYA'])
        else:
            result = func(mock_dir_name, target_name, rand=rand, bricksize=bricksize,
                          bounds=bounds, magcut=magcut, nproc=nproc)

        source_data_all[source_name] = result
        print()

        #if target_name not in loaded_mocks: # not sure if this is right
        ##if this_name not in loaded_mocks.keys():
        #    loaded_mocks.append(target_name)
        #
        #    func = globals()[read_function]
        #    result = func(mock_dir_name, target_name, rand=rand, bricksize=bricksize,
        #                  bounds=bounds, magcut=magcut)
        #    source_data_all[source_name] = result
        #    print()
        #else:
        #    #log.info('pointing towards the results of {} for {}'.format(loaded_mocks[this_name], source_name))
        #    source_data_all[target_name] = source_data_all[loaded_mocks[target_name]]

    log.info('Loaded {} mock catalog(s).'.format(len(source_data_all)))
    return source_data_all

def encode_rownum_filenum(rownum, filenum):
    """Encodes row and file number in 52 packed bits.

    Parameters
    ----------
    rownum : int
        Row in input file.
    filenum : int
        File number in input file set.

    Returns
    -------
    encoded value(s) : int64 numpy.ndarray
        52 packed bits encoding row and file number.

    """
    assert(np.shape(rownum) == np.shape(filenum))
    assert(np.all(rownum  >= 0))
    assert(np.all(rownum  <= int(ENCODE_ROW_MAX)))
    assert(np.all(filenum >= 0))
    assert(np.all(filenum <= int(ENCODE_FILE_MAX)))

    # This should be a 64 bit integer.
    encoded_value = (np.asarray(filenum,dtype=np.uint64) << ENCODE_ROW_END) + np.asarray(rownum, dtype=np.uint64)

    # Note return signed
    return np.asarray(encoded_value, dtype=np.int64)

def decode_rownum_filenum(encoded_values):
    """Inverts encode_rownum_filenum to obtain row number and file number.

    Parameters
    ----------
    encoded_values(s) : int64 ndarray

    Returns
    -------
    filenum : str
        File number.
    rownum : int
        Row number.

    """
    filenum = (np.asarray(encoded_values,dtype=np.uint64) & ENCODE_FILE_MASK) >> ENCODE_ROW_END
    rownum  = (np.asarray(encoded_values,dtype=np.uint64) & ENCODE_ROW_MASK)
    return rownum, filenum

def make_mockid(objid, n_per_file):
    """
    Computes mockid from row and file IDs.

    Parameters
    ----------
    objid : int array
        Row identification number.
    n_per_file : int list
        Number of items per file that went into objid.

    Returns
    -------
    mockid : int array
        Encoded row and file ID.

    """
    n_files = len(n_per_file)
    n_obj = len(objid)

    n_p_file = np.array(n_per_file)
    n_per_file_cumsum = n_p_file.cumsum()

    filenum = np.zeros(n_obj, dtype='int64')
    for n in range(1, n_files):
        filenum[n_per_file_cumsum[n-1]:n_per_file_cumsum[n]] = n

    return encode_rownum_filenum(objid, filenum)

def read_100pc(mock_dir_name, target_name='STAR', rand=None, bricksize=0.25,
               bounds=None, magcut=None, nproc=None):
    """Read a single-file GUMS-based mock of nearby (d<100 pc) normal stars (i.e.,
    no white dwarfs).

    Parameters
    ----------
    mock_dir_name : str
        Complete path and filename of the mock catalog.
    target_name : str
        Target name (not used; defaults to `STAR`).
    rand : numpy.RandomState
        RandomState object used for the random number generation.
    bricksize : float
        Size of each brick in deg.
    bounds : 4-element tuple
        Restrict the sample to bounds = (min_ra, max_ra, min_dec, max_dec).
    magcut : float
        Magnitude cut to apply to the sample (not used here).
    nproc : int
        Number of cores to use for reading (not used here).

    Returns
    -------
    Dictionary with the following entries.
        'OBJID' : int64 numpy.ndarray
            Object identification number for each file in mock_dir_name.
        'MOCKID': int numpy.ndarray
            Unique mock identification number.
        'RA': numpy.ndarray
            RA positions for the objects in the mock.
        'DEC' : numpy.ndarray
            DEC positions for the objects in the mock.
        'Z' : numpy.ndarray
            Heliocentric radial velocity divided by the speed of light.
        'BRICKNAME' : str numpy.ndarray
            Brick name assigned according to RA, Dec coordinates.
        'SEED' : int numpy.ndarray
            Random seed used in the template-generating code.
        'MAG': numpy.ndarray
            Apparent magnitude in SDSS g-band(???).
        'TEFF': numpy.ndarray
            Effective stellar temperature (K).
        'LOGG': numpy.ndarray
            Surface gravity (cm/s**2).
        'FEH': numpy.ndarray
            Logarithmic iron abundance relative to solar.
        'FILTERNAME': str
            Filter name corresponding to mag (used to normalize the spectra).
        'TRUESPECTYPE': str
            Set to `STAR` for this whole sample.
        'TEMPLATETYPE': str
            Set to `STAR` for this whole sample.
        'TEMPLATESUBTYPE': numpy.ndarray
            Spectral class for each object (e.g., GV) based on the GUMS mock.
        'FILES': str list
            List of all mock file(s) read.
        'N_PER_FILE': int list
            Number of mock targets per file.

    """
    mockfile = mock_dir_name
    try:
        os.stat(mockfile)
    except:
        log.fatal('Mock file {} not found!'.format(mockfile))
        raise IOError

    cols = ['RA','DEC','RADIALVELOCITY', 'MAGG',
            'TEFF', 'LOGG', 'FEH', 'SPECTRALTYPE']
    data = fitsio.read(mockfile, ext=1, upper=True, columns=cols)

    ra = data['RA'].astype('f8') % 360.0 #enforce 0 < ra < 360
    dec = data['DEC'].astype('f8')
    zz = (data['RADIALVELOCITY'] / C_LIGHT).astype('f4')
    mag = data['MAGG'].astype('f4') # SDSS g-band
    teff = data['TEFF'].astype('f4')
    logg = data['LOGG'].astype('f4')
    feh = data['FEH'].astype('f4')
    templatesubtype = data['SPECTRALTYPE']

    nobj = len(ra)
    log.info('Read {} objects from {}.'.format(nobj, mockfile))

    if bounds is not None:
        min_ra, max_ra, min_dec, max_dec = bounds
        cut = (ra >= min_ra) * (ra <= max_ra) * (dec >= min_dec) * (dec <= max_dec)
        if np.count_nonzero(cut) == 0:
            log.fatal('No objects in range RA={}, {}, Dec={}, {}!'.format(nobj, min_ra, max_ra, min_dec, max_dec))
            raise ValueError
        ra = ra[cut]
        dec = dec[cut]
        zz = zz[cut]
        mag = mag[cut]
        teff = teff[cut]
        logg = logg[cut]
        feh = feh[cut]
        templatesubtype = templatesubtype[cut]
        nobj = len(ra)
        log.info('Trimmed to {} objects in range RA={}, {}, Dec={}, {}'.format(nobj, min_ra, max_ra, min_dec, max_dec))

    files = list()
    files.append(mockfile)
    n_per_file = list()
    n_per_file.append(nobj)

    objid = np.arange(nobj, dtype='i8')
    mockid = make_mockid(objid, n_per_file)
    brickname = get_brickname_from_radec(ra, dec, bricksize=bricksize)

    seed = rand.randint(2**32, size=nobj)

    return {'OBJID': objid, 'MOCKID': mockid, 'RA': ra, 'DEC': dec, 'Z': zz,
            'BRICKNAME': brickname, 'SEED': seed, 'MAG': mag, 'TEFF': teff, 'LOGG': logg, 'FEH': feh,
            'FILTERNAME': 'sdss2010-g', # ?????
            'TRUESPECTYPE': 'STAR', 'TEMPLATETYPE': 'STAR', 'TEMPLATESUBTYPE': templatesubtype,
            'FILES': files, 'N_PER_FILE': n_per_file}

def read_wd(mock_dir_name, target_name='WD', rand=None, bricksize=0.25,
               bounds=None, magcut=None, nproc=None):
    """Read a single-file GUMS-based mock of white dwarfs.

    Parameters
    ----------
    mock_dir_name : str
        Complete path and filename of the mock catalog.
    target_name : str
        Target name (not used; defaults to `WD`).
    rand : numpy.RandomState
        RandomState object used for the random number generation.
    bricksize : float
        Size of each brick in deg.
    bounds : 4-element tuple
        Restrict the sample to bounds = (min_ra, max_ra, min_dec, max_dec).
    magcut : float
        Magnitude cut to apply to the sample (not used here).
    nproc : int
        Number of cores to use for reading (not used here).

    Returns
    -------
    Dictionary with the following entries.
        'OBJID' : int64 numpy.ndarray
            Object identification number for each file in mock_dir_name.
        'MOCKID': int numpy.ndarray
            Unique mock identification number.
        'RA': numpy.ndarray
            RA positions for the objects in the mock.
        'DEC' : numpy.ndarray
            DEC positions for the objects in the mock.
        'Z' : numpy.ndarray
            Heliocentric radial velocity divided by the speed of light.
        'BRICKNAME' : str numpy.ndarray
            Brick name assigned according to RA, Dec coordinates.
        'SEED' : int numpy.ndarray
            Random seed used in the template-generating code.
        'MAG': numpy.ndarray
            Apparent magnitude in the SDSS g-band.
        'TEFF': numpy.ndarray
            Effective stellar temperature (K).
        'LOGG': numpy.ndarray
            Surface gravity (cm/s**2).
        'FILTERNAME': str
            Filter name corresponding to mag (used to normalize the spectra).
        'TRUESPECTYPE': str
            Set to `STAR` for this whole sample.
        'TEMPLATETYPE': str
            Set to `WD` for this whole sample.
        'TEMPLATESUBTYPE': numpy.ndarray
            Spectral class for each object (DA vs DB) based on the GUMS mock.
        'FILES': str list
            List of all mock file(s) read.
        'N_PER_FILE': int list
            Number of mock targets per file.

    """
    mockfile = mock_dir_name
    try:
        os.stat(mockfile)
    except:
        log.fatal('Mock file {} not found!'.format(mockfile))
        raise IOError

    cols = ['RA','DEC','RADIALVELOCITY', 'G_SDSS',
            'TEFF', 'LOGG', 'SPECTRALTYPE']
    data = fitsio.read(mockfile, ext=1, upper=True, columns=cols)

    ra = data['RA'].astype('f8') % 360.0 #enforce 0 < ra < 360
    dec = data['DEC'].astype('f8')
    zz = (data['RADIALVELOCITY'] / C_LIGHT).astype('f4')
    mag = data['G_SDSS'].astype('f4') # SDSS g-band
    teff = data['TEFF'].astype('f4')
    logg = data['LOGG'].astype('f4')
    templatesubtype = np.char.upper(data['SPECTRALTYPE'].astype('<U'))

    nobj = len(ra)
    log.info('Read {} objects from {}.'.format(nobj, mockfile))

    if bounds is not None:
        min_ra, max_ra, min_dec, max_dec = bounds
        cut = (ra >= min_ra) * (ra <= max_ra) * (dec >= min_dec) * (dec <= max_dec)
        if np.count_nonzero(cut) == 0:
            log.fatal('No objects in range RA={}, {}, Dec={}, {}!'.format(nobj, min_ra, max_ra, min_dec, max_dec))
            raise ValueError
        ra = ra[cut]
        dec = dec[cut]
        zz = zz[cut]
        mag = mag[cut]
        teff = teff[cut]
        logg = logg[cut]
        templatesubtype = templatesubtype[cut]
        nobj = len(ra)
        log.info('Trimmed to {} objects in range RA={}, {}, Dec={}, {}'.format(nobj, min_ra, max_ra, min_dec, max_dec))

    files = list()
    files.append(mockfile)
    n_per_file = list()
    n_per_file.append(nobj)

    objid = np.arange(nobj, dtype='i8')
    mockid = make_mockid(objid, n_per_file)
    brickname = get_brickname_from_radec(ra, dec, bricksize=bricksize)

    seed = rand.randint(2**32, size=nobj)

    return {'OBJID': objid, 'MOCKID': mockid, 'RA': ra, 'DEC': dec, 'Z': zz,
            'BRICKNAME': brickname, 'SEED': seed, 'MAG': mag, 'TEFF': teff, 'LOGG': logg,
            'FILTERNAME': 'sdss2010-g',
            'TRUESPECTYPE': 'STAR', 'TEMPLATETYPE': 'WD', 'TEMPLATESUBTYPE': templatesubtype,
            'FILES': files, 'N_PER_FILE': n_per_file}

def _sample_vdisp(logvdisp_meansig, nmodel=1, rand=None):
    """Choose a subset of velocity dispersions."""
    if rand is None:
        rand = np.random.RandomState()

    fracvdisp = (0.1, 40)

    nvdisp = int(np.max( ( np.min( ( np.round(nmodel * fracvdisp[0]), fracvdisp[1] ) ), 1 ) ))
    vvdisp = 10**rand.normal(logvdisp_meansig[0], logvdisp_meansig[1], nvdisp)
    vdisp = rand.choice(vvdisp, nmodel)
    
    return vdisp

def read_gaussianfield(mock_dir_name, target_name, rand=None, bricksize=0.25,
                       lya=None, bounds=None, magcut=None, nproc=None):
    """Reads the GaussianRandomField mocks for ELGs, LRGs, and QSOs.

    Parameters
    ----------
    mock_dir_name : str
        Complete top-level path to the mock catalogs or the mock filename (for SKY).
    target_name : str
        Target name specifying the mock catalog to read ('LRG', 'ELG', 'QSO', or
        'SKY').
    rand : numpy.RandomState
        RandomState object used for the random number generation.
    bricksize : float
        Size of each brick in deg.
    bounds : 4-element tuple
        Restrict the sample to bounds = (min_ra, max_ra, min_dec, max_dec).
    magcut : float
        Magnitude cut to apply to the sample (not used here).
    nproc : int
        Number of cores to use for reading (not used here).
    lya : dictionary
        Information on the Lyman-alpha mock to read.

    Returns
    -------
    Dictionary with the following basic entries (for SKY).
        'OBJID' : int64 numpy.ndarray
            Object identification number for each file in mock_dir_name.
        'MOCKID': int numpy.ndarray
            Unique mock identification number.
        'RA': numpy.ndarray
            RA positions for the objects in the mock.
        'DEC' : numpy.ndarray
            DEC positions for the objects in the mock.
        'Z' : numpy.ndarray
            Heliocentric redshift (equal to zero for SKY).
        'BRICKNAME' : str numpy.ndarray
            Brick name assigned according to RA, Dec coordinates.
        'SEED' : int numpy.ndarray
            Random seed used in the template-generating code.
        'TRUESPECTYPE': str
            Set to one of SKY, GALAXY (for ELG and LRG), or QSO.
        'TEMPLATETYPE': str
            Set to one of SKY, ELG, LRG, or QSO.
        'TEMPLATESUBTYPE': numpy.ndarray
            Not used for now (empty string for all target names).
        'FILES': str list
            List of all mock file(s) read.
        'N_PER_FILE': int list
            Number of mock targets per file.

    The target names ELG, LRG, and QSO have the following additional/optional
    keys.
        'GR': numpy.ndarray
            Apparent g-r color (only for ELG, QSO).
        'RZ': numpy.ndarray
            Apparent r-z color
        'RW1': numpy.ndarray
            Apparent r-W1 color (only for LRG).
        'W1W2': numpy.ndarray
            Apparent W1-W2 color (only for QSO).
        'MAG': numpy.ndarray
            Apparent magnitude in the DECam r-, z-, or g-band (for ELG, LRG, QSO, resp.)
        'FILTERNAME': str
            Filter name corresponding to mag (used to normalize the spectra).
        'VDISP': numpy.ndarray
            Velocity dispersion (km/s) (only for ELG, LRG).

    """
    if target_name == 'SKY':
        mockfile = mock_dir_name
        columns = ['RA', 'DEC']
    else:
        mockfile = os.path.join(mock_dir_name, '{}.fits'.format(target_name.upper()))
        columns = ['RA', 'DEC', 'Z_COSMO', 'DZ_RSD']

    try:
        os.stat(mockfile)
    except:
        log.fatal('Mock file {} not found!'.format(mockfile))
        raise IOError

    data = fitsio.read(mockfile, columns=columns, upper=True, ext=1)

    ra = data['RA'].astype('f8') % 360.0 # enforce 0 < ra < 360
    dec = data['DEC'].astype('f8')
    
    if target_name == 'SKY':
        zz = np.zeros(len(ra), dtype='f4')
    else:
        zz = (data['Z_COSMO'].astype('f8') + data['DZ_RSD'].astype('f8')).astype('f4')
    del data

    nobj = len(ra)
    log.info('Read {} objects from {}.'.format(nobj, mockfile))

    mag = np.repeat(-1, nobj) # placeholder

    files = list()
    n_per_file = list()
    files.append(mockfile)
    n_per_file.append(nobj)

    objid = np.arange(nobj, dtype='i8')
    mockid = make_mockid(objid, n_per_file)
    
    # Combine the QSO and Lyman-alpha samples.
    if target_name == 'QSO' and lya:

        log.info('Adding Lyman-alpha targets.')

        #truespectype = np.repeat('QSO', nobj)
        #templatetype = np.repeat('QSO', nobj)
        #templatesubtype = np.repeat('', nobj)

        mockfile_lya = lya['mock_dir_name']
        columns = ['RA', 'DEC', 'Z', 'MAG_G']

        try:
            os.stat(mockfile_lya)
        except:
            log.fatal('Mock file {} not found!'.format(mockfile_lya))
            raise IOError

        data = fitsio.read(mockfile_lya, columns=columns, upper=True, ext=1)

        ra_lya = data['RA'].astype('f8') % 360.0 # enforce 0 < ra < 360
        dec_lya = data['DEC'].astype('f8')
        zz_lya = data['Z'].astype('f4')
        mag_lya = data['MAG_G'].astype('f4') # g-band
        nobj_lya = len(ra_lya)
        log.info('Read {} objects from {}.'.format(nobj_lya, mockfile_lya))

        files.append(mockfile_lya)
        n_per_file.append(nobj_lya)

        objid_lya = np.arange(nobj_lya, dtype='i8')
        mockid_lya = make_mockid(objid_lya, [n_per_file[1]])

        # Join the QSO + Lya samples, cutting at zcut (=2.1)
        ra = np.concatenate((ra, ra_lya))
        dec = np.concatenate((dec, dec_lya))
        zz  = np.concatenate((zz, zz_lya))
        mag = np.concatenate((mag, mag_lya))
        objid = np.concatenate((objid, objid_lya))
        mockid = np.concatenate((mockid, mockid_lya))
        nobj = len(ra)

        log.info('Combined QSO+Lya sample has {} targets.'.format(nobj))
        
    if bounds is not None:
        min_ra, max_ra, min_dec, max_dec = bounds
        cut = (ra >= min_ra) * (ra <= max_ra) * (dec >= min_dec) * (dec <= max_dec)
        if np.count_nonzero(cut) == 0:
            log.fatal('No objects in range RA={}, {}, Dec={}, {}!'.format(nobj, min_ra, max_ra, min_dec, max_dec))
            raise ValueError
        objid = objid[cut]
        mockid = mockid[cut]
        ra = ra[cut]
        dec = dec[cut]
        zz = zz[cut]
        nobj = len(ra)
        log.info('Trimmed to {} objects in range RA={}, {}, Dec={}, {}'.format(nobj, min_ra, max_ra, min_dec, max_dec))
    
    brickname = get_brickname_from_radec(ra, dec, bricksize=bricksize)

    seed = rand.randint(2**32, size=nobj)

    # Create a basic dictionary for SKY.
    out = {'OBJID': objid, 'MOCKID': mockid, 'RA': ra, 'DEC': dec, 'Z': zz,
           'BRICKNAME': brickname, 'SEED': seed, 'FILES': files,
           'N_PER_FILE': n_per_file}

    # Assign magnitudes / colors based on the appropriate Gaussian mixture model.
    if target_name == 'SKY':
        out.update({'TRUESPECTYPE': 'SKY', 'TEMPLATETYPE': 'SKY', 'TEMPLATESUBTYPE': ''})
    else:
        log.info('Sampling from Gaussian mixture model.')
        GMM = SampleGMM(random_state=rand)
        mags = GMM.sample(target_name, nobj) # [g, r, z, w1, w2, w3, w4]

        out.update({'GR': mags['g']-mags['r'], 'RZ': mags['r']-mags['z'],
                    'RW1': mags['r']-mags['w1'], 'W1W2': mags['w1']-mags['w2']})

        if target_name in ('ELG', 'LRG'):
            out.update({
                'SHAPEEXP_R': mags['exp_r'], 'SHAPEEXP_E1': mags['exp_e1'], 'SHAPEEXP_E2': mags['exp_e2'], 
                'SHAPEDEV_R': mags['dev_r'], 'SHAPEDEV_E1': mags['dev_e1'], 'SHAPEDEV_E2': mags['dev_e2']
                })

        if target_name == 'ELG':
            """Selected in the r-band with g-r, r-z colors."""
            vdisp = _sample_vdisp((1.9, 0.15), nmodel=nobj, rand=rand)
            out.update({'TRUESPECTYPE': 'GALAXY', 'TEMPLATETYPE': 'ELG', 'TEMPLATESUBTYPE': '',
                        'VDISP': vdisp, 'MAG': mags['r'], 'FILTERNAME': 'decam2014-r'})

        elif target_name == 'LRG':
            """Selected in the z-band with r-z, r-W1 colors."""
            vdisp = _sample_vdisp((2.3, 0.1), nmodel=nobj, rand=rand)
            out.update({'TRUESPECTYPE': 'GALAXY', 'TEMPLATETYPE': 'LRG', 'TEMPLATESUBTYPE': '',
                        'VDISP': vdisp, 'MAG': mags['z'], 'FILTERNAME': 'decam2014-z'})

        elif target_name == 'QSO':
            """Selected in the r-band with g-r, r-z, and W1-W2 colors."""
            replace = np.where(mag == -1)[0]
            if len(replace) > 0:
                mag[replace] = mags['g'] # g-band
            
            out.update({
                'TRUESPECTYPE': 'QSO', 'TEMPLATETYPE': 'QSO', 'TEMPLATESUBTYPE': 'LYA',
                #'TRUESPECTYPE': truespectype, 'TEMPLATETYPE': templatetype, 'TEMPLATESUBTYPE': templatesubtype,
                'MAG': mag, 'FILTERNAME': 'decam2014-g'}) # Lya is normalized in the g-band

        else:
            log.fatal('Unrecognized target type {}!'.format(target_name))
            raise ValueError

    return out

def read_durham_mxxl_hdf5(mock_dir_name, target_name='BGS', rand=None, bricksize=0.25,
                          bounds=None, magcut=None, nproc=None):
    """ Reads the MXXL mock of BGS galaxies.

    Parameters
    ----------
    mock_dir_name : str
        Complete path and filename of the mock catalog.
    target_name : str
        Target name (not used; defaults to `BGS`).
    rand : numpy.RandomState
        RandomState object used for the random number generation.
    bricksize : float
        Size of each brick in deg.
    bounds : 4-element tuple
        Restrict the sample to bounds = (min_ra, max_ra, min_dec, max_dec).
    magcut : float
        Magnitude cut to apply to the sample (not used here).
    nproc : int
        Number of cores to use for reading (not used here).

    Returns
    -------
    Dictionary with the following entries.
        'OBJID' : int64 numpy.ndarray
            Object identification number for each file in mock_dir_name.
        'MOCKID': int numpy.ndarray
            Unique mock identification number.
        'RA': numpy.ndarray
            RA positions for the objects in the mock.
        'DEC' : numpy.ndarray
            DEC positions for the objects in the mock.
        'Z' : numpy.ndarray
            Heliocentric redshift.
        'BRICKNAME' : str numpy.ndarray
            Brick name assigned according to RA, Dec coordinates.
        'SEED' : int numpy.ndarray
            Random seed used in the template-generating code.
        'MAG': numpy.ndarray
            Apparent magnitude in the SDSS r-band.
        'VDISP': numpy.ndarray
            Velocity dispersion (km/s).
        'SDSS_absmag_r01' : numpy.ndarray
            Absolute SDSS r-band magnitude band-shifted to z=0.1.
        'SDSS_01gr' : numpy.ndarray
            SDSS g-r color band-shifted to z=0.1
        'FILTERNAME': str
            Filter name corresponding to mag (used to normalize the spectra).
        'TRUESPECTYPE': str
            Set to `GALAXY` for this whole sample.
        'TEMPLATETYPE': str
            Set to `BGS` for this whole sample.
        'TEMPLATESUBTYPE': numpy.ndarray
            Not used for now (empty string for all target names).
        'FILES': str list
            List of all mock file(s) read.
        'N_PER_FILE': int list
            Number of mock targets per file.


    """
    import h5py

    mockfile = mock_dir_name
    try:
        os.stat(mockfile)
    except:
        log.fatal('Mock file {} not found!'.format(mockfile))
        raise IOError

    f = h5py.File(mockfile)
    ra  = f['Data/ra'][...].astype('f8') % 360.0
    dec = f['Data/dec'][...].astype('f8')
    zz = f['Data/z_obs'][...].astype('f8')
    rmag = f['Data/app_mag'][...].astype('f8')
    absmag = f['Data/abs_mag'][...].astype('f8')
    gr = f['Data/g_r'][...].astype('f8')
    f.close()

    nobj = len(ra)
    log.info('Read {} objects from {}.'.format(nobj, mockfile))

    if bounds is not None:
        min_ra, max_ra, min_dec, max_dec = bounds
        cut = (ra >= min_ra) * (ra <= max_ra) * (dec >= min_dec) * (dec <= max_dec)
        if np.count_nonzero(cut) == 0:
            log.fatal('No objects in range RA={}, {}, Dec={}, {}!'.format(nobj, min_ra, max_ra, min_dec, max_dec))
            raise ValueError
        ra = ra[cut]
        dec = dec[cut]
        zz = zz[cut]
        rmag = rmag[cut]
        absmag = absmag[cut]
        gr = gr[cut]
        nobj = len(ra)
        log.info('Trimmed to {} objects in range RA={}, {}, Dec={}, {}'.format(nobj, min_ra, max_ra, min_dec, max_dec))

    if magcut is not None:
        cut = rmag < magcut
        if np.count_nonzero(cut) == 0:
            log.fatal('No objects with r < {}!'.format(magcut))
            raise ValueError
        ra = ra[cut]
        dec = dec[cut]
        zz = zz[cut]
        rmag = rmag[cut]
        absmag = absmag[cut]
        gr = gr[cut]
        nobj = len(ra)
        log.info('Trimmed to {} objects with r < {}.'.format(nobj, magcut))

    files = list()
    files.append(mockfile)
    n_per_file = list()
    n_per_file.append(nobj)

    objid = np.arange(nobj, dtype='i8')
    mockid = make_mockid(objid, n_per_file)
    brickname = get_brickname_from_radec(ra, dec, bricksize=bricksize)

    seed = rand.randint(2**32, size=nobj)
    vdisp = _sample_vdisp((1.9, 0.15), nmodel=nobj, rand=rand)

    return {'OBJID': objid, 'MOCKID': mockid, 'RA': ra, 'DEC': dec, 'Z': zz,
            'BRICKNAME': brickname, 'SEED': seed, 'MAG': rmag, 'VDISP': vdisp,
            'SDSS_absmag_r01': absmag, 'SDSS_01gr': gr, 'FILTERNAME': 'sdss2010-r',
            'TRUESPECTYPE': 'GALAXY', 'TEMPLATETYPE': 'BGS', 'TEMPLATESUBTYPE': '',
            'FILES': files, 'N_PER_FILE': n_per_file}

def _load_galaxia_file(mockfile):
    """Multiprocessing support routine for read_galaxia.  Read each individual mock
    galaxia file.

    """
    try:
        os.stat(mockfile)
    except:
        log.fatal('Mock file {} not found!'.format(mockfile))
        raise IOError

    cols = ['RA','DEC','V_HELIO', 'SDSSR_TRUE_NODUST', 'SDSSR_OBS',
            'TEFF', 'LOGG', 'FEH']
    data = fitsio.read(mockfile, ext=1, upper=True, columns=cols)

    ra = data['RA'].astype('f8') % 360.0 # enforce 0 < ra < 360
    dec = data['DEC'].astype('f8')
    zz = (data['V_HELIO'].astype('f4') / C_LIGHT).astype('f4')
    mag = data['SDSSR_TRUE_NODUST'].astype('f4') # SDSS r-band, extinction-corrected
    mag_obs = data['SDSSR_OBS'].astype('f4')     # SDSS r-band, observed
    teff = 10**data['TEFF'].astype('f4')         # log10!
    logg = data['LOGG'].astype('f4')
    feh = data['FEH'].astype('f4')

    return {'OBJID': np.arange(len(ra), dtype='i8'), 'RA': ra, 'DEC': dec,
            'Z': zz, 'MAG': mag, 'MAG_OBS': mag_obs, 'TEFF': teff,
            'LOGG': logg, 'FEH': feh}

def read_galaxia(mock_dir_name, target_name='STAR', rand=None, bricksize=0.25,
                 bounds=None, magcut=None, nproc=1):
    """ Read and concatenate the MWS_MAIN mock files.

    Parameters
    ----------
    mock_dir_name : str
        Complete top-level path to the mock catalogs.
    target_name : str
        Target name (not used; defaults to `STAR`).
    rand : numpy.RandomState
        RandomState object used for the random number generation.
    bricksize : float
        Size of each brick in deg.
    bounds : 4-element tuple
        Restrict the sample to bounds = (min_ra, max_ra, min_dec, max_dec).
    magcut : float
        Magnitude cut to apply to the sample (not used here).
    nproc : int
        Number of cores to use for reading (default 1).

    Returns
    -------
    Dictionary with the following entries.
        'OBJID' : int64 numpy.ndarray
            Object identification number for each file in mock_dir_name.
        'MOCKID': int numpy.ndarray
            Unique mock identification number.
        'RA': numpy.ndarray
            RA positions for the objects in the mock.
        'DEC' : numpy.ndarray
            DEC positions for the objects in the mock.
        'Z' : numpy.ndarray
            Heliocentric radial velocity divided by the speed of light.
        'BRICKNAME' : str numpy.ndarray
            Brick name assigned according to RA, Dec coordinates.
        'SEED' : int numpy.ndarray
            Random seed used in the template-generating code.
        'MAG': numpy.ndarray
            Apparent magnitude (extinction-corrected) in SDSS r-band.
        'MAG_OBS': numpy.ndarray
            Apparent magnitude (including extinction) in SDSS r-band.
        'TEFF': numpy.ndarray
            Effective stellar temperature (K).
        'LOGG': numpy.ndarray
            Surface gravity (cm/s**2).
        'FEH': numpy.ndarray
            Logarithmic iron abundance relative to solar.
        'FILTERNAME': str
            Filter name corresponding to mag (used to normalize the spectra).
        'TRUESPECTYPE': str
            Set to `STAR` for this whole sample.
        'TEMPLATETYPE': str
            Set to `STAR` for this whole sample.
        'TEMPLATESUBTYPE': numpy.ndarray
            Spectral class for each object (e.g., GV) based on the GUMS mock.
        'FILES': str list
            List of all mock file(s) read.
        'N_PER_FILE': int list
            Number of mock targets per file.

    """
    import multiprocessing
    #nproc = max(1, multiprocessing.cpu_count() // 2)

    if False:
        iter_mock_files = iter_files(mock_dir_name, 'allsky', ext='fits')
    else:
        from glob import glob
        log.warning('Temporary hack using glob because I am having problems with iter_files.')
        iter_mock_files = glob(mock_dir_name+'/*/*/*.fits')

    file_list = list(iter_mock_files)
    nfiles = len(iter_mock_files)

    if nfiles == 0:
        log.fatal('Unable to find files in {}'.format(mock_dir_name))
        raise ValueError

    # Multiprocessing parallel I/O, but this fails for galaxia 0.0.2 mocks due
    # to python issue https://bugs.python.org/issue17560 where Pool.map can't
    # return objects with more then 2**32-1 bytes:
    # multiprocessing.pool.MaybeEncodingError: Error sending result: Reason:
    # 'error("'i' format requires -2147483648 <= number <= 2147483647",)'
    # Leaving this code here for the moment in case we fine a workaround

    if False:
        p = multiprocessing.Pool(nproc)
        target_list = p.map(_load_galaxia_file, file_list)
        p.close()
    else:
        target_list = list()
        for mock_file in iter_mock_files:
            target_list.append(_load_galaxia_file(mock_file))

    # Concatenate all the dictionaries into a single dictionary, in an order
    # determined by np.argsort applied to the base name of each path in
    # file_list.
    file_order = np.argsort([os.path.basename(x) for x in file_list])

    log.info('Combining mock files.')
    full_data   = dict()
    if len(target_list) > 0:
        for k in list(target_list[0]): # iterate over keys
            #log.info(' -- {}'.format(k))
            data_list_this_key = list()
            for itarget in file_order: # append all the arrays corresponding to a given key
                data_list_this_key.append(target_list[itarget][k])

            full_data[k] = np.concatenate(data_list_this_key) #consolidate data dictionary

        # Count number of points per file
        k          = list(target_list[0])[0] # pick the first available column
        n_per_file = [len(target_list[itarget][k]) for itarget in file_order]
        ofile_list = [file_list[itarget] for itarget in file_order]

    ra = full_data['RA']
    dec = full_data['DEC']
    zz = full_data['Z']
    mag = full_data['MAG']
    mag_obs = full_data['MAG_OBS']
    objid = full_data['OBJID']
    teff = full_data['TEFF']
    logg = full_data['LOGG']
    feh = full_data['FEH']
    nobj = len(ra)
    log.info('Read {} objects from {} mock files.'.format(nobj, nfiles))

    if bounds is not None:
        min_ra, max_ra, min_dec, max_dec = bounds
        cut = (ra >= min_ra) * (ra <= max_ra) * (dec >= min_dec) * (dec <= max_dec)
        if np.count_nonzero(cut) == 0:
            log.fatal('No objects in range RA={}, {}, Dec={}, {}!'.format(nobj, min_ra, max_ra, min_dec, max_dec))
            raise ValueError
        ra = ra[cut]
        dec = dec[cut]
        zz = zz[cut]
        mag = mag[cut]
        mag_obs = mag_obs[cut]
        objid = objid[cut]
        teff = teff[cut]
        logg = logg[cut]
        feh = feh[cut]
        nobj = len(ra)
        log.info('Trimmed to {} objects in range RA={}, {}, Dec={}, {}'.format(nobj, min_ra, max_ra, min_dec, max_dec))

    if magcut is not None:
        cut = mag < magcut
        if np.count_nonzero(cut) == 0:
            log.fatal('No objects with r < {}!'.format(magcut))
            raise ValueError
        ra = ra[cut]
        dec = dec[cut]
        zz = zz[cut]
        mag = mag[cut]
        mag_obs = mag_obs[cut]
        objid = objid[cut]
        teff = teff[cut]
        logg = logg[cut]
        feh = feh[cut]
        nobj = len(ra)
        log.info('Trimmed to {} objects with r < {}.'.format(nobj, magcut))

    mockid = make_mockid(objid, n_per_file)
    seed = rand.randint(2**32, size=nobj)
    brickname = get_brickname_from_radec(ra, dec, bricksize=bricksize)

    return {'OBJID': objid, 'MOCKID': mockid, 'RA': ra, 'DEC': dec, 'Z': zz,
            'BRICKNAME': brickname, 'SEED': seed, 'MAG': mag, 'TEFF': teff, 'LOGG': logg, 'FEH': feh,
            'MAG_OBS': mag_obs, 'FILTERNAME': 'sdss2010-r',
            'TRUESPECTYPE': 'STAR', 'TEMPLATETYPE': 'STAR', 'TEMPLATESUBTYPE': '',
            'FILES': ofile_list, 'N_PER_FILE': n_per_file}

def _load_lya_file(mockfile):
    """Multiprocessing support routine for read_galaxia.  Reach each individual mock
    Lyman-alpha file.

    """
    try:
        os.stat(mockfile)
    except:
        log.fatal('Mock file {} not found!'.format(mockfile))
        raise IOError

    log.info('Reading {}.'.format(mockfile))
    h = fitsio.FITS(mockfile)
    heads = [head.read_header() for head in h]

    nn = len(heads) - 1 # the first item in heads is empty
    zz = np.zeros(nn).astype('f4')
    ra = np.zeros(nn).astype('f8')
    dec = np.zeros(nn).astype('f8')
    mag_g = np.zeros(nn).astype('f4')

    for ii in range(nn):
        zz[ii] = heads[ii+1]['ZQSO']
        ra[ii] = heads[ii+1]['RA']
        dec[ii] = heads[ii+1]['DEC']
        mag_g[ii] = heads[ii+1]['MAG_G']

    objid = np.arange(len(ra), dtype='i8')
    ra = ra * 180.0 / np.pi
    ra = ra % 360.0 #enforce 0 < ra < 360
    dec = dec * 180.0 / np.pi

    return {'OBJID': objid, 'RA': ra, 'DEC': dec, 'Z': zz, 'MAG_G': mag_g}

def read_lya(mock_dir_name, target_name='QSO', rand=None, bricksize=0.25,
             bounds=None, magcut=None, nproc=1):
    """ Read and concatenate the LYA mock files.

    Parameters
    ----------
    mock_dir_name : str
        Complete top-level path to the mock catalogs.
    target_name : str
        Target name (not used; defaults to `QSO`).
    rand : numpy.RandomState
        RandomState object used for the random number generation.
    bricksize : float
        Size of each brick in deg.
    bounds : 4-element tuple
        Restrict the sample to bounds = (min_ra, max_ra, min_dec, max_dec).
    magcut : float
        Magnitude cut to apply to the sample (not used here).
    nproc : int
        Number of cores to use for reading (default 1).

    Returns
    -------
    Dictionary with the following entries.
        'OBJID' : int64 numpy.ndarray
            Object identification number for each file in mock_dir_name.
        'MOCKID': int numpy.ndarray
            Unique mock identification number.
        'RA': numpy.ndarray
            RA positions for the objects in the mock.
        'DEC' : numpy.ndarray
            DEC positions for the objects in the mock.
        'Z' : numpy.ndarray
            Heliocentric radial velocity divided by the speed of light.
        'BRICKNAME' : str numpy.ndarray
            Brick name assigned according to RA, Dec coordinates.
        'SEED' : int numpy.ndarray
            Random seed used in the template-generating code.
        'MAG': numpy.ndarray
            Apparent magnitude (extinction-corrected) in SDSS r-band.
        'FILTERNAME': str
            Filter name corresponding to mag (used to normalize the spectra).
        'TRUESPECTYPE': str
            Set to `QSO` for this whole sample.
        'TEMPLATETYPE': str
            Set to `QSO` for this whole sample.
        'TEMPLATESUBTYPE': numpy.ndarray
            Spectral class for each object (set to `LYA` for this whole sample).
        'FILES': str list
            List of all mock file(s) read.
        'N_PER_FILE': int list
            Number of mock targets per file.

    """
    import multiprocessing
    #nproc = max(1, multiprocessing.cpu_count() // 2)

    if False:
        iter_mock_files = iter_files(mock_dir_name, '', ext='fits.gz')
    else:
        from glob import glob
        log.warning('Temporary hack using glob because I am having problems with iter_files.')
        iter_mock_files = glob(mock_dir_name+'/*.fits.gz')

    file_list = list(iter_mock_files)
    nfiles = len(iter_mock_files)

    if nfiles == 0:
        log.fatal('Unable to find files in {}'.format(mock_dir_name))
        raise ValueError

    if nproc > 1:
        p = multiprocessing.Pool(nproc)
        target_list = p.map(_load_lya_file, file_list)
        p.close()
    else:
        target_list = list()
        for mock_file in iter_mock_files:
            target_list.append(_load_lya_file(mock_file))

    # Concatenate all the dictionaries into a single dictionary, in an order
    # determined by np.argsort applied to the base name of each path in
    # file_list.
    file_order = np.argsort([os.path.basename(x) for x in file_list])

    log.info('Combining mock files.')
    full_data   = dict()
    if len(target_list) > 0:
        for k in list(target_list[0]):  # iterate over keys
            log.info(' -- {}'.format(k))
            data_list_this_key = list()
            for itarget in file_order:  # append all the arrays corresponding to a given key
                data_list_this_key.append(target_list[itarget][k])

            full_data[k] = np.concatenate(data_list_this_key) # consolidate data dictionary

        # Count number of points per file
        k          = list(target_list[0])[0] # pick the first available column
        n_per_file = [len(target_list[itarget][k]) for itarget in file_order]
        ofile_list = [file_list[itarget] for itarget in file_order]
        #bb = [file_list[itarget] for itarget in file_order]

    objid = full_data['OBJID']
    ra = full_data['RA']
    dec = full_data['DEC']
    zz = full_data['Z']
    mag_g = full_data['MAG_G']
    nobj = len(ra)
    log.info('Read {} objects from {} mock files.'.format(nobj, nfiles))

    mockid = make_mockid(objid, n_per_file)

    if bounds is not None:
        min_ra, max_ra, min_dec, max_dec = bounds
        cut = (ra >= min_ra) * (ra <= max_ra) * (dec >= min_dec) * (dec <= max_dec)
        if np.count_nonzero(cut) == 0:
            log.fatal('No objects in range RA={}, {}, Dec={}, {}!'.format(nobj, min_ra, max_ra, min_dec, max_dec))
            raise ValueError
        objid = objid[cut]
        mockid = mockid[cut]
        ra = ra[cut]
        dec = dec[cut]
        zz = zz[cut]
        mag_g = mag_g[cut]
        nobj = len(ra)
        log.info('Trimmed to {} objects in range RA={}, {}, Dec={}, {}'.format(nobj, min_ra, max_ra, min_dec, max_dec))

    seed = rand.randint(2**32, size=nobj)
    brickname = get_brickname_from_radec(ra, dec, bricksize=bricksize)

    # Sample from the GMM to get magnitudes and colors.
    #log.info('Sampling from Gaussian mixture model.')
    #GMM = SampleGMM(random_state=rand)
    #mags = GMM.sample(target_name, nobj) # [g, r, z, w1, w2, w3, w4]

    return {'OBJID': objid, 'MOCKID': mockid, 'RA': ra, 'DEC': dec, 'Z': zz,
            'BRICKNAME': brickname, 'SEED': seed, 'FILTERNAME': 'sdss2010-g',
            'TRUESPECTYPE': 'QSO', 'TEMPLATETYPE': 'QSO', 'TEMPLATESUBTYPE': 'LYA',
            'MAG': mag_g, 'FILES': ofile_list, 'N_PER_FILE': n_per_file}

def read_mock_durham(core_filename, photo_filename):
    """Read stuff.

    Args:
        core_filename: filename of the hdf5 file storing core lightconedata
        photo_filename: filename of the hdf5 storing photometric data

    Returns:
        objects: ndarray with the structure required to go through
        desitarget.cuts.select_targets()

    """
    import h5py

    fin_core = h5py.File(core_filename, "r")
    fin_mags = h5py.File(photo_filename, "r")

    core_data = fin_core.require_group('/Data')
    photo_data = fin_mags.require_group('/Data')


    gal_id_string = core_data['GalaxyID'].value # these are string values, not integers!

    n_gals = 0
    n_gals = core_data['ra'].size

    #the mock has to be converted in order to create the following columns
    columns = [
        'BRICKID', 'BRICKNAME', 'OBJID', 'BRICK_PRIMARY', 'TYPE',
        'RA', 'RA_IVAR', 'DEC', 'DEC_IVAR',
        'DECAM_FLUX', 'DECAM_MW_TRANSMISSION',
        'WISE_FLUX', 'WISE_MW_TRANSMISSION',
        'SHAPEDEV_R', 'SHAPEEXP_R',
        ]


    obj_id = np.arange(n_gals)
    brickid = np.ones(n_gals, dtype='int64')
    shapedev_r  = np.zeros(n_gals)
    shapeexp_r = np.zeros(n_gals)
    wise_mw_transmission = np.ones((n_gals,4))
    decam_mw_transmission = np.ones((n_gals,6))
    brick_primary = np.ones(n_gals, dtype=bool)
    morpho_type = np.chararray(n_gals, itemsize=3)
    morpho_type[:] = 'EXP'
    brick_name = np.chararray(n_gals, itemsize=8)
    brick_name[:] = '0durham0'

    ra = core_data['ra'].value
    dec = core_data['dec'].value
    dec_ivar = 1.0E10 * np.ones(n_gals)
    ra_ivar = 1.0E10 * np.ones(n_gals)

    wise_flux = np.zeros((n_gals,4))
    decam_flux = np.zeros((n_gals,6))

    g_mags = photo_data['appDgo_tot_ext'].value
    r_mags = photo_data['appDro_tot_ext'].value
    z_mags = photo_data['appDzo_tot_ext'].value

    decam_flux[:,1] = 10**((22.5 - g_mags)/2.5)
    decam_flux[:,2] = 10**((22.5 - r_mags)/2.5)
    decam_flux[:,4] = 10**((22.5 - z_mags)/2.5)

    #this corresponds to the return type of read_tractor() using DECaLS DR1 tractor data.
    type_table = [
        ('BRICKID', '>i4'),
        ('BRICKNAME', '|S8'),
        ('OBJID', '>i4'),
        ('BRICK_PRIMARY', '|b1'),
        ('TYPE', '|S4'),
        ('RA', '>f8'),
        ('RA_IVAR', '>f4'),
        ('DEC', '>f8'),
        ('DEC_IVAR', '>f4'),
        ('DECAM_FLUX', '>f4', (6,)),
        ('DECAM_MW_TRANSMISSION', '>f4', (6,)),
        ('WISE_FLUX', '>f4', (4,)),
        ('WISE_MW_TRANSMISSION', '>f4', (4,)),
        ('SHAPEEXP_R', '>f4'),
        ('SHAPEDEV_R', '>f4')
    ]
    data = np.ndarray(shape=(n_gals), dtype=type_table)
    data['BRICKID'] = brickid
    data['BRICKNAME'] = brick_name
    data['OBJID'] = obj_id
    data['BRICK_PRIMARY'] = brick_primary
    data['TYPE'] = morpho_type
    data['RA'] = ra
    data['RA_IVAR'] = ra_ivar
    data['DEC'] = dec
    data['DEC_IVAR'] = dec_ivar
    data['DECAM_FLUX'] = decam_flux
    data['DECAM_MW_TRANSMISSION'] = decam_mw_transmission
    data['WISE_FLUX'] = wise_flux
    data['WISE_MW_TRANSMISSION'] = wise_mw_transmission
    data['SHAPEEXP_R'] = shapeexp_r
    data['SHAPEDEV_R'] = shapedev_r

    return data
