'''module for covariance matrix computation'''

import logging
import time
from datetime import timedelta
from itertools import combinations_with_replacement
import numpy as np
import healpy as hp

from ._kmeans_radec import kmeans_sample

logger = logging.getLogger(__name__)


class SampleCovariance(np.ndarray):
    '''array subclass for iterative sample covariance matrix computation'''

    def __new__(cls, nrows, ncols=None):
        if ncols is None:
            ncols = nrows
        cov = np.zeros((nrows, ncols)).view(cls)
        cov.sample_count = 0
        cov.sample_row_mean = np.zeros(nrows)
        cov.sample_col_mean = np.zeros(ncols)
        return cov

    def __array_finalize__(self, cov):
        if cov is None:
            return
        nrows, ncols = np.shape(cov)
        self.sample_count = getattr(cov, 'sample_count', 0)
        self.sample_row_mean = np.zeros(nrows)
        self.sample_col_mean = np.zeros(ncols)
        self.sample_row_mean[:] = getattr(cov, 'sample_row_mean', 0.)
        self.sample_col_mean[:] = getattr(cov, 'sample_col_mean', 0.)


def add_sample(cov, x, y=None):
    '''add a sample to a sample covariance matrix'''

    x = np.reshape(x, -1)
    if y is None:
        y = x
    else:
        y = np.reshape(y, -1)

    if x.size != cov.sample_row_mean.size or y.size != cov.sample_col_mean.size:
        raise ValueError('size mismatch between sample and covariance matrix')

    delta = x - cov.sample_row_mean
    cov.sample_count += 1
    cov.sample_row_mean += delta/cov.sample_count
    cov.sample_col_mean += (y - cov.sample_col_mean)/cov.sample_count
    if cov.sample_count > 1:
        cov += (np.outer(delta, y - cov.sample_col_mean) - cov)/(cov.sample_count - 1)


def update_covariance(cov, sample):
    '''update a set of sample covariances given a sample'''

    logger.info('updating covariances for %d item(s)', len(sample))
    t = time.monotonic()

    for (k1, v1), (k2, v2) in combinations_with_replacement(sample.items(), 2):
        if (k1, k2) not in cov:
            nrows, ncols = np.size(v1), np.size(v2)
            logger.info('creating %d x %d covariance matrix for %s, %s', nrows, ncols, k1, k2)
            cov[k1, k2] = SampleCovariance(nrows, ncols)
        logger.info('updating covariance for %s, %s', k1, k2)
        add_sample(cov[k1, k2], v1, v2)

    logger.info('updated %d covariance(s) in %s', len(sample)*(len(sample)+1)//2, timedelta(seconds=(time.monotonic() - t)))


def jackknife_regions_kmeans(fpmap, n, *, maxrepeat=5, maxiter=1000, tol=1e-5, return_centers=False):
    '''partition a footprint map into n regions using k-means'''

    nside = hp.get_nside(fpmap)
    npix = hp.nside2npix(nside)

    logger.info('partitioning map with NSIDE=%s into %s regions', nside, n)
    t = time.monotonic()

    logger.info('finding all nonzero pixels in map')

    ipix = np.nonzero(fpmap)[0]

    logger.info('found %d nonzero pixels in map', len(ipix))
    logger.info('getting angles of all nonzero pixels in map')

    radec = np.transpose(hp.pix2ang(nside, ipix, lonlat=True))

    for r in range(maxrepeat+1):
        logger.info('constructing %s regions using k-means%s', n, '' if r == 0 else f' (repeat {r})')

        km = kmeans_sample(radec, n, verbose=0)

        if km.converged:
            logger.info('k-means converged')
            break
        else:
            logger.info('k-means not converged; repeat')
    else:
        raise RuntimeError(f'k-means failed to partition map into {n} regions after repeat {maxrepeat}')

    areas = 60**4//100/np.pi/npix*np.bincount(km.labels)
    area_mean, area_std, area_unit = np.mean(areas), np.std(areas), 'deg2'
    if area_mean < 1.:
        area_mean, area_std, area_unit = area_mean/3600, area_std/3600, 'arcmin2'
    if area_mean < 1.:
        area_mean, area_std, area_unit = area_mean/3600, area_std/3600, 'arcsec2'
    logger.info('region area is %.3f ± %.3f %s', area_mean, area_std, area_unit)

    jkmap = np.zeros(npix, dtype=int)
    jkmap[ipix] = km.labels + 1

    logger.info('partitioned map in %s', timedelta(seconds=(time.monotonic() - t)))

    if return_centers:
        result = jkmap, km.centers
    else:
        result = jkmap

    return result
