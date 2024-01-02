# Heracles: Euclid code for harmonic-space statistics on the sphere
#
# Copyright (C) 2023 Euclid Science Ground Segment
#
# This file is part of Heracles.
#
# Heracles is free software: you can redistribute it and/or modify it
# under the terms of the GNU Lesser General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Heracles is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with Heracles. If not, see <https://www.gnu.org/licenses/>.
"""module for field definitions"""

from __future__ import annotations

import warnings
from abc import ABCMeta, abstractmethod
from types import MappingProxyType
from typing import TYPE_CHECKING

import coroutines
import numpy as np

from .core import update_metadata

if TYPE_CHECKING:
    from collections.abc import AsyncIterable, Mapping, Sequence
    from typing import Any

    from numpy.typing import ArrayLike

    from .catalog import Catalog, CatalogPage
    from .maps import Mapper
    from .progress import ProgressTask


# type alias for column specification
Columns = tuple["str | None", ...]


class Field(metaclass=ABCMeta):
    """Abstract base class for field definitions.

    Concrete classes must implement the `__call__()` method which takes
    a catalogue instance and returns a coroutine for mapping.

    """

    # column names: "col1", "col2", "[optional]"
    uses: Sequence[str] | str | None = None

    # every field subclass has a static spin weight attribute, which can be
    # overwritten by the class (or even an individual instance)
    __spin: int | None = None

    # definition of required and optional columns
    __ncol: tuple[int, int]

    def __init_subclass__(cls, *, spin: int | None = None) -> None:
        """Initialise spin weight of field subclasses."""
        super().__init_subclass__()
        if spin is not None:
            cls.__spin = spin
        uses = cls.uses
        if uses is None:
            uses = ()
        elif isinstance(uses, str):
            uses = (uses,)
        ncol = len(uses)
        nopt = 0
        for u in uses[::-1]:
            if u.startswith("[") and u.endswith("]"):
                nopt += 1
            else:
                break
        cls.__ncol = (ncol - nopt, ncol)

    def __init__(self, *columns: str) -> None:
        """Initialise the field."""
        super().__init__()
        self.__columns = self._init_columns(*columns) if columns else None
        self._metadata: dict[str, Any] = {}
        if (spin := self.__spin) is not None:
            self._metadata["spin"] = spin

    @classmethod
    def _init_columns(cls, *columns: str) -> Columns:
        """Initialise the given set of columns for a specific field
        subclass."""
        nmin, nmax = cls.__ncol
        if not nmin <= len(columns) <= nmax:
            uses = cls.uses
            if uses is None:
                uses = ()
            if isinstance(uses, str):
                uses = (uses,)
            count = f"{nmin}"
            if nmax != nmin:
                count += f" to {nmax}"
            msg = f"field of type '{cls.__name__}' accepts {count} columns"
            if uses:
                msg += " (" + ", ".join(uses) + ")"
            msg += f", received {len(columns)}"
            raise ValueError(msg)
        return columns + (None,) * (nmax - len(columns))

    @property
    def columns(self) -> Columns | None:
        """Return the catalogue columns used by this field."""
        return self.__columns

    @property
    def columns_or_error(self) -> Columns:
        """Return the catalogue columns used by this field, or raise a
        :class:`ValueError` if not set."""
        if self.__columns is None:
            msg = "no columns for field"
            raise ValueError(msg)
        return self.__columns

    @property
    def metadata(self) -> Mapping[str, Any]:
        """Return the static metadata for this field."""
        return MappingProxyType(self._metadata)

    @property
    def spin(self) -> int:
        """Spin weight of field."""
        spin = self.__spin
        if spin is None:
            clsname = self.__class__.__name__
            msg = f"field of type '{clsname}' has undefined spin weight"
            raise ValueError(msg)
        return spin

    @abstractmethod
    async def __call__(
        self,
        catalog: Catalog,
        mapper: Mapper,
        *,
        progress: ProgressTask | None = None,
    ) -> ArrayLike:
        """Implementation for mapping a catalogue."""
        ...


async def _pages(
    catalog: Catalog,
    progress: ProgressTask | None,
) -> AsyncIterable[CatalogPage]:
    """
    Asynchronous generator for the pages of a catalogue.  Also manages
    progress updates.
    """
    page_size = catalog.page_size
    if progress:
        progress.update(completed=0, total=catalog.size)
    for page in catalog:
        await coroutines.sleep()
        yield page
        if progress:
            progress.update(advance=page_size)
    # suspend again to give all concurrent loops a chance to finish
    await coroutines.sleep()


class Positions(Field, spin=0):
    """Field of positions in a catalogue.

    Can produce both overdensity maps and number count maps, depending
    on the ``overdensity`` property.

    """

    uses = "longitude", "latitude"

    def __init__(
        self,
        *columns: str,
        overdensity: bool = True,
        nbar: float | None = None,
    ) -> None:
        """Create a position field."""
        super().__init__(*columns)
        self.__overdensity = overdensity
        self.__nbar = nbar

    @property
    def overdensity(self) -> bool:
        """Flag to create overdensity maps."""
        return self.__overdensity

    @property
    def nbar(self) -> float | None:
        """Mean number count."""
        return self.__nbar

    @nbar.setter
    def nbar(self, nbar: float | None) -> None:
        """Set the mean number count."""
        self.__nbar = nbar

    async def __call__(
        self,
        catalog: Catalog,
        mapper: Mapper,
        *,
        progress: ProgressTask | None = None,
    ) -> ArrayLike:
        """Map the given catalogue."""

        # get catalogue column definition
        col = self.columns_or_error

        # position map
        pos = np.zeros(mapper.size, mapper.dtype)

        # keep track of the total number of galaxies
        ngal = 0

        # map catalogue data asynchronously
        async for page in _pages(catalog, progress):
            lon, lat = page.get(*col)
            mapper.map_values(lon, lat, [pos])

            ngal += page.size

            # clean up to free unneeded memory
            del page, lon, lat

        # get visibility map if present in catalogue
        vmap = catalog.visibility

        # match resolution of visibility map if present
        # FIXME generic mapper support
        if vmap is not None and vmap.size != pos.size:
            import healpy as hp

            warnings.warn("position and visibility maps have different NSIDE")
            vmap = hp.ud_grade(vmap, mapper.nside)

        # mean visibility (i.e. f_sky)
        if vmap is None:
            vbar = 1
        else:
            vbar = np.mean(vmap)

        # effective number of pixels
        npix = 4 * np.pi / mapper.area

        # compute average number count from map
        nbar = ngal / vbar / npix
        # override with provided value, but check that it makes sense
        if (nbar_ := self.nbar) is not None:
            # Poisson std dev from expected ngal assuming nbar_ is truth
            sigma_nbar = (nbar_ / vbar / npix) ** 0.5
            if abs(nbar - nbar_) > 3 * sigma_nbar:
                warnings.warn(
                    f"The provided mean density ({nbar_:g}) differs from the "
                    f"estimated mean density ({nbar:g}) by more than 3 sigma.",
                )
            nbar = nbar_

        # normalize map
        pos /= nbar

        # compute density contrast if asked to
        if self.__overdensity:
            if vmap is None:
                pos -= 1
            else:
                pos -= vmap

        # compute bias of number counts
        bias = ngal / (4 * np.pi) * mapper.area**2 / nbar**2

        # set metadata of array
        update_metadata(pos, self, catalog, mapper, nbar=nbar, bias=bias)

        # return the position map
        return pos


class ScalarField(Field, spin=0):
    """Field of real scalar values in a catalogue."""

    uses = "longitude", "latitude", "value", "[weight]"

    async def __call__(
        self,
        catalog: Catalog,
        mapper: Mapper,
        *,
        progress: ProgressTask | None = None,
    ) -> ArrayLike:
        """Map real values from catalogue to HEALPix map."""

        # get the column definition of the catalogue
        *col, wcol = self.columns_or_error

        # scalar field map
        val = np.zeros(mapper.size, mapper.dtype)

        # total weighted variance from online algorithm
        ngal = 0
        wmean, var = 0.0, 0.0

        # go through pages in catalogue and map values
        async for page in _pages(catalog, progress):
            if wcol is not None:
                page.delete(page[wcol] == 0)

            if page.size:
                lon, lat, v = page.get(*col)
                w = page.get(wcol) if wcol is not None else None

                mapper.map_values(lon, lat, [val], [v], w)

                ngal += page.size
                if w is None:
                    var += (v**2 - var).sum() / ngal
                else:
                    wmean += (w - wmean).sum() / ngal
                    var += ((w * v) ** 2 - var).sum() / ngal

                del lon, lat, v, w

            # clean up and yield control to main loop
            del page

        # fix mean weight if there was no column for it
        if wcol is None:
            wmean = 1.0

        # compute mean visibility
        if catalog.visibility is None:
            vbar = 1
        else:
            vbar = np.mean(catalog.visibility)

        # compute mean weight per effective mapper "pixel"
        wbar = ngal / (4 * np.pi * vbar) * wmean * mapper.area

        # normalise the map
        val /= wbar

        # compute bias from variance (per object)
        bias = 4 * np.pi * vbar**2 * (var / wmean**2) / ngal

        # set metadata of array
        update_metadata(val, self, catalog, mapper, wbar=wbar, bias=bias)

        # return the value map
        return val


class ComplexField(Field, spin=0):
    """Field of complex values in a catalogue.

    The :class:`ComplexField` class has zero spin weight, while
    subclasses such as :class:`Spin2Field` have non-zero spin weight.

    """

    uses = "longitude", "latitude", "real", "imag", "[weight]"

    async def __call__(
        self,
        catalog: Catalog,
        mapper: Mapper,
        *,
        progress: ProgressTask | None = None,
    ) -> ArrayLike:
        """Map complex values from catalogue to HEALPix map."""

        # get the column definition of the catalogue
        *col, wcol = self.columns_or_error

        # complex map with real and imaginary part
        val = np.zeros((2, mapper.size), mapper.dtype)

        # total weighted variance from online algorithm
        ngal = 0
        wmean, var = 0.0, 0.0

        # go through pages in catalogue and get the shear values,
        async for page in _pages(catalog, progress):
            if wcol is not None:
                page.delete(page[wcol] == 0)

            if page.size:
                lon, lat, re, im = page.get(*col)

                w = page.get(wcol) if wcol is not None else None

                mapper.map_values(lon, lat, [val[0], val[1]], [re, im], w)

                ngal += page.size
                if w is None:
                    var += (re**2 + im**2 - var).sum() / ngal
                else:
                    wmean += (w - wmean).sum() / ngal
                    var += ((w * re) ** 2 + (w * im) ** 2 - var).sum() / ngal

                del lon, lat, re, im, w

            del page

        # set mean weight if there was no column for it
        if wcol is None:
            wmean = 1.0

        # compute mean visibility
        if catalog.visibility is None:
            vbar = 1
        else:
            vbar = np.mean(catalog.visibility)

        # mean weight per effective mapper "pixel"
        wbar = ngal / (4 * np.pi * vbar) * wmean * mapper.area

        # normalise the map
        val /= wbar

        # bias from measured variance, for E/B decomposition
        bias = 2 * np.pi * vbar**2 * (var / wmean**2) / ngal

        # set metadata of array
        update_metadata(val, self, catalog, mapper, wbar=wbar, bias=bias)

        # return the shear map
        return val


class Visibility(Field, spin=0):
    """Copy visibility map from catalogue at given resolution."""

    async def __call__(
        self,
        catalog: Catalog,
        mapper: Mapper,
        *,
        progress: ProgressTask | None = None,
    ) -> ArrayLike:
        """Create a visibility map from the given catalogue."""

        # make sure that catalogue has a visibility map
        vmap = catalog.visibility
        if vmap is None:
            msg = "no visibility map in catalog"
            raise ValueError(msg)

        # warn if visibility is changing resolution
        if vmap.size != mapper.size:
            import healpy as hp

            warnings.warn(
                f"changing NSIDE of visibility map "
                f"from {hp.get_nside(vmap)} to {mapper.nside}",
            )
            vmap = hp.ud_grade(vmap, mapper.nside)
        else:
            # make a copy for updates to metadata
            vmap = np.copy(vmap)

        update_metadata(vmap, self, catalog, mapper)

        return vmap


class Weights(Field, spin=0):
    """Field of weight values from a catalogue."""

    uses = "longitude", "latitude", "[weight]"

    async def __call__(
        self,
        catalog: Catalog,
        mapper: Mapper,
        *,
        progress: ProgressTask | None = None,
    ) -> ArrayLike:
        """Map catalogue weights."""

        # get the columns for this field
        *col, wcol = self.columns_or_error

        # weight map
        wht = np.zeros(mapper.size, mapper.dtype)

        # map catalogue
        async for page in _pages(catalog, progress):
            lon, lat = page.get(*col)

            if wcol is None:
                w = None
            else:
                w = page.get(wcol)

            mapper.map_values(lon, lat, [wht], None, w)

            del page, lon, lat, w

        # compute average weight in nonzero pixels
        wbar = wht.mean()
        if catalog.visibility is not None:
            wbar /= np.mean(catalog.visibility)

        # normalise the map
        wht /= wbar

        # set metadata of arrays
        update_metadata(wht, self, catalog, mapper, wbar=wbar)

        # return the weight map
        return wht


class Spin2Field(ComplexField, spin=2):
    """Spin-2 complex field."""


Shears = Spin2Field
Ellipticities = Spin2Field
