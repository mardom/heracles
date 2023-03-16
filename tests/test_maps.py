import numpy as np
import healpy as hp
import pytest

from .conftest import warns


def map_catalog(m, catalog):
    g = m(catalog)
    g.send(None)
    for page in catalog:
        g.send(page)
    try:
        g.throw(GeneratorExit)
    except StopIteration as e:
        return e.value
    else:
        return None


@pytest.fixture
def nside():
    return 64


@pytest.fixture
def sigma_e():
    return 0.1


@pytest.fixture
def vmap(nside):
    return np.round(np.random.rand(12*nside**2))


@pytest.fixture
def page(nside):
    from unittest.mock import Mock

    ipix = np.ravel(4*hp.ring2nest(nside, np.arange(12*nside**2))[:, np.newaxis] + [0, 1, 2, 3])

    ra, dec = hp.pix2ang(nside*2, ipix, nest=True, lonlat=True)

    size = ra.size

    w = np.random.rand(size//4, 4)
    g1 = np.random.randn(size//4, 4)
    g2 = np.random.randn(size//4, 4)
    g1 -= np.sum(w*g1, axis=-1, keepdims=True)/np.sum(w, axis=-1, keepdims=True)
    g2 -= np.sum(w*g2, axis=-1, keepdims=True)/np.sum(w, axis=-1, keepdims=True)
    w, g1, g2 = w.reshape(-1), g1.reshape(-1), g2.reshape(-1)

    cols = {'ra': ra, 'dec': dec, 'g1': g1, 'g2': g2, 'w': w}

    def get(*names):
        if len(names) == 1:
            return cols[names[0]]
        else:
            return [cols[name] for name in names]

    page = Mock()
    page.size = size
    page.get = get
    page.__getitem__ = lambda self, *names: get(*names)

    return page


@pytest.fixture
def catalog(page):

    from unittest.mock import Mock

    catalog = Mock()
    catalog.visibility = None
    catalog.__iter__ = lambda self: iter([page])

    return catalog


def test_visibility_map(nside, vmap):

    from unittest.mock import Mock
    from le3_pk_wl.maps import VisibilityMap

    fsky = vmap.mean()

    for nside_out in [nside//2, nside, nside*2]:
        catalog = Mock()
        catalog.visibility = vmap

        mapper = VisibilityMap(nside_out)

        with warns(UserWarning if nside != nside_out else None):
            result = mapper(catalog)

        assert result is not vmap

        assert result.shape == (12*nside_out**2,)
        assert result.dtype.metadata == {'spin': 0, 'kernel': 'healpix', 'power': 0}
        assert np.isclose(result.mean(), fsky)

    # test missing visibility map
    catalog = Mock()
    catalog.visibility = None
    mapper = VisibilityMap(nside)
    with pytest.raises(ValueError, match='no visibility'):
        mapper(catalog)


def test_position_map(nside, catalog, vmap):

    from le3_pk_wl.maps import PositionMap

    # normal mode: compute overdensity maps with metadata

    m = map_catalog(PositionMap(nside, 'ra', 'dec'), catalog)

    assert m.shape == (12*nside**2,)
    assert m.dtype.metadata == {'spin': 0, 'nbar': 4., 'kernel': 'healpix', 'power': 0}
    np.testing.assert_array_equal(m, 0)

    # compute number count map

    m = map_catalog(PositionMap(nside, 'ra', 'dec', overdensity=False), catalog)

    assert m.shape == (12*nside**2,)
    assert m.dtype.metadata == {'spin': 0, 'nbar': 4., 'kernel': 'healpix', 'power': 1}
    np.testing.assert_array_equal(m, 4)

    # compute overdensity maps with visibility map

    catalog.visibility = vmap

    m = map_catalog(PositionMap(nside, 'ra', 'dec'), catalog)

    assert m.shape == (12*nside**2,)
    assert m.dtype.metadata == {'spin': 0, 'nbar': 4./vmap.mean(), 'kernel': 'healpix', 'power': 0}

    # compute number count map with visibility map

    m = map_catalog(PositionMap(nside, 'ra', 'dec', overdensity=False), catalog)

    assert m.shape == (12*nside**2,)
    assert m.dtype.metadata == {'spin': 0, 'nbar': 4./vmap.mean(), 'kernel': 'healpix', 'power': 1}


def test_scalar_map(nside, catalog):

    from le3_pk_wl.maps import ScalarMap

    m = map_catalog(ScalarMap(nside, 'ra', 'dec', 'g1', 'w'), catalog)

    w = next(iter(catalog))['w']
    w = w.reshape(w.size//4, 4).sum(axis=-1)
    wbar = w.mean()

    assert m.shape == (12*nside**2,)
    assert m.dtype.metadata == {'spin': 0, 'wbar': wbar, 'kernel': 'healpix', 'power': 0}
    np.testing.assert_array_almost_equal(m, 0)

    m = map_catalog(ScalarMap(nside, 'ra', 'dec', 'g1', 'w', normalize=False), catalog)

    assert m.shape == (12*nside**2,)
    assert m.dtype.metadata == {'spin': 0, 'wbar': wbar, 'kernel': 'healpix', 'power': 1}
    np.testing.assert_array_almost_equal(m, 0)


def test_complex_map(nside, catalog):

    from le3_pk_wl.maps import ComplexMap

    m = map_catalog(ComplexMap(nside, 'ra', 'dec', 'g1', 'g2', 'w', spin=2), catalog)

    w = next(iter(catalog))['w']
    w = w.reshape(w.size//4, 4).sum(axis=-1)
    wbar = w.mean()

    assert m.shape == (2, 12*nside**2,)
    assert m.dtype.metadata == {'spin': 2, 'wbar': wbar, 'kernel': 'healpix', 'power': 0}
    np.testing.assert_array_almost_equal(m, 0)

    m = map_catalog(ComplexMap(nside, 'ra', 'dec', 'g1', 'g2', 'w', spin=1, normalize=False), catalog)

    assert m.shape == (2, 12*nside**2,)
    assert m.dtype.metadata == {'spin': 1, 'wbar': wbar, 'kernel': 'healpix', 'power': 1}
    np.testing.assert_array_almost_equal(m, 0)


def test_weight_map(nside, catalog):

    from le3_pk_wl.maps import WeightMap

    m = map_catalog(WeightMap(nside, 'ra', 'dec', 'w'), catalog)

    w = next(iter(catalog))['w']
    w = w.reshape(w.size//4, 4).sum(axis=-1)
    wbar = w.mean()

    assert m.shape == (12*nside**2,)
    assert m.dtype.metadata == {'spin': 0, 'wbar': wbar, 'kernel': 'healpix', 'power': 0}
    np.testing.assert_array_almost_equal(m, w/wbar)

    m = map_catalog(WeightMap(nside, 'ra', 'dec', 'w', normalize=False), catalog)

    assert m.shape == (12*nside**2,)
    assert m.dtype.metadata == {'spin': 0, 'wbar': wbar, 'kernel': 'healpix', 'power': 1}
    np.testing.assert_array_almost_equal(m, w)


def test_transform_maps():

    from le3_pk_wl.maps import transform_maps, update_metadata

    nside = 32
    npix = 12*nside**2

    t = np.random.randn(npix)
    update_metadata(t, spin=0, a=1)
    p = np.random.randn(2, npix)
    update_metadata(p, spin=2, b=2)

    # single scalar map
    maps = {('T', 0): t}
    alms = transform_maps(maps)

    assert len(alms) == 1
    assert alms.keys() == maps.keys()
    assert alms['T', 0].dtype.metadata['spin'] == 0
    assert alms['T', 0].dtype.metadata['a'] == 1
    assert alms['T', 0].dtype.metadata['nside'] == nside

    # polarisation map
    maps = {('P', 0): p}
    alms = transform_maps(maps)

    assert len(alms) == 2
    assert alms.keys() == {('E', 0), ('B', 0)}
    assert alms['E', 0].dtype.metadata['spin'] == 2
    assert alms['B', 0].dtype.metadata['spin'] == 2
    assert alms['E', 0].dtype.metadata['b'] == 2
    assert alms['B', 0].dtype.metadata['b'] == 2
    assert alms['E', 0].dtype.metadata['nside'] == nside
    assert alms['B', 0].dtype.metadata['nside'] == nside

    # mixed
    maps = {('T', 0): t, ('P', 1): p}
    alms = transform_maps(maps)

    assert len(alms) == 3
    assert alms.keys() == {('T', 0), ('E', 1), ('B', 1)}
    assert alms['T', 0].dtype.metadata['spin'] == 0
    assert alms['E', 1].dtype.metadata['spin'] == 2
    assert alms['B', 1].dtype.metadata['spin'] == 2
    assert alms['T', 0].dtype.metadata['a'] == 1
    assert alms['E', 1].dtype.metadata['b'] == 2
    assert alms['B', 1].dtype.metadata['b'] == 2
    assert alms['T', 0].dtype.metadata['nside'] == nside
    assert alms['E', 1].dtype.metadata['nside'] == nside
    assert alms['B', 1].dtype.metadata['nside'] == nside


def test_update_metadata():
    from le3_pk_wl.maps import update_metadata

    a = np.empty(0)

    assert a.dtype.metadata is None

    update_metadata(a, x=1)

    assert a.dtype.metadata == {'x': 1}

    update_metadata(a, y=2)

    assert a.dtype.metadata == {'x': 1, 'y': 2}


class MockMap:

    def __init__(self):
        self.args = []
        self.return_value = object()

    def __call__(self, catalog):
        self.args.append(catalog)
        return self.return_value

    def assert_called_with(self, value):
        assert self.args[-1] is value

    def assert_any_call(self, value):
        assert value in self.args


class MockMapGen(MockMap):

    def __call__(self, catalog):
        while True:
            try:
                yield
            except GeneratorExit:
                break
        return super().__call__(catalog)


class MockCatalog:
    def __iter__(self):
        yield {}


@pytest.mark.parametrize('Map', [MockMap, MockMapGen])
def test_map_catalogs(Map, nside):

    from itertools import product
    from le3_pk_wl.maps import map_catalogs

    test_maps = [
        Map(),
        [Map(), Map(), Map()],
        {'a': Map(), 'b': Map(), 'z': Map()},
    ]

    test_catalogs = [
        MockCatalog(),
        [MockCatalog(), MockCatalog()],
        {'x': MockCatalog(), 'y': MockCatalog()},
    ]

    for maps, catalogs in product(test_maps, test_catalogs):

        data = map_catalogs(maps, catalogs)

        if isinstance(maps, list):

            if isinstance(catalogs, list):
                for k, i in product(range(len(maps)), range(len(catalogs))):
                    maps[k].assert_any_call(catalogs[i])
                    assert data[k, i] is maps[k].return_value

            elif isinstance(catalogs, dict):
                for k, i in product(range(len(maps)), catalogs.keys()):
                    maps[k].assert_any_call(catalogs[i])
                    assert data[k, i] is maps[k].return_value

            else:
                for k in range(len(maps)):
                    maps[k].assert_called_with(catalogs)
                    assert data[k] is maps[k].return_value

        elif isinstance(maps, dict):

            if isinstance(catalogs, list):
                for k, i in product(maps.keys(), range(len(catalogs))):
                    maps[k].assert_any_call(catalogs[i])
                    assert data[k, i] is maps[k].return_value

            elif isinstance(catalogs, dict):
                for k, i in product(maps.keys(), catalogs.keys()):
                    maps[k].assert_any_call(catalogs[i])
                    assert data[k, i] is maps[k].return_value

            else:
                for k in maps.keys():
                    maps[k].assert_called_with(catalogs)
                    assert data[k] is maps[k].return_value

        else:

            if isinstance(catalogs, list):
                for i in range(len(catalogs)):
                    maps.assert_any_call(catalogs[i])
                    assert data[i] is maps.return_value

            elif isinstance(catalogs, dict):
                for i in catalogs.keys():
                    maps.assert_any_call(catalogs[i])
                    assert data[i] is maps.return_value

            else:
                maps.assert_called_with(catalogs)
                assert data is maps.return_value
