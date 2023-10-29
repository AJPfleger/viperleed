"""Module energy_range of viperleed.tleedmlib.classes.rparams.special.

Created on 2023-10-23

@author: Michele Riva (@michele-riva)

Classes
-------
EnergyRange
    Base class for parameters with 'start stop step' user input .
TheoEnergies(EnergyRange)
    Used as the Rparams attribute THEO_ENERGIES
"""

import ast
from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite, remainder
from numbers import Real

from ._base import SpecialParameter
from .._defaults import NO_VALUE


EPS = 1e-8  # Tolerance for comparisons of floats

# Notice that we purposely do not pass a param keyword here, as
# this is exclusively a base class, and it is not associated with
# any parameter. Hence, it is not registered by SpecialParameter.

@dataclass
class EnergyRange(SpecialParameter):
    """A container for energies."""

    start: float = NO_VALUE
    stop: float = NO_VALUE
    step: float = NO_VALUE

    def __eq__(self, other):
        """Return whether this EnergyRange is identical to another."""
        if not isinstance(other, (EnergyRange, Sequence)):
            return NotImplemented
        if len(tuple(self)) != len(tuple(other)):
            return NotImplemented
        scale = self.step if self.has_step else 1
        for v_self, v_other in zip(self, other):
            if (v_self, v_other) == (NO_VALUE, NO_VALUE):
                continue
            if v_self is NO_VALUE or v_other is NO_VALUE:
                return NotImplemented
            if abs(v_self - v_other) > EPS*scale:
                return NotImplemented
        return True

    def __iter__(self):
        """Yield items of self."""
        yield self.start
        yield self.stop
        yield self.step

    def __post_init__(self):
        """Check and process initialization values."""
        non_defaults = self._non_defaults
        if not all(isinstance(e, Real) for e in non_defaults):
            raise TypeError('Values must be real')
        if not all(isfinite(e) for e in non_defaults):
            raise ValueError('All values must be finite')
        self._check_consistency()

    @property
    def min(self):
        """Return the lower limit of this EnergyRange."""
        return self.start

    @property
    def max(self):
        """Return the upper limit of this EnergyRange."""
        return self.stop

    @property
    def defined(self):
        """Return whether all of the attributes have a value set."""
        return not any(v is NO_VALUE for v in self)

    @property
    def has_bounds(self):
        """Return whether both start and stop are defined."""
        return not any(v is NO_VALUE for v in (self.start, self.stop))

    @property
    def has_step(self):
        """Return whether this EnergyRange has step defined."""
        return self.step is not NO_VALUE

    @property
    def n_energies(self):
        """Return the number of energies in this TheoEnergies."""
        if not self.defined:
            raise RuntimeError(f'{self} has undefined items')
        # +1 because we include both start and stop
        return round((self.stop - self.start) / self.step) + 1

    @property
    def _non_defaults(self):
        """Return the non-default values in self."""
        return [e for e in self if e is not NO_VALUE]

    @classmethod
    def from_value(cls, value):
        """Return an EnergyRange from value."""
        return cls(*value)

    @classmethod
    def from_sorted_grid(cls, energy_grid):
        """Return an energy range from a sorted grid of energies."""
        n_energies = len(energy_grid)
        if n_energies < 2:
            raise ValueError('Not enough energy_grid values. Need '
                             f'at least 2, found {n_energies}')
        start, stop = energy_grid[0], energy_grid[-1]
        step = energy_grid[1] - energy_grid[0]                                  # TODO: or is it better (stop-start)/(N-1) ?
        # step = (stop - start) / (n_energies - 1)
        return cls(start, stop, step)

    @staticmethod
    def parse_string_sequence(string_sequence):
        """Return floating-point or NO_VALUE from a string sequence."""
        # We will use ast to interpret the sequence as a tuple.
        # Notice the trailing comma, in case string_sequence is
        # only one-element-long
        string = ','.join(string_sequence) + ','

        # We have to replace '_' with something that AST can
        # handle. 'None' seems easy enough. We replace it
        # again further down when converting the rest to float
        string = string.replace('_', 'None')
        try:
            return [float(v) if v is not None else NO_VALUE
                    for v in ast.literal_eval(string)]
        except (SyntaxError, ValueError, TypeError,
                MemoryError, RecursionError) as exc:
            new_exc = TypeError if 'float' in exc.args[0] else ValueError
            raise new_exc(' '.join(string_sequence)) from exc

    def set_undefined_values(self, *new_values):
        """Assign undefined values from new_values, then adjust start."""
        if len(new_values) == 1:
            new_values = new_values[0]
        for attr, value in zip(('start', 'stop', 'step'), new_values):
            if getattr(self, attr) is NO_VALUE:
                setattr(self, attr, value)
        self.__post_init__()  # Check and process new values

    def _check_consistency(self):
        """Change inconsistent values or complain."""
        try:
            1 / self.step
        except ZeroDivisionError:
            raise ValueError('Step cannot be zero') from None
        except TypeError:  # NO_VALUE
            pass

        start, stop, step = self
        if self.defined and (stop - start) * step < 0:
            raise ValueError('Inconsistent step. Cannot shift from '
                             f'{start:.2f} to {stop:.2f} with {step=:.2f}')
        if self.has_bounds and self._swap and stop < start:
            self._swap()

    def _swap(self):
        """Swap start and stop, change step."""
        self.start, self.stop = self.stop, self.start
        if self.has_step:
            self.step *= -1


class TheoEnergies(EnergyRange, param='THEO_ENERGIES'):
    """Energy range used for calculating I(V) curves."""

    def __post_init__(self):
        """Check and process initialization values."""
        super().__post_init__()
        if not all(e > 0 for e in self._non_defaults):
            raise ValueError('Values must be positive')
        if self.has_bounds and self.stop < self.start:
            raise ValueError('Maximum energy value should be at '
                             'least as large as the minimum')

        # Mess with start/stop only if all the values are present,
        # otherwise, leave it for when the others will be initialized
        # from experimental data. That's in Rparams.initTheoEnergies.
        if self.defined:
            self.adjust_to_fit_step()

    @property
    def is_adjusted(self):
        """Return whether (stop - start) is a multiple of step."""
        if not self.defined:
            raise RuntimeError(f'{self} has undefined items')
        start, stop, step = self
        return abs(remainder(stop - start,  step)) < EPS

    def adjust_to_fit_step(self):
        """Modify start so that (stop - start) is a multiple of step."""
        if self.is_adjusted:
            return

        start, stop, step = self
        # The next line could in principle also be done with
        # remainder, but there are some corner cases in which
        # it is complicated to get the same results as now.
        start -= step - (stop - start) % step
        # if start < -EPS:    # Testing reveals that this is never hit
            # start = start % step
        if abs(start) < EPS:
            start = step
        self.start = start

    def as_floats(self):
        """Return a list of float values, replacing NO_VALUE with -1."""
        return [-1 if e is NO_VALUE else e for e in self]

    def contains(self, other):
        """Return whether other is a subset of this TheoEnergies."""
        if not isinstance(other, TheoEnergies):
            raise TypeError
        if not self.defined:
            raise RuntimeError('Cannot compare non-defined TheoEnergies')
        if not other.defined:
            raise ValueError('Cannot compare non-defined TheoEnergies')
        if self.start > other.start or self.stop < other.stop:
            return False
        if self.step != other.step:
            return False
        # Finally, make sure they're not shifted
        self_shift = remainder(self.start, self.step)
        other_shift = remainder(other.start, other.step)
        return abs(self_shift - other_shift) < self.step * EPS

    _swap = None  # Never swap a TheoEnergies. All items must be > 0


class IVShiftRange(EnergyRange, param='IV_SHIFT_RANGE'):
    """EnergyRange for Rparams attribute IV_SHIFT_RANGE."""

    @classmethod
    def fixed(cls, fixed_value):
        """Return an IVShiftRange with both bounds at the same value."""
        return cls(fixed_value, fixed_value, NO_VALUE)
