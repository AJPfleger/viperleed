"""Module symmetry_eps of viperleed.tleedmlib.classes.rparams.special.

Created on 2023-12-11

@author: Alexander Imre (@amimre)

Defines the class SymmetryEps, which is a float with optional z value.
"""

from ._base import SpecialParameter


# TODO: arithmetic operations return a float. This may be problematic.
# hash uses the default float implementation. This means that it cannot
# distinguish SymmetryEps(0.1) from SymmetryEps(0.1, 0.2)
# Dunder methods that may be needed: '__add__', '__eq__', '__floordiv__',
# '__ge__', '__gt__', '__hash__', '__le__', '__lt__', '__mod__', '__mul__',
# '__neg__', '__pos__', '__pow__', '__radd__', '__rdivmod__', '__rfloordiv__',
# '__rmod__', '__rmul__', '__round__', '__rpow__', '__rsub__', '__rtruediv__',
# '__sub__', '__truediv__'
# TODO: forbid negative values!

class SymmetryEps(float, SpecialParameter, param='SYMMETRY_EPS'):
    """SymmetryEps acts like a float but has an optional .z value.

    Used for interpreting the parameter SYMMETRY_EPS. The user
    can specify a second float value to be used for symmetry
    comparisons in the z direction (i.e., orthogonal to the
    surface). If no second value is given, the first value is
    used by default.
    """

    def __new__(cls, value, z=None):
        """Initialize instance."""
        try:
            float(value)
        except (ValueError, TypeError):
            raise TypeError('SymmetryEps value must be float') from None
        if z is not None:
            try:
                z = float(z)
            except (ValueError, TypeError):
                raise TypeError('SymmetryEps z value must be float') from None
        instance = super().__new__(cls, value)
        setattr(instance, '_z', z)
        return instance

    @property
    def z(self):  # pylint: disable=invalid-name
        """Return the z value of this SymmetryEps."""
        # About the disable: the member exists, it's created in __new__
        z_value = self._z  # pylint: disable=no-member
        if z_value is None:
            return float(self)
        return z_value
