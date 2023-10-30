"""Tests for EnergyRange(+subclasses) of viperleed.tleedmlib.rparams.special.

Created on 2023-10-27

@author: Michele Riva (@michele-riva)

Contains also tests for the TheoEnergies subclass of EnergyRange.
"""

import itertools

import numpy as np
import pytest
from pytest_cases import fixture, parametrize

from viperleed.tleedmlib.classes.rparams import EnergyRange
from viperleed.tleedmlib.classes.rparams import IVShiftRange
from viperleed.tleedmlib.classes.rparams import TheoEnergies
from viperleed.tleedmlib.classes.rparams.special.energy_range import EPS
from viperleed.tleedmlib.classes.rparams._defaults import NO_VALUE


class TestEnergyRange:
    """Collection of tests for the EnergyRange base class."""

    _class = EnergyRange

    @fixture(name='make_range', scope='class')
    def factory_make_range(self):
        """Return an EnergyRange object."""
        def _make(name):
            try:
                return self._class(*self.valid[name][0])
            except KeyError:
                pytest.skip(f'{name!r} is not valid')
                raise
        return _make

    valid = {      # init value,     expected
        '1 2 0.1': ((1.0, 2.0, 0.1), (1.0, 2.0, 0.1)),
        '1 2 0.2': ((1.0, 2.0, 0.2), (1.0, 2.0, 0.2)),
        'shifted': ((1.05, 2.05, 0.2), (1.05, 2.05, 0.2)),
        'start==stop': ((1.0, 1.0, 0.1), (1.0, 1.0, 0.1)),
        'small step': ((1.0, 1.7, 1e-10), (1.0, 1.7, 1e-10)),
        'swapped': ((3.0, 1.0, -0.1), (1.0, 3.0, 0.1)),
        'swapped no step': ((3.0, 1.0), (1.0, 3.0, NO_VALUE)),
        'negative': ((-3.0, 1.0), (-3.0, 1.0, NO_VALUE)),
        'no step': ((1.0, 2.0), (1.0, 2.0, NO_VALUE)),
        'large': ((10**20, 10**21, 10**19), (10**20, 10**21, 10**19)),
        'many': ((0.0492, 1230.0369, 0.0123), (0.0492, 1230.0369, 0.0123)),
        }
    invalid = {
        'wrong type': (('invalid_input',), TypeError),
        'start>stop': ((2.0, 1.0, 0.1), ValueError),
        'step zero': ((1.0, 3.0, 0.0), ValueError),
        'infinite': ((float('-inf'), 5.0, 1.2), ValueError),
        'nan': ((1.0, float('nan'), 0.4), ValueError),
        'inf step': ((1.0, 5.0, float('inf')), ValueError),
        'nan step': ((1.0, 5.0, float('nan')), ValueError),
        }

    @parametrize(name=valid, ids=valid)
    def test_equal(self, name, make_range):
        """Check correct result of the equality method."""
        energy_range = make_range(name)
        *_, expected = self.valid[name]
        assert pytest.approx(energy_range) == expected
        assert energy_range == make_range(name)

    @parametrize(names=itertools.combinations(valid, 2))
    def test_different(self, names, make_range):
        """Check non-equality of different ranges."""
        assert make_range(names[0]) != make_range(names[1])

    non_comparable = ('string', 1.78)

    @parametrize(invalid=non_comparable)
    def test_different_not_comparable(self, invalid, make_range):
        """Check that an invalid type cannot be compared."""
        assert make_range('1 2 0.1') != invalid

    @parametrize(name=valid)
    def test_iter(self, name, make_range):
        """Check correct iteration of an EnergyRange."""
        energy_range = make_range(name)
        *_, expected = self.valid[name]
        assert tuple(energy_range) == pytest.approx(expected)

    @parametrize(name=valid)
    def test_properties(self, name, make_range):
        """Check min and max."""
        energy_range = make_range(name)
        *_, expected = self.valid[name]
        min_max = energy_range.min, energy_range.max
        assert min_max == pytest.approx(expected[:2])

    n_energies = {
        '1 2 0.1': 11,
        '1 2 0.2': 6,
        'start==stop': 1,
        'small step': 7e9+1,
        'swapped': 21,
        'adjust': 5,
        'large': 91,
        'many': 100000,
        }

    @parametrize('name,expected', n_energies.items(), ids=n_energies)
    def test_n_energies(self, name, expected, make_range):
        """Check correct number of energies."""
        energy_range = make_range(name)
        assert energy_range.n_energies == expected

    @parametrize(name=valid)
    def test_from_value(self, name):
        """Check correct creation from a single sequence."""
        if name not in self.valid:
            pytest.skip(reason=f'{name!r} is not valid')
        value, expected = self.valid[name]
        energy_range = self._class.from_value(value)
        assert tuple(energy_range) == pytest.approx(expected)

    @parametrize('value,exc', invalid.values(), ids=invalid)
    def test_invalid_input(self, value, exc):
        """Check complaints when created from an invalid input."""
        with pytest.raises(exc):
            self._class.from_value(value)

    def test_defined(self, make_range):
        """Check correct value of defined @property."""
        assert make_range('large').defined
        assert make_range('swapped').defined
        assert not make_range('no step').defined

    _n_many = n_energies['many']
    valid_grid = {
        'simple': ([4.0, 5.0, 6.0, 7.0], (4, 7, 1)),
        'many': (0.0123*(np.arange(_n_many) + 4), (0.0492, 1230.0369, 0.0123)),
        'random': (0.0123*(np.arange(_n_many) + 4)
                   + 0.0123*EPS*(np.random.rand(_n_many)-0.5),
                   (0.0492, 1230.0369, 0.0123)),
        'float step': ([0.1, 0.2, 0.3, 0.4, 0.5], (0.1, 0.5, 0.1)),
        'inverted': ([7.0, 6.0, 5.0, 4.0], (4, 7, 1)),
        }
    invalid_grid = {
        'too few': ([0.0], ValueError),
        'wrong types': (['1.0', '2.0', '3.0', '4.0'], TypeError),
        }

    @parametrize('grid,expected', valid_grid.values(), ids=valid_grid)
    def test_from_sorted_grid_valid(self, grid, expected):
        """Test valid initialization from a sorted energy grid."""
        energies = self._class.from_sorted_grid(grid)
        assert energies == expected

    @parametrize('grid,exc', invalid_grid.values(), ids=invalid_grid)
    def test_from_sorted_grid_invalid(self, grid, exc):
        """Check complaints when given an invalid energy grid."""
        with pytest.raises(exc):
            self._class.from_sorted_grid(grid)

    def test_undefined_raises(self, make_range):
        """Check complaints when accessing properties of undefined range."""
        undefined = make_range('no step')
        for attr in ('is_adjusted', 'n_energies'):
            with pytest.raises(RuntimeError):
                getattr(undefined, attr)
        for method_name in ('adjust_to_fit_step', ):
            method = getattr(undefined, method_name)
            with pytest.raises(RuntimeError):
                method()

    @parametrize(name=valid)
    def test_adjusted(self, name, make_range):
        """Check that a defined TheoEnergies is adjusted."""
        energy_range = make_range(name)
        if not energy_range.defined:
            pytest.skip(f'{name!r} range is not fully defined')
        assert energy_range.is_adjusted

    set_undef = {  # ini_vals, new_vals, expect
        'defined': ((1.0, 3.0, 0.1), (0.4, 1.8, 0.2), (1.0, 3.0, 0.1)),
        'no step': ((1.0, 3.0, NO_VALUE), (0.4, 1.8, 0.2), (1.0, 3.0, 0.2)),
        'no bound': ((NO_VALUE, 3.0, NO_VALUE), ((1.0, 3.0, NO_VALUE)),
                     (1.0, 3.0, NO_VALUE)),
        }

    @parametrize('ini_vals,new_vals,expect', set_undef.values(), ids=set_undef)
    def test_set_undefined(self, ini_vals, new_vals, expect, subtests):
        """Check correct setting of new values for undefined members."""
        before = self._class(*ini_vals)
        with subtests.test('single object'):
            before.set_undefined_values(new_vals)
            assert before == expect

        # Again, with unpacking
        before = self._class(*ini_vals)
        with subtests.test('unpacked'):
            before.set_undefined_values(*new_vals)
            assert before == expect

    @parametrize(name=valid)
    def test_copy(self, name, make_range, subtests):
        """Check correct creation of a copy."""
        original = make_range(name)
        copied = original.copy()
        with subtests.test('identity'):
            assert copied is not original
        with subtests.test('equality'):
            assert copied == original
        if not copied.defined:
            return
        with subtests.test('different after modification'):
            copied.start += copied.step
            assert copied != original

    contains_valid = {  # outer, inner
        'same':         ((1.0, 2.0, 0.1), (1.0, 2.0, 0.1), True),
        'start lower':  ((0.7, 2.0, 0.1), (1.0, 2.0, 0.1), True),
        'start higher': ((1.2, 2.0, 0.1), (1.0, 2.0, 0.1), False),
        'stop lower':   ((1.0, 1.8, 0.1), (1.0, 2.0, 0.1), False),
        'stop higher':  ((1.0, 2.9, 0.1), (1.0, 2.0, 0.1), True),
        'diff step':    ((1.0, 2.0, 0.1), (1.0, 2.0, 0.5), False),
        'shifted':      ((0.05, 2.05, 0.1), (1.0, 2.2, 0.1), False),
        }

    @parametrize('out_args,in_args,result', contains_valid.values(),
                 ids=contains_valid)
    def test_contains(self, out_args, in_args, result):
        """Check correct result of contains method."""
        outer = self._class(*out_args)
        inner = self._class(*in_args)
        assert outer.contains(inner) is result

    contains_invalid = {
        'self undefined': (TheoEnergies(), TheoEnergies(1.0, 2.0, 0.1),
                           RuntimeError),
        'other undefined': (TheoEnergies(1.0, 2.0, 0.1), TheoEnergies(),
                            ValueError),
        'wrong type': (TheoEnergies(0.05, 5.05, 0.1), 'abcd', TypeError),
        }

    @parametrize('outer,inner,exc', contains_invalid.values(),
                 ids=contains_invalid)
    def test_contains_invalid(self, outer, inner, exc):
        """Check complaints when calling contains with invalid arguments."""
        with pytest.raises(exc):
            outer.contains(inner)


class TestTheoEnergies(TestEnergyRange):
    """Tests for the TheoEnergies subclass of EnergyRange."""

    _class = TheoEnergies
    valid = {
        **TestEnergyRange.valid,
        'adjust': ((1.0, 10.0, 2.0), (2.0, 10.0, 2.0)),
        }
    for key in ('negative',):
        valid.pop(key)

    invalid = {
        **TestEnergyRange.invalid,
        'negative': ((-3.0, 1.0, 0.1), ValueError),
        }

    @parametrize('value,exc', invalid.values(), ids=invalid)
    def test_invalid_input(self, value, exc):
        """Check complaints when created from an invalid input."""
        super().test_invalid_input(value, exc)

    @parametrize(name=valid)
    def test_adjusted(self, name, make_range):
        """Check that a defined TheoEnergies is adjusted."""
        energy_range = make_range(name)
        if not energy_range.defined:
            energy_range.set_undefined_values(3, 20, 0.5)
        assert energy_range.is_adjusted

    @parametrize('name,expected', valid.items(), ids=valid)
    def test_as_floats(self, name, expected, make_range):
        """Check correctness of the as_floats method."""
        energy_range = make_range(name)
        if not energy_range.defined:
            assert -1 in energy_range.as_floats()
        else:
            as_floats = energy_range.as_floats()
            assert as_floats == pytest.approx(list(expected[1]))
            assert -1 not in as_floats

    set_undef = {  # ini_vals, new_vals, expect
        **TestEnergyRange.set_undef,
        'adjust': ((0.1, 1.0, NO_VALUE), (3.6, 8.0, 0.2), (0.2, 1.0, 0.2)),
        }

    @parametrize('ini_vals,new_vals,expect', set_undef.values(), ids=set_undef)
    def test_set_undefined(self, ini_vals, new_vals, expect, subtests):
        """Check correct setting of new values for undefined members."""
        super().test_set_undefined(ini_vals, new_vals, expect, subtests)


class TestIVShiftRange(TestEnergyRange):
    """Tests for IVShiftRange subclass of EnergyRange."""

    _class = IVShiftRange
    valid = {
        **TestEnergyRange.valid,
        # Replace the ones that need adjustments
        'shifted': ((1.05, 2.05, 0.2), (1.0, 2.2, 0.2)),

        # Add some more to check the adjustments. Notice that
        # these are nasty cases, as a very simple floor/ceil
        # with floating points fails some of these checks
        '1.27 no step': ((1.27, 1.27), (1.27, 1.27, NO_VALUE)),
        '1.27, 0.05': ((1.27, 1.27, 0.05), (1.25, 1.30, .05)),
        '1.29, 0.05': ((1.29, 1.29, 0.05), (1.25, 1.30, .05)),
        '1.30, 0.05': ((1.30, 1.30, 0.05), (1.30, 1.30, .05)),
        '-1.27, 0.05': ((-1.27, -1.27, 0.05), (-1.30, -1.25, .05)),
        '-1.29, 0.05': ((-1.29, -1.29, 0.05), (-1.30, -1.25, .05)),
        '-1.30, 0.05': ((-1.30, -1.30, 0.05), (-1.30, -1.30, .05)),
        '4.4, 0.2': ((4.4, 4.4, 0.2), (4.4, 4.4, 0.2)),
        '4.5, 0.2': ((4.5, 4.5, 0.2), (4.4, 4.6, 0.2)),
        '4.6, 0.2': ((4.6, 4.6, 0.2), (4.6, 4.6, 0.2)),
        '-4.4, 0.2': ((-4.4, -4.4, 0.2), (-4.6, -4.4, 0.2)),
        '-4.5, 0.2': ((-4.5, -4.5, 0.2), (-4.6, -4.4, 0.2)),
        '-4.6, 0.2': ((-4.6, -4.6, 0.2), (-4.6, -4.6, 0.2)),
        }

    def test_fixed(self):
        """Check correct creation of fixed IVShiftRange objects."""
        fixed = self._class.fixed(0.5)
        assert fixed == (0.5, 0.5, NO_VALUE)

    undef_step = {
        'coherent': ((-0.5, 1.9), 0.1, (-0.5, 1.9, 0.1)),
        'incoherent': ((-0.5, 1.9), 0.2, (-0.6, 2.0, 0.2)),
        'with step': ((-0.5, 1.9, 0.2), 0.1, (-0.6, 2.0, 0.2)),
        }

    @parametrize('ini_vals,step,expect', undef_step.values(), ids=undef_step)
    def test_set_undefined_step(self, ini_vals, step, expect):
        """Check correct setting of an undefined step."""
        original = self._class(*ini_vals)
        original.set_undefined_step(step)
        assert original == expect
