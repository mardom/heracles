from unittest.mock import Mock, call, patch

import numpy as np
import pytest


@pytest.fixture
def nside():
    return 32


@pytest.fixture
def zbins():
    return {0: (0.0, 0.8), 1: (1.0, 1.2)}


@pytest.fixture
def mock_alms(rng, zbins):
    import numpy as np

    lmax = 32

    Nlm = (lmax + 1) * (lmax + 2) // 2

    # names and spins
    fields = {"P": 0, "G": 2}

    alms = {}
    for n, s in fields.items():
        shape = (Nlm, 2) if s == 0 else (2, Nlm, 2)
        for i in zbins:
            a = rng.standard_normal(shape) @ [1, 1j]
            a.dtype = np.dtype(a.dtype, metadata={"nside": 32, "spin": s})
            alms[n, i] = a

    return alms


def test_alm2lmax(rng):
    import healpy as hp

    from heracles.twopoint import alm2lmax

    for lmax in rng.choice(1000, size=100):
        alm = np.zeros(hp.Alm.getsize(lmax), dtype=complex)
        assert alm2lmax(alm) == lmax


def test_alm2cl(mock_alms):
    from itertools import combinations_with_replacement

    import healpy as hp

    from heracles.twopoint import alm2cl

    for alm, alm2 in combinations_with_replacement(mock_alms.values(), 2):
        cl = alm2cl(alm, alm2)
        expected = np.empty_like(cl)
        for i in np.ndindex(*alm.shape[:-1]):
            for j in np.ndindex(*alm2.shape[:-1]):
                expected[i + j] = hp.alm2cl(alm[i], alm2[j])
        np.testing.assert_allclose(cl, expected)


def test_alm2cl_unequal_size(rng):
    import healpy as hp

    from heracles.twopoint import alm2cl

    lmax1 = 10
    lmax2 = 20

    alm = rng.standard_normal(((lmax1 + 1) * (lmax1 + 2) // 2, 2)) @ [1, 1j]
    alm2 = rng.standard_normal(((lmax2 + 1) * (lmax2 + 2) // 2, 2)) @ [1, 1j]

    alm21 = np.zeros_like(alm)
    for ell in range(lmax1 + 1):
        for m in range(ell + 1):
            alm21[hp.Alm.getidx(lmax1, ell, m)] = alm2[hp.Alm.getidx(lmax2, ell, m)]

    cl = alm2cl(alm, alm2)
    np.testing.assert_allclose(cl, hp.alm2cl(alm, alm21))

    cl = alm2cl(alm, alm2, lmax=lmax2)
    np.testing.assert_allclose(cl, hp.alm2cl(alm, alm21, lmax_out=lmax2))


def test_almkeys():
    from heracles.twopoint import _almkeys

    dtype = np.dtype(complex)
    spin2_dtype = np.dtype(complex, metadata={"spin": 2})

    alms = {
        ("A", 1): np.zeros((), dtype=dtype),
        ("B", 2): np.zeros((2,), dtype=dtype),
        ("C", 3): np.zeros((2, 10), dtype=dtype),
        ("D", 4): np.zeros((2, 3, 10), dtype=dtype),
        ("E", 5): np.zeros((2, 10), dtype=spin2_dtype),
        ("F", 6): np.zeros((2, 3, 10), dtype=spin2_dtype),
    }

    keys = list(_almkeys(alms))

    assert keys == [
        ("A", 1),
        ("B", 2),
        ("C_0", 3),
        ("C_1", 3),
        ("D_0_0", 4),
        ("D_0_1", 4),
        ("D_0_2", 4),
        ("D_1_0", 4),
        ("D_1_1", 4),
        ("D_1_2", 4),
        ("E_E", 5),
        ("E_B", 5),
        ("F_E_0", 6),
        ("F_E_1", 6),
        ("F_E_2", 6),
        ("F_B_0", 6),
        ("F_B_1", 6),
        ("F_B_2", 6),
    ]


def test_angular_power_spectra(mock_alms):
    from itertools import combinations_with_replacement

    from heracles.twopoint import angular_power_spectra

    order = ["P", "G_E", "G_B"]

    fields = []
    for (k, i), alm in mock_alms.items():
        if alm.dtype.metadata["spin"] == 0:
            fields.append((k, i))
        else:
            fields.append((f"{k}_E", i))
            fields.append((f"{k}_B", i))

    # alms cross themselves

    comb = {
        (k1, k2, i1, i2) if order.index(k1) <= order.index(k2) else (k2, k1, i2, i1)
        for (k1, i1), (k2, i2) in combinations_with_replacement(fields, 2)
    }

    cls = angular_power_spectra(mock_alms)

    assert cls.keys() == comb

    # explicit cross

    cls = angular_power_spectra(mock_alms, mock_alms)

    assert cls.keys() == comb

    # explicit include

    cls = angular_power_spectra(
        mock_alms,
        include=[("P", "P", ..., ...), ("P", "G_E", ..., ...)],
    )

    assert cls.keys() == {
        (k1, k2, i1, i2) if order.index(k1) <= order.index(k2) else (k2, k1, i2, i1)
        for k1, k2, i1, i2 in comb
        if (k1, k2) in [("P", "P"), ("P", "G_E")]
    }

    cls = angular_power_spectra(mock_alms, include=[("P", "P", 0), ("P", "G_E", 1)])

    assert cls.keys() == {
        (k1, k2, i1, i2) if order.index(k1) <= order.index(k2) else (k2, k1, i2, i1)
        for k1, k2, i1, i2 in comb
        if (k1, k2, i1) in [("P", "P", 0), ("P", "G_E", 1)]
    }

    # explicit exclude

    cls = angular_power_spectra(
        mock_alms,
        exclude=[("P", "P"), ("P", "G_E"), ("P", "G_B")],
    )

    assert cls.keys() == {
        (k1, k2, i1, i2) if order.index(k1) <= order.index(k2) else (k2, k1, i2, i1)
        for k1, k2, i1, i2 in comb
        if (k1, k2) not in [("P", "P"), ("P", "G_E"), ("P", "G_B")]
    }

    cls = angular_power_spectra(mock_alms, exclude=[(..., ..., 1, ...)])

    assert cls.keys() == {(k1, k2, i1, i2) for k1, k2, i1, i2 in comb if i1 != 1}

    # explicit cross with separate alms

    mock_alms1 = {(k, i): alm for (k, i), alm in mock_alms.items() if i % 2 == 0}
    mock_alms2 = {(k, i): alm for (k, i), alm in mock_alms.items() if i % 2 == 1}
    fields1 = [(k, i) for (k, i) in fields if i % 2 == 0]
    fields2 = [(k, i) for (k, i) in fields if i % 2 == 1]

    comb12 = {
        (k1, k2, i1, i2) if order.index(k1) <= order.index(k2) else (k2, k1, i2, i1)
        for k1, i1 in fields1
        for k2, i2 in fields2
    }

    cls = angular_power_spectra(mock_alms1, mock_alms2)

    assert cls.keys() == comb12


def test_debias_cls():
    from heracles.twopoint import debias_cls

    cls = {
        0: np.zeros(100),
        2: np.zeros(100, dtype=np.dtype(float, metadata={"bias": 4.56, "spin_2": 2})),
    }

    nbs = {
        0: 1.23,
    }

    debias_cls(cls, nbs, inplace=True)

    assert np.all(cls[0] == -1.23)

    assert np.all(cls[2][:2] == 0.0)
    assert np.all(cls[2][2:] == -4.56)


def test_debias_cls_healpix():
    import healpy as hp

    from heracles.twopoint import debias_cls

    pw0, pw2 = hp.pixwin(64, lmax=99, pol=True)

    md1 = {
        "kernel_1": "healpix",
        "nside_1": 64,
        "kernel_2": "healpix",
        "nside_2": 64,
        "spin_2": 2,
    }
    md2 = {
        "kernel_1": "healpix",
        "nside_1": 64,
        "spin_2": 2,
    }
    md3 = {
        "kernel_1": "healpix",
        "nside_1": 64,
        "kernel_2": "healpix",
        "nside_2": 64,
        "spin_2": 2,
        "deconv_2": False,
    }

    cls = {
        1: np.zeros(100, dtype=np.dtype(float, metadata=md1)),
        2: np.zeros(100, dtype=np.dtype(float, metadata=md2)),
        3: np.zeros(100, dtype=np.dtype(float, metadata=md3)),
    }

    nbs = {
        1: 1.23,
        2: 4.56,
        3: 7.89,
    }

    debias_cls(cls, nbs, inplace=True)

    assert np.all(cls[1][:2] == 0.0)
    assert np.all(cls[1][2:] == -1.23 / pw0[2:] / pw2[2:])

    assert np.all(cls[2][:2] == 0.0)
    assert np.all(cls[2][2:] == -4.56 / pw0[2:])

    assert np.all(cls[3][:2] == 0.0)
    assert np.all(cls[3][2:] == -7.89 / pw0[2:])


@patch("convolvecl.mixmat_eb")
@patch("convolvecl.mixmat")
def test_mixing_matrices(mock, mock_eb, rng):
    from heracles.twopoint import mixing_matrices

    # this only tests the function logic
    # the mixing matrix computation itself is tested elsewhere

    # field definition, requires mask and spin weight

    # mixmat_eb returns three values
    mock_eb.return_value = (Mock(), Mock(), Mock())

    lmax = 20
    cl = rng.standard_normal(lmax + 1)

    # create the mock field information
    fields = {
        "P": Mock(mask="V", spin=0),
        "G": Mock(mask="W", spin=2),
    }

    # compute pos-pos
    cls = {("V", "V", 0, 1): cl}
    mms = mixing_matrices(fields, cls)
    assert len(mms) == 1
    assert mock.call_count == 1
    assert mock_eb.call_count == 0
    mock.assert_called_with(cl, l1max=None, l2max=None, l3max=None, spin=(0, 0))
    assert mms["P", "P", 0, 1] is mock.return_value

    mock.reset_mock()
    mock_eb.reset_mock()

    # compute pos-she
    cls = {("V", "W", 0, 1): cl, ("W", "V", 0, 1): cl}
    mms = mixing_matrices(fields, cls)
    assert len(mms) == 2
    assert mock.call_count == 2
    assert mock_eb.call_count == 0
    assert mock.call_args_list == [
        call(cl, l1max=None, l2max=None, l3max=None, spin=(0, 2)),
        call(cl, l1max=None, l2max=None, l3max=None, spin=(2, 0)),
    ]
    assert mms["P", "G_E", 0, 1] is mock.return_value
    assert mms["G_E", "P", 0, 1] is mock.return_value

    mock.reset_mock()
    mock_eb.reset_mock()

    # compute she-she
    cls = {("W", "W", 0, 1): cl}
    mms = mixing_matrices(fields, cls)
    assert len(mms) == 3
    assert mock.call_count == 0
    assert mock_eb.call_count == 1
    mock_eb.assert_called_with(cl, l1max=None, l2max=None, l3max=None, spin=(2, 2))
    assert mms["G_E", "G_E", 0, 1] is mock_eb.return_value[0]
    assert mms["G_B", "G_B", 0, 1] is mock_eb.return_value[1]
    assert mms["G_E", "G_B", 0, 1] is mock_eb.return_value[2]

    mock.reset_mock()
    mock_eb.reset_mock()

    # compute unknown
    cls = {("X", "Y", 0, 1): cl}
    mms = mixing_matrices(fields, cls)
    assert len(mms) == 0

    mock.reset_mock()
    mock_eb.reset_mock()

    # compute multiple combinations
    cls = {("V", "V", 0, 0): cl, ("V", "V", 0, 1): cl, ("V", "V", 1, 1): cl}
    mms = mixing_matrices(fields, cls)
    assert len(mms) == 3
    assert mock.call_count == 3
    assert mock_eb.call_count == 0
    assert mock.call_args_list == [
        call(cl, l1max=None, l2max=None, l3max=None, spin=(0, 0)),
        call(cl, l1max=None, l2max=None, l3max=None, spin=(0, 0)),
        call(cl, l1max=None, l2max=None, l3max=None, spin=(0, 0)),
    ]
    assert mms.keys() == {("P", "P", 0, 0), ("P", "P", 0, 1), ("P", "P", 1, 1)}


@pytest.mark.parametrize("weights", [None, "l(l+1)", "2l+1", "<rand>"])
def test_binned_cls(rng, weights):
    from heracles.twopoint import binned_cls

    cls = {"key": rng.standard_normal(21)}

    bins = [2, 5, 10, 15, 20]

    if weights == "<rand>":
        weights_ = rng.random(40)
    else:
        weights_ = weights

    result = binned_cls(cls, bins, weights=weights_)

    for key, cl in cls.items():
        ell = np.arange(len(cl))

        if weights is None:
            w = np.ones_like(ell)
        elif weights == "l(l+1)":
            w = ell * (ell + 1)
        elif weights == "2l+1":
            w = 2 * ell + 1
        else:
            w = weights_[: len(ell)]

        binned_ell = []
        binned_cl = []
        binned_w = []
        for a, b in zip(bins[:-1], bins[1:]):
            inbin = (a <= ell) & (ell < b)
            binned_ell.append(np.average(ell[inbin], weights=w[inbin]))
            binned_cl.append(np.average(cl[inbin], weights=w[inbin]))
            binned_w.append(w[inbin].sum())

        np.testing.assert_array_almost_equal(result[key]["L"], binned_ell)
        np.testing.assert_array_almost_equal(result[key]["CL"], binned_cl)
        np.testing.assert_array_equal(result[key]["LMIN"], bins[:-1])
        np.testing.assert_array_equal(result[key]["LMAX"], bins[1:])
        np.testing.assert_array_almost_equal(result[key]["W"], binned_w)


@pytest.mark.parametrize("weights", [None, "l(l+1)", "2l+1", "<rand>"])
@pytest.mark.parametrize("ndim", [1, 2, 3])
def test_bin2pt(ndim, rng, weights):
    from heracles.twopoint import bin2pt

    data = rng.standard_normal((21, 31, 41)[:ndim])

    bins = [2, 5, 10, 15, 20]

    if weights == "<rand>":
        weights_ = rng.random(51)
    else:
        weights_ = weights

    result = bin2pt(data, bins, "XY", weights=weights_)

    ell = np.arange(len(data))

    if weights is None:
        w = np.ones_like(ell)
    elif weights == "l(l+1)":
        w = ell * (ell + 1)
    elif weights == "2l+1":
        w = 2 * ell + 1
    else:
        w = weights_[: len(ell)]

    binned_ell = np.empty(len(bins) - 1)
    binned_xy = np.empty((len(bins) - 1, *data.shape[1:]))
    binned_w = np.empty(len(bins) - 1)
    for i, (a, b) in enumerate(zip(bins[:-1], bins[1:])):
        inbin = (a <= ell) & (ell < b)
        binned_ell[i] = np.average(ell[inbin], weights=w[inbin])
        for j in np.ndindex(*binned_xy.shape[1:]):
            binned_xy[(i, *j)] = np.average(data[(inbin, *j)], weights=w[inbin])
        binned_w[i] = w[inbin].sum()

    np.testing.assert_array_almost_equal(result["L"], binned_ell)
    np.testing.assert_array_almost_equal(result["XY"], binned_xy)
    np.testing.assert_array_equal(result["LMIN"], bins[:-1])
    np.testing.assert_array_equal(result["LMAX"], bins[1:])
    np.testing.assert_array_almost_equal(result["W"], binned_w)
