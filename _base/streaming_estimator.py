# This file is part of PyEMMA.
#
# Copyright (c) 2016 Computational Molecular Biology Group, Freie Universitaet Berlin (GER)
#
# PyEMMA is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


from __future__ import absolute_import

import numpy as np
from pyemma._base.estimator import Estimator
from pyemma.coordinates.data import DataInMemory
from pyemma.coordinates.data._base import DEFAULT_CHUNKSIZE
from pyemma.coordinates.data._base.iterable import Iterable
from pyemma.util.exceptions import NotConvergedWarning


class StreamingEstimator(Estimator):
    r""" Base class for streamed estimation.

    It checks the input and wraps it in a Iterable, to be able to access the data
    in a streaming fashion.
    """
    def __init__(self, chunksize=NotImplemented):
        super(StreamingEstimator, self).__init__()

    def estimate(self, X, chunksize=DEFAULT_CHUNKSIZE, **kwargs):
        # ensure the input is able to provide a stream
        if not isinstance(X, Iterable):
            from pyemma.util import types
            array_list = types.ensure_traj_list(X)
            X = DataInMemory(array_list, chunksize=chunksize)
        # Because we want to use pipelining methods like get_output, we have to set a data producer.
        self.data_producer = X
        self.chunksize = chunksize
        X.chunksize = self.chunksize
        # run estimation
        try:
            super(StreamingEstimator, self).estimate(X, **kwargs)
        except NotConvergedWarning as ncw:
            self._logger.info(
                "Presumably finished estimation. Message: %s" % ncw)
        return self

    @property
    def chunksize(self):
        """chunksize defines how much data is being processed at once."""
        return self._chunksize

    @chunksize.setter
    def chunksize(self, size):
        if size is None:
            size = DEFAULT_CHUNKSIZE
        if not size >= 0:
            raise ValueError('chunksize has to be positive')

        self._chunksize = int(size)
