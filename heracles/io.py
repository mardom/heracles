'''module for file reading and writing'''

import os
import logging

import numpy as np
import healpy as hp
import fitsio


logger = logging.getLogger(__name__)


def _write_array(a, name, fits, ext):
    '''write an array to a FITS table column'''

    # write the array as a single column
    fits.write_table([np.reshape(a, -1)], names=[name], extname=ext)

    # write metadata to reconstitute the array later
    fits[ext].write_key(f'{name}AXES', np.ndim(a), f'number of {name} array axes')
    for j, d in enumerate(np.shape(a)):
        fits[ext].write_key(f'{name}AXIS{j}', d, f'axis {j} of {name} array')


def _read_array(hdu, name):
    '''read an array from a FITS table HDU'''

    # read the flattened array
    a = hdu.read(columns=[name])

    # recreate the shape of the array
    h = hdu.read_header()
    d = h[f'{name}AXES']
    s = tuple(h[f'{name}AXIS{j}'] for j in range(d))

    # return the array data in the given shape
    return np.reshape(a[name], s)


def write_binspec(filename, bin_id, seed, query, workdir='.'):
    '''write a bin specification to file'''
    path = os.path.join(workdir, filename)
    with open(path, 'w') as f:
        f.write(f'{bin_id}:{seed}:{query}')


def read_binspec(filename, workdir='.'):
    '''read a bin specification from file'''
    path = os.path.join(workdir, filename)
    with open(path) as f:
        bin_id, seed, query = f.read().split(':', 2)
    return int(bin_id.strip()), int(seed.strip()), query.strip()


def clobber_fits(filename, workdir='.'):
    '''clobber a FITS file'''
    path = os.path.join(workdir, filename)
    with fitsio.FITS(path, 'rw', clobber=True) as fits:
        fits.write(None)


def read_mask(mask_name, nside=None, field=0, extra_mask_name=None):
    '''read visibility map from a HEALPix map file'''
    mask = hp.read_map(mask_name, field=field)

    # set unseen pixels to zero
    unseen = np.where(mask == hp.UNSEEN)
    mask[unseen] = 0

    nside_mask = hp.get_nside(mask)

    if nside is not None:
        # mask is provided at a different resolution
        if nside_mask < nside:
            print('WARNING: Nside of mask < Nside of requested maps')
        if nside_mask != nside:
            mask = hp.ud_grade(mask, nside)
            nside_mask = nside

    # apply extra mask if given
    if extra_mask_name is not None:
        extra_mask = hp.read_map(extra_mask_name)
        nside_extra = hp.get_nside(extra_mask)
        if nside_extra != nside_mask:
            extra_mask = hp.ud_grade(extra_mask, nside_mask)
        mask *= extra_mask

    return mask


def write_header(filename, params=None, clobber=False, workdir='.'):
    '''write the PK-WL metadata to the primary HDU of a FITS file

    If the output file exists, its header will be overwritten, unless the
    ``clobber`` parameter is set to ``True``, in which case the entire file
    will be overwritten.

    '''

    logger.info('writing FITS header: %s', filename)

    # full path to FITS file
    path = os.path.join(workdir, filename)

    # if new or overwriting, create an empty FITS with primary HDU
    if not os.path.isfile(path) or clobber:
        with fitsio.FITS(path, mode='rw', clobber=True) as fits:
            fits.write(None)

    # reopen FITS for writing header
    with fitsio.FITS(path, mode='rw', clobber=False) as fits:

        # write the software metadata
        fits[0].write_key('SOFTNAME', 'LE3_PK_WL', 'software name')
        fits[0].write_key('SOFTVERS', '1.0.0', 'software version')

        # write params if given
        if params is not None:
            fits[0].write_key('NSIDE', params.nside, 'HEALPix map resolution')
            fits[0].write_key('LMIN', params.lmin, 'minimum angular mode number')
            fits[0].write_key('LMAX', params.lmax, 'maximum angular mode number')
            fits[0].write_key('NELLBIN', params.nell_bins, 'number of angular mode bins')
            fits[0].write_key('LOGLIN', ['lin', 'log'][params.linlogspace], 'linear or logarithmic binning')
            fits[0].write_key('NLSAMP', params.nlsamp, 'number of noise realisations')
            fits[0].write_key('NBARCUT', params.nbar_cut, 'cut for estimating mean density')
            fits[0].write_key('SEED', params.seed, 'random seed for noise realisations')

    logger.info('> DONE')


def read_header(filename, workdir='.'):
    '''read the PK-WL parameters from the primary HDU of a FITS file

    Returns an options dictionary.

    '''

    logger.info('reading FITS header: %s', filename)

    # full path to FITS file
    path = os.path.join(workdir, filename)

    # read primary header from FITS
    h = fitsio.read_header(path)

    # dictionary to contain whatever is found in the header
    options = {}

    # read keywords
    if 'NSIDE' in h:
        options['nside'] = h['NSIDE']
    if 'LMIN' in h:
        options['lmin'] = h['LMIN']
    if 'LMAX' in h:
        options['lmax'] = h['LMAX']
    if 'NELLBIN' in h:
        options['nell_bins'] = h['NELLBIN']
    if 'LOGLIN' in h:
        options['linlogspace'] = ['lin', 'log'].index(h['LOGLIN'])
    if 'NLSAMP' in h:
        options['nlsamp'] = h['NLSAMP']
    if 'NBARCUT' in h:
        options['nbar_cut'] = h['NBARCUT']
    if 'SEED' in h:
        options['seed'] = h['SEED']

    logger.info('> DONE')

    # return the dict of options
    return options


def write_maps(filename, maps, *, clobber=False, workdir='.'):
    '''write a set of maps to FITS file

    If the output file exists, the new estimates will be appended, unless the
    ``clobber`` parameter is set to ``True``.

    '''

    logger.info('writing %d maps to %s', len(maps), filename)

    # full path to FITS file
    path = os.path.join(workdir, filename)

    # if new or overwriting, create an empty FITS with primary HDU
    if not os.path.isfile(path) or clobber:
        with fitsio.FITS(path, mode='rw', clobber=True) as fits:
            fits.write(None)

    # reopen FITS for writing data
    with fitsio.FITS(path, mode='rw', clobber=False) as fits:

        # write a new TOC extension if FITS doesn't already contain one
        if 'MAPTOC' not in fits:
            fits.create_table_hdu(names=['EXT', 'NAME', 'BIN'],
                                  formats=['10A', '10A', 'I'],
                                  extname='MAPTOC')

        # get a recarray to write TOC entries with
        tocentry = np.empty(1, dtype=fits['MAPTOC'].get_rec_dtype()[0])

        # get the first free map extension index
        mapn = 0
        while f'MAP{mapn}' in fits:
            mapn += 1

        # write every map
        for (n, i), m in maps.items():
            logger.info('writing %s map for bin %s', n, i)

            # the cl extension name
            ext = f'MAP{mapn}'
            mapn += 1

            # write the data
            fits.write_table([m], names=[n], extname=ext)

            # HEALPix metadata
            npix = np.shape(m)[-1]
            nside = hp.npix2nside(npix)
            fits[ext].write_key('PIXTYPE', 'HEALPIX', 'HEALPIX pixelisation')
            fits[ext].write_key('ORDERING', 'RING', 'Pixel ordering scheme, either RING or NESTED')
            fits[ext].write_key('NSIDE', nside, 'Resolution parameter of HEALPIX')
            fits[ext].write_key('FIRSTPIX', 0, 'First pixel # (0 based)')
            fits[ext].write_key('LASTPIX', npix-1, 'Last pixel # (0 based)')
            fits[ext].write_key('INDXSCHM', 'IMPLICIT', 'Indexing: IMPLICIT or EXPLICIT')
            fits[ext].write_key('OBJECT', 'FULLSKY', 'Sky coverage, either FULLSKY or PARTIAL')

            # write the TOC entry
            tocentry[0] = (ext, n, i)
            fits['MAPTOC'].append(tocentry)

    logger.info('done with %d maps', len(maps))


def read_maps(filename, workdir='.'):
    '''read a set of maps from a FITS file'''

    logger.info('reading maps from %s', filename)

    # full path to FITS file
    path = os.path.join(workdir, filename)

    # the returned set of maps
    maps = {}

    # open the FITS file for reading
    with fitsio.FITS(path) as fits:

        # get the TOC from the FITS file
        fits_toc = fits['MAPTOC'].read()

        # read every entry in the TOC, add it to the list, then read the maps
        for entry in fits_toc:
            ext, n, i = entry[['EXT', 'NAME', 'BIN']]

            logger.info('reading %s map for bin %s', n, i)

            # read the map from the extension
            m = fits[ext].read()

            # store in set of maps
            maps[n, i] = m[n]

    logger.info('done with %d maps', len(maps))

    # return the dictionary of maps
    return maps


def write_alms(filename, alms, *, clobber=False, workdir='.'):
    '''write a set of alms to FITS file

    If the output file exists, the new estimates will be appended, unless the
    ``clobber`` parameter is set to ``True``.

    '''

    logger.info('writing %d alms to %s', len(alms), filename)

    # full path to FITS file
    path = os.path.join(workdir, filename)

    # if new or overwriting, create an empty FITS with primary HDU
    if not os.path.isfile(path) or clobber:
        with fitsio.FITS(path, mode='rw', clobber=True) as fits:
            fits.write(None)

    # reopen FITS for writing data
    with fitsio.FITS(path, mode='rw', clobber=False) as fits:

        # write a new TOC extension if FITS doesn't already contain one
        if 'ALMTOC' not in fits:
            fits.create_table_hdu(names=['EXT', 'NAME', 'BIN'],
                                  formats=['10A', '10A', 'I'],
                                  extname='ALMTOC')

        # get a recarray to write TOC entries with
        tocentry = np.empty(1, dtype=fits['ALMTOC'].get_rec_dtype()[0])

        # get the first free alm extension index
        almn = 0
        while f'ALM{almn}' in fits:
            almn += 1

        # write every alm
        for (n, i), alm in alms.items():
            logger.info('writing %s alm for bin %s', n, i)

            # the cl extension name
            ext = f'ALM{almn}'
            almn += 1

            # write the data
            fits.write_table([alm.real, alm.imag], names=['real', 'imag'], extname=ext)

            # write the TOC entry
            tocentry[0] = (ext, n, i)
            fits['ALMTOC'].append(tocentry)

    logger.info('done with %d alms', len(alms))


def read_alms(filename, workdir='.'):
    '''read a set of alms from a FITS file'''

    logger.info('reading alms from %s', filename)

    # full path to FITS file
    path = os.path.join(workdir, filename)

    # the returned set of alms
    alms = {}

    # open the FITS file for reading
    with fitsio.FITS(path) as fits:

        # get the TOC from the FITS file
        fits_toc = fits['ALMTOC'].read()

        # read every entry in the TOC, add it to the list, then read the alms
        for entry in fits_toc:
            ext, n, i = entry[['EXT', 'NAME', 'BIN']]

            logger.info('reading %s alm for bin %s', n, i)

            # read the alm from the extension
            raw = fits[ext].read()
            alm = np.empty(len(raw), dtype=complex)
            alm.real = raw['real']
            alm.imag = raw['imag']
            del raw

            # store in set of alms
            alms[n, i] = alm

    logger.info('done with %d alms', len(alms))

    # return the dictionary of alms
    return alms


def write_cls(filename, cls, *, clobber=False, workdir='.'):
    '''write a set of cls to FITS file

    If the output file exists, the new estimates will be appended, unless the
    ``clobber`` parameter is set to ``True``.

    '''

    logger.info('writing %d cls to %s', len(cls), filename)

    # full path to FITS file
    path = os.path.join(workdir, filename)

    # if new or overwriting, create an empty FITS with primary HDU
    if not os.path.isfile(path) or clobber:
        with fitsio.FITS(path, mode='rw', clobber=True) as fits:
            fits.write(None)

    # reopen FITS for writing data
    with fitsio.FITS(path, mode='rw', clobber=False) as fits:

        # write a new TOC extension if FITS doesn't already contain one
        if 'CLTOC' not in fits:
            fits.create_table_hdu(names=['EXT', 'NAME', 'BIN1', 'BIN2'],
                                  formats=['10A', '10A', 'I', 'I'],
                                  extname='CLTOC')

        # get a recarray to write TOC entries with
        tocentry = np.empty(1, dtype=fits['CLTOC'].get_rec_dtype()[0])

        # get the first free cl extension index
        cln = 0
        while f'CL{cln}' in fits:
            cln += 1

        # write every cl
        for (n, i1, i2), cl in cls.items():
            logger.info('writing %s cl for bins %s, %s', n, i1, i2)

            # the cl extension name
            ext = f'CL{cln}'
            cln += 1

            # write the data column
            _write_array(cl, 'CL', fits, ext)

            # write the TOC entry
            tocentry[0] = (ext, n, i1, i2)
            fits['CLTOC'].append(tocentry)

    logger.info('done with %d cls', len(cls))


def read_cls(filename, workdir='.'):
    '''read a set of cls from a FITS file'''

    logger.info('reading cls from %s', filename)

    # full path to FITS file
    path = os.path.join(workdir, filename)

    # the returned set of cls
    cls = {}

    # open the FITS file for reading
    with fitsio.FITS(path) as fits:

        # get the TOC from the FITS file
        fits_toc = fits['CLTOC'].read()

        # read every entry in the TOC, add it to the list, then read the cls
        for entry in fits_toc:
            ext, n, i1, i2 = entry[['EXT', 'NAME', 'BIN1', 'BIN2']]

            logger.info('reading %s cl for bins %s, %s', n, i1, i2)

            # read the cl from the extension
            cls[n, i1, i2] = _read_array(fits[ext], 'CL')

    logger.info('done with %d cls', len(cls))

    # return the dictionary of cls
    return cls


def write_mms(filename, mms, *, clobber=False, workdir='.'):
    '''write a set of mixing matrices to FITS file

    If the output file exists, the new mixing matrices will be appended, unless
    the ``clobber`` parameter is set to ``True``.

    '''

    logger.info('writing %d mm(s) to %s', len(mms), filename)

    # full path to FITS file
    path = os.path.join(workdir, filename)

    # if new or overwriting, create an empty FITS with primary HDU
    if not os.path.isfile(path) or clobber:
        with fitsio.FITS(path, mode='rw', clobber=True) as fits:
            fits.write(None)

    # reopen FITS for writing data
    with fitsio.FITS(path, mode='rw', clobber=False) as fits:

        # write a new TOC extension if FITS doesn't already contain one
        if 'MMTOC' not in fits:
            fits.create_table_hdu(names=['EXT', 'NAME', 'BIN1', 'BIN2'],
                                  formats=['10A', '10A', 'I', 'I'],
                                  extname='MMTOC')

        # get a recarray to write TOC entries with
        tocentry = np.empty(1, dtype=fits['MMTOC'].get_rec_dtype()[0])

        # get the first free mm extension index
        mmn = 0
        while f'MM{mmn}' in fits:
            mmn += 1

        # write every mixing matrix
        for (n, i1, i2), mm in mms.items():
            logger.info('writing mixing matrix %s for bins %s, %s', n, i1, i2)

            # the mm extension name
            ext = f'MM{mmn}'
            mmn += 1

            # write the mixing matrix as a table column
            _write_array(mm, 'MM', fits, ext)

            # write the TOC entry
            tocentry[0] = (ext, n, i1, i2)
            fits['MMTOC'].append(tocentry)

    logger.info('done with %d mm(s)', len(mms))


def read_mms(filename, workdir='.'):
    '''read a set of mixing matrices from a FITS file'''

    logger.info('reading mixing matrices from %s', filename)

    # full path to FITS file
    path = os.path.join(workdir, filename)

    # the returned set of mms
    mms = {}

    # open the FITS file for reading
    with fitsio.FITS(path) as fits:

        # get the TOC from the FITS file
        fits_toc = fits['MMTOC'].read()

        # read every entry in the TOC, add it to the list, then read the mms
        for entry in fits_toc:
            ext, n, i1, i2 = entry[['EXT', 'NAME', 'BIN1', 'BIN2']]

            logger.info('reading mixing matrix %s for bins %s, %s', n, i1, i2)

            # read the mixing matrix from the extension
            mms[n, i1, i2] = _read_array(fits[ext], 'MM')

    logger.info('done with %d mm(s)', len(mms))

    # return the dictionary of mms
    return mms


def write_cov(filename, cov, clobber=False, workdir='.'):
    '''write a set of covariance matrices to FITS file

    If the output file exists, the new estimates will be appended, unless the
    ``clobber`` parameter is set to ``True``.

    '''

    logger.info('writing %d covariances to %s', len(cov), filename)

    # full path to FITS file
    path = os.path.join(workdir, filename)

    # if new or overwriting, create an empty FITS with primary HDU
    if not os.path.isfile(path) or clobber:
        with fitsio.FITS(path, mode='rw', clobber=True) as fits:
            fits.write(None)

    # reopen FITS for writing data
    with fitsio.FITS(path, mode='rw', clobber=False) as fits:

        # write a new TOC extension if FITS doesn't already contain one
        if 'COVTOC' not in fits:
            fits.create_table_hdu(names=['EXT', 'NAME_1', 'BIN1_1', 'BIN2_1', 'NAME_2', 'BIN1_2', 'BIN2_2'],
                                  formats=['10A', '10A', 'I', 'I', '10A', 'I', 'I'],
                                  extname='COVTOC')

        # get a recarray to write TOC entries with
        tocentry = np.empty(1, dtype=fits['COVTOC'].get_rec_dtype()[0])

        # get the first free cov extension index
        extn = 0
        while f'COV{extn}' in fits:
            extn += 1

        # write every covariance sub-matrix
        for (k1, k2), mat in cov.items():
            # the cl extension name
            ext = f'COV{extn}'
            extn += 1

            logger.info('writing %s x %s covariance matrix', k1, k2)

            # write the data
            _write_array(mat, 'COV', fits, ext)

            # write the TOC entry
            tocentry[0] = (ext, *k1, *k2)
            fits['COVTOC'].append(tocentry)

    logger.info('done with %d covariance(s)', len(cov))


def read_cov(filename, workdir='.'):
    '''read a set of covariances matrices from a FITS file'''

    logger.info('reading covariance matrices from %s', filename)

    # full path to FITS file
    path = os.path.join(workdir, filename)

    # the returned set of covariances
    cov = {}

    # open the FITS file for reading
    with fitsio.FITS(path) as fits:

        # get the TOC from the FITS file
        fits_toc = fits['COVTOC'].read()

        # read every entry in the TOC, add it to the list, then read the data
        for entry in fits_toc:
            ext = entry['EXT']
            k1 = tuple(entry[['NAME_1', 'BIN1_1', 'BIN2_1']])
            k2 = tuple(entry[['NAME_2', 'BIN1_2', 'BIN2_2']])

            logger.info('reading %s x %s covariance matrix', k1, k2)

            # read the mixing matrix from the extension
            cov[k1, k2] = _read_array(fits[ext], 'COV')

    logger.info('done with %d covariance(s)', len(cov))

    # return the toc dict of covariances
    return cov
