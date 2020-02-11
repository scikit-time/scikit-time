# This file is part of sktime.
#
# Copyright (c) 2020, 2015, 2014 Computational Molecular Biology Group, Freie Universitaet Berlin (GER)
#
# sktime is free software: you can redistribute it and/or modify
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
import collections
from typing import List, Union, Optional

import numpy as np
import sktime.markovprocess.hmm._hmm_bindings as _bindings
from scipy.sparse import issparse

from sktime.base import Estimator
from sktime.markovprocess import TransitionCountModel, Q_
from sktime.markovprocess._transition_matrix import estimate_P, stationary_distribution
from sktime.markovprocess.hmm import HiddenMarkovStateModel
from sktime.markovprocess.hmm.hmm import viterbi
from sktime.markovprocess.util import compute_dtrajs_effective
from sktime.util import ensure_dtraj_list

_HMMModelStorage = collections.namedtuple('_HMMModelStorage', ['transition_matrix', 'output_model',
                                                               'initial_distribution'])


class MaximumLikelihoodHMSM(Estimator):
    """
    Maximum likelihood Hidden Markov model (HMM).

    This class is used to fit a maximum-likelihood HMM to data.

    References
    ----------
    [1] L. E. Baum and J. A. Egon, "An inequality with applications to statistical
        estimation for probabilistic functions of a Markov process and to a model
        for ecology," Bull. Amer. Meteorol. Soc., vol. 73, pp. 360-363, 1967.

    """

    def __init__(self, initial_model: HiddenMarkovStateModel, stride: Union[int, str] = 1,
                 lagtime: int = 1, reversible: bool = True, stationary: bool = False,
                 p: Optional[np.ndarray] = None, physical_time: str = '1 step', accuracy: float = 1e-3,
                 maxit: int = 1000, maxit_reversible: int = 100000):
        r"""
        Initialize a maximum likelihood hidden Markov model estimator. The type of output model (gaussian or discrete)
        and the number of hidden states are extracted from the initial model. In case no initial distribution was given,
        the initial model assumes a uniform initial distribution.

        Parameters
        ----------
        initial_model : HiddenMarkovStateModel
            This model will be used to initialize the hidden markov model estimation routine. Since it is prone to
            get stuck in local optima, several initializations should be tried and scored and/or one of the available
            initialization heuristics should be applied, if appropriate.
        stride : int or str, optional, default=1
            stride between two lagged trajectories extracted from the input trajectories. Given trajectory s[t], stride
            and lag will result in trajectories
                s[0], s[lag], s[2 lag], ...
                s[stride], s[stride + lag], s[stride + 2 lag], ...
            Setting stride = 1 will result in using all data (useful for maximum likelihood estimator), while a
            Bayesian estimator requires a longer stride in order to have statistically uncorrelated trajectories.
            Setting stride = 'effective' uses the largest neglected timescale as an fit for the correlation time and
            sets the stride accordingly.
        lagtime : int, optional, default=1
            Lag parameter used for fitting the HMM
        reversible : bool, optional, default=True
            If True, a prior that enforces reversible transition matrices (detailed balance) is used;
            otherwise, a standard  non-reversible prior is used.
        stationary : bool, optional, default=False
            If True, the initial distribution of hidden states is self-consistently computed as the stationary
            distribution of the transition matrix. If False, it will be estimated from the starting states.
            Only set this to true if you're sure that the observation trajectories are initiated from a global
            equilibrium distribution.
        p : (n,) ndarray, optional, default=None
            Initial or fixed stationary distribution. If given and stationary=True, transition matrices will be
            estimated with the constraint that they have the set parameter as their stationary distribution.
            If given and stationary=False, the parameter is the fixed initial distribution of hidden states.
        physical_time : str, optional, default='1 step'
            Description of the physical time corresponding to the trajectory time
            step.  May be used by analysis algorithms such as plotting tools to
            pretty-print the axes. By default '1 step', i.e. there is no physical
            time unit. Specify by a number, whitespace and unit. Permitted units
            are (* is an arbitrary string):

            |  'fs',  'femtosecond*'
            |  'ps',  'picosecond*'
            |  'ns',  'nanosecond*'
            |  'us',  'microsecond*'
            |  'ms',  'millisecond*'
            |  's',   'second*'
        accuracy : float, optional, default=1e-3
            Convergence threshold for EM iteration. When two the likelihood does not increase by more than
            accuracy, the iteration is stopped successfully.
        maxit : int, optional, default=1000
            Stopping criterion for EM iteration. When this many iterations are performed without reaching the requested
            accuracy, the iteration is stopped without convergence and a warning is given.
        maxit_reversible : int, optional, default=1000000
            Maximum number of iterations for reversible transition matrix estimation. Only used with reversible=True.
        """
        super().__init__()
        self.initial_transition_model = initial_model
        self.stride = stride
        self.lagtime = lagtime
        self.reversible = reversible
        self.stationary = stationary
        if stationary:
            self.fixed_stationary_distribution = p
        else:
            self.fixed_initial_distribution = p
        self.accuracy = accuracy
        self.maxit = maxit
        self.maxit_reversible = maxit_reversible
        self.physical_time = physical_time

    @property
    def physical_time(self) -> Q_:
        r""" yields a description of the physical time """
        return self._physical_time

    @physical_time.setter
    def physical_time(self, value: str):
        r"""
        Sets a description of the physical time for input trajectories. Specify by a number, whitespace, and unit.
        Permitted units are 'fs', 'ps', 'ns', 'us', 'ms', 's', and 'step'.

        Parameters
        ----------
        value : str
            the physical time description
        """
        self._physical_time = Q_(value)

    @property
    def maxit_reversible(self) -> int:
        return self._maxit_reversible

    @maxit_reversible.setter
    def maxit_reversible(self, value: int):
        self._maxit_reversible = int(value)

    @property
    def fixed_stationary_distribution(self) -> Optional[np.ndarray]:
        return self._fixed_stationary_distribution

    @fixed_stationary_distribution.setter
    def fixed_stationary_distribution(self, value: Optional[np.ndarray]):
        if value is not None and value.shape[0] != self.n_hidden_states:
            raise ValueError("Fixed stationary distribution must be as long as there are hidden states.")
        self._fixed_stationary_distribution = value

    @property
    def fixed_initial_distribution(self) -> Optional[np.ndarray]:
        return self._fixed_initial_distribution

    @fixed_initial_distribution.setter
    def fixed_initial_distribution(self, value: Optional[np.ndarray]):
        if value is not None and value.shape[0] != self.n_hidden_states:
            raise ValueError("Fixed initial distribution must be as long as there are hidden states.")
        self._fixed_initial_distribution = value

    @property
    def stationary(self) -> bool:
        return self._stationary

    @stationary.setter
    def stationary(self, value: bool):
        self._stationary = bool(value)

    @property
    def accuracy(self) -> float:
        return self._accuracy

    @accuracy.setter
    def accuracy(self, value: float):
        self._accuracy = float(value)

    @property
    def maxit(self) -> int:
        return self._maxit

    @maxit.setter
    def maxit(self, value: int):
        self._maxit = int(value)

    @property
    def reversible(self) -> bool:
        return self._reversible

    @reversible.setter
    def reversible(self, value: bool):
        self._reversible = bool(value)

    @property
    def stride(self) -> Union[int, str]:
        return self._stride

    @stride.setter
    def stride(self, value):
        if isinstance(value, str):
            if value != 'effective':
                raise ValueError("stride value can only be either integer or 'effective'.")
            else:
                self._stride = value
        else:
            self._stride = int(value)

    @property
    def lagtime(self) -> int:
        return self._lagtime

    @lagtime.setter
    def lagtime(self, value: int):
        value = int(value)
        if value <= 0:
            raise ValueError("Lagtime must be positive!")
        self._lagtime = value

    @property
    def n_hidden_states(self) -> int:
        return self._initial_model.n_hidden_states

    @property
    def initial_transition_model(self) -> HiddenMarkovStateModel:
        return self._initial_transition_model

    @initial_transition_model.setter
    def initial_transition_model(self, value: HiddenMarkovStateModel) -> None:
        self._initial_transition_model = value

    def fit(self, dtrajs, initial_model=None, **kwargs):
        if initial_model is None:
            initial_model = self.initial_transition_model
        if initial_model is None or not isinstance(initial_model, HiddenMarkovStateModel):
            raise ValueError("For estimation, an initial model of type "
                             "`sktime.markovprocess.hmm.HiddenMarkovStateModel` is required.")

        # copy initial model
        transition_matrix = initial_model.transition_model.transition_matrix
        if issparse(transition_matrix):
            # want dense matrix, toarray makes a copy
            transition_matrix = transition_matrix.toarray()
        else:
            # new instance
            transition_matrix = np.copy(transition_matrix)

        hmm_data = _HMMModelStorage(transition_matrix=transition_matrix, output_model=initial_model.output_model.copy(),
                                    initial_distribution=initial_model.initial_distribution.copy())

        dtrajs = ensure_dtraj_list(dtrajs)
        dtrajs = compute_dtrajs_effective(dtrajs, lagtime=self.lagtime, n_states=initial_model.n_hidden_states,
                                          stride=self.stride)

        max_n_frames = max(len(obs) for obs in dtrajs)
        # pre-construct hidden variables
        N = self.n_states
        alpha = np.zeros((max_n_frames, N))
        beta = np.zeros((max_n_frames, N))
        gammas = [np.zeros((len(obs), N)) for obs in dtrajs]
        count_matrices = [np.zeros((N, N)) for _ in dtrajs]

        it = 0
        likelihoods = np.empty(self.maxit)
        # flag if connectivity has changed (e.g. state lost) - in that case the likelihood
        # is discontinuous and can't be used as a convergence criterion in that iteration.
        tmatrix_nonzeros = hmm_data.transition_matrix.nonzero()
        converged = False

        while not converged and it < self.maxit:
            loglik = 0.0
            for obs, gamma, counts in zip(dtrajs, gammas, count_matrices):
                loglik_update, _ = self._forward_backward(hmm_data, obs, alpha, beta, gamma, counts)
                loglik += loglik_update
            assert np.isfinite(loglik), it

            # convergence check
            if it > 0:
                dL = loglik - likelihoods[it - 1]
                if dL < self._accuracy:
                    converged = True

            # update model
            self._update_model(hmm_data, dtrajs, gammas, count_matrices, maxiter=self._maxit_P)

            # connectivity change check
            tmatrix_nonzeros_new = hmm_data.transition_matrix.nonzero()
            if not np.array_equal(tmatrix_nonzeros, tmatrix_nonzeros_new):
                converged = False  # unset converged
                tmatrix_nonzeros = tmatrix_nonzeros_new

            # end of iteration
            likelihoods[it] = loglik
            it += 1

        likelihoods = np.resize(likelihoods, it)

        transition_counts = self._reduce_transition_counts(count_matrices)

        count_model = TransitionCountModel(count_matrix=transition_counts, lagtime=self.lagtime,
                                           physical_time=self.physical_time)
        model = HiddenMarkovStateModel(
            transition_model=hmm_data.transition_matrix,
            output_model=hmm_data.output_model,
            initial_distribution=hmm_data.initial_distribution,
            likelihoods=likelihoods,
            state_probabilities=gammas,
            initial_count=self._init_counts(gammas),
            hidden_state_trajectories=[viterbi(hmm_data.transition_matrix, obs, hmm_data.initial_distribution)
                                       for obs in dtrajs],
            count_model=count_model
        )
        self._model = model
        return self

    @staticmethod
    def _forward_backward(model: _HMMModelStorage, obs, alpha, beta, gamma, counts):
        """
        Estimation step: Runs the forward-back algorithm on trajectory obs

        Parameters
        ----------
        model: _HMMModelStorage
            named tuple with transition matrix, initial distribution, output model
        obs: np.ndarray
            single observation corresponding to index itraj
        alpha: ndarray
            forward coefficients
        beta: ndarray
            backward coefficients
        gamma: ndarray
            gammas
        counts: ndarray
            count matrix

        Returns
        -------
        logprob : float
            The probability to observe the observation sequence given the HMM
            parameters
        pobs : ndarray
            state probability trajectory obtained from obs
        """
        # get parameters
        A = model.transition_matrix
        pi = model.initial_distribution
        T = len(obs)
        # compute output probability matrix
        pobs = model.output_model.to_state_probability_trajectory(obs)
        # forward variables
        logprob = _bindings.util.forward(A, pobs, pi, alpha_out=alpha, T=T)
        # backward variables
        _bindings.util.backward(A, pobs, beta_out=beta, T=T)
        # gamma
        _bindings.util.state_probabilities(alpha, beta, gamma_out=gamma, T=T)
        # count matrix
        _bindings.util.transition_counts(alpha, beta, A, pobs, counts_out=counts, T=T)
        return logprob, pobs

    def _init_counts(self, gammas):
        gamma0_sum = np.zeros(self.n_hidden_states)
        # update state counts
        for g in gammas:
            gamma0_sum += g[0]
        return gamma0_sum

    @staticmethod
    def _reduce_transition_counts(count_matrices):
        C = np.add.reduce(count_matrices)
        return C

    def _update_model(self, model: _HMMModelStorage, observations: List[np.ndarray], gammas: List[np.ndarray],
                      count_matrices: List[np.ndarray], maxiter: int = int(1e7)):
        """
        Maximization step: Updates the HMM model given the hidden state assignment and count matrices

        Parameters
        ----------
        gammas : [ ndarray(T,N, dtype=float) ]
            list of state probabilities for each trajectory
        count_matrices : [ ndarray(N,N, dtype=float) ]
            list of the Baum-Welch transition count matrices for each hidden
            state trajectory
        maxiter : int
            maximum number of iterations of the transition matrix estimation if
            an iterative method is used.

        """
        gamma0_sum = self._init_counts(gammas)
        C = self._reduce_transition_counts(count_matrices)

        # compute new transition matrix
        T = estimate_P(C, reversible=self.reversible, fixed_statdist=self.fixed_stationary_distribution,
                       maxiter=maxiter, maxerr=1e-12, mincount_connectivity=1e-16)
        # estimate stationary or init distribution
        if self.stationary:
            if self.fixed_stationary_distribution is None:
                pi = stationary_distribution(T, C=C, mincount_connectivity=1e-16)
            else:
                pi = self.fixed_stationary_distribution
        else:
            if self.fixed_initial_distribution is None:
                pi = gamma0_sum / np.sum(gamma0_sum)
            else:
                pi = self.fixed_initial_distribution

        model.initial_distribution = pi
        model.transition_matrix = T
        model.output_model.fit(observations, gammas)