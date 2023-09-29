# -*- coding: utf-8 -*-
"""Module base_slab of viperleed.tleedmlib.classes.slab.

Created on 2023-02-21, originally Jun 13 2019

@author: Florian Kraushofer (@fkraushofer)
@author: Michele Riva (@michele-riva)

Defines the BaseSlab class, useful to describe collections of atoms in
crystalline form. This is the abstract base class at the basis of both
BulkSlab and SurfaceSlab classes (for 3D- and 2D-periodic systems,
respectively), and contains generic functionality that is common to
both. This module contains refactored and modified functionality that
used to be contained in the original slab module by F. Kraushofer.
"""

from abc import ABC, abstractmethod
import copy
import itertools
import logging
from numbers import Real
import re

import numpy as np
import scipy.spatial as sps
from scipy.spatial import KDTree

from viperleed.tleedmlib import leedbase
from viperleed.tleedmlib.base import angle
from viperleed.tleedmlib.base import rotation_matrix, rotation_matrix_order
from viperleed.tleedmlib.classes.layer import Layer
from viperleed.tleedmlib.classes.sitetype import Sitetype

from .slab_errors import InvalidUnitCellError


_LOGGER = logging.getLogger('tleedm.slab')


# TODO: would it make sense to have cartpos[2] go the other way? Watch out for the
#       "reference" z in LEED that should always be the z of the topmost atom AFTER REFCALC
#       Could store the top_z, then have a .leed_pos attribute that returns top_z - cartpos[2]
# TODO: too-many-instance-attributes
# TODO: layer coordinates may not be up to date after we do update_origin
# TODO: a huge fraction of the time spent when dealing with slab symmetry
#       operations is actually taken up by calls to deepcopy. It would help
#       quite a bit to have a .light_copy(which_purpose) method that makes
#       appropriate copies of selected parts of the slab. Most of the times,
#       we only need ucell and some lightweight version of atlist (maybe as
#       a tuple of lightweight Atoms that do not hold references to this slab).
class BaseSlab(ABC):
    """An abstract base class representing a solid.

    Contains unit cell, element information and atom coordinates.
    Also has a variety of convenience functions for manipulating
    and updating the atoms.

    Attributes
    ----------
    ucell : np.array
        The unit cell as vectors a, b, c (columns)
    poscar_scaling : float
        The original scaling factor from POSCAR
    elements : tuple of str
        Element labels as read from POSCAR
    chemelem : list of str
        Chemical elements in the slab, including from `ELEMENT_MIX`
    n_per_elem : dict {str: int}
        The number of atoms per POSCAR element.
    atlist : list of Atom
        List of all atoms in the slab.
    layers : list of Layer
        List of Layer objects, where each `layer` is a composite
        of sublayers, as in TensErLEED
    sublayers : list of Layer
        List of Layer objects, each containing atoms of equal
        element and Z coordinate
    sitelist : list of Sitetype
        List of distinct sites as Sitetype, storing information
        on vibration and concentration
    ucell_mod : list of tuples (str, numpy.ndarray)
        Stored modifications made to the unit cell; each is a tuple
        of (type, array), where type is 'lmul', 'rmul', or 'add'
    topat_ori_z : float
        Stores the original position of the topmost atom in Cartesian
        coordinates
    celltype : str                                                              # TODO: would be nicer with an Enum
        Unit-cell shape as string. Values: 'oblique', 'rhombic',
        'rectangular', 'square', 'hexagonal'
    planegroup : str
        Symmetry group of the slab. May be reduced by the user
        relative to `foundplanegroup`.
    foundplanegroup : str
        Highest symmetry found. Doesn't get modified when user
        reduces symmetry manually.
    orisymplane : SymPlane
        Only stored if the `planegroup` is ambiguous as to which unit
        vector the symmetry plane at the origin is parallel to
    linklists : list of list of Atom
        List of lists of atoms which are linked by a symmetry operation
    layers_initialized : bool
        Set by self.createLayers
    sites_initialized : bool
        Set by self.initSites
    symbaseslab : Slab or None
        Slab with the smallest in-plane unit-cell area that shows
        the full symmetry of the slab.
    bulk_screws : list of int
        Integer list of rotation orders present in the bulk.
    bulk_glides : list of SymPlane
        List of glide-symmetry planes present in the bulk.
    """

    def __init__(self):
        """Initialize instance."""
        self.ucell = np.array([])                                               # base
        self.poscar_scaling = 1.                                                # base
        self.chemelem = set()                                                   # base
        self.n_per_elem = {}                                                    # base
        self.atlist = []                                                        # base
        self.layers = []                                                        # base
        self.sublayers = []                                                     # base
        self.sitelist = []                                                      # base
        self.ucell_mod = []                                                     # base
        self.ucell_ori = np.array([])                                           # base
        self.topat_ori_z = None                                                 # base (non-bulk after we fix the cartpos[2] flip)
        self.celltype = 'unknown'                                               # base
        self.planegroup = 'unknown'                                             # base
        self.foundplanegroup = 'unknown'                                        # base
        self.orisymplane = None                                                 # base
        self.linklists = []                                                     # base?
        self.symbaseslab = None                                                 # non-bulk?
        self.bulkslab = None  # Deleted in BulkSlab.__init__

        # Remember the last value of the ELEMENT_MIX parameter that
        # was applied. Prevents repeated applications
        self.last_element_mix = None                                            # base?

        # Some not-so-useful attributes that will soon be removed
        self.layers_initialized = False
        self.sites_initialized = False

    @property
    def angle_between_ucell_and_coord_sys(self):
        """Return angle between first unit-cell vector and coordinate system.

        Returns
        -------
        angle : float
            Angle between first slab unit cell vector and Cartesian
            coordinate system in degrees.

        Raises
        ------
        InvalidUnitCellError
            If this property is accessed before there is a unit cell
            defined.
        """
        a_vec, *_ = self.surface_vectors
        # NB: arctan2 requires (y, x) order
        return np.degrees(np.arctan2(a_vec[1], a_vec[0]))

    @property
    def elements(self):
        """Return a tuple of elements in this slab, as originally read."""
        return tuple(self.n_per_elem.keys())

    @property
    @abstractmethod
    def is_bulk(self):
        """Return whether this is a bulk slab."""
        return False

    #                                                                           TODO: remove. Used only once. Also confusing because it's only in-plane
    @property
    def reciprocal_vectors(self):
        """Returns the reciprocal lattice vectors as an array.

        Reciprocal vectors are defined by
        $a_i \dot$ b_j = 2\pi\delta_{ij}$.
        We need to transpose here again, because of swap row <-> col
        when going between real and reciprocal space.
        TensErLEED always does this calculation explicitly and
        normalizes to area, but here the inverse already contains a
        factor of 1/det.

        Returns
        -------
        np.ndarray, shape=(2, 2)
            Array of *reciprocal* lattice vectors *as rows*.
        """
        return 2*np.pi*np.linalg.inv(self.surface_vectors).T

    # @property
    # def ab_cell(self):
    @property
    def surface_vectors(self):
        """Return the 2D portion of the unit cell."""
        try:
            return self.ucell[:2, :2].T
        except IndexError:  # Uninitialized
            raise InvalidUnitCellError(
                f'{type(self).__name__} has no unit cell defined'
                ) from None

    @classmethod
    def from_slab(cls, other):
        """Return a `cls` instance with attributes deep-copied from `other`."""
        if not isinstance(other, BaseSlab):
            raise TypeError(f'{cls.__name__}.from_slab: other is not a slab.')
        if type(other) is cls:
            return copy.deepcopy(other)

        instance = cls()
        memo = {id(other): instance}
        for attr, value in other.__dict__.items():
            if not hasattr(instance, attr):
                # Skip attributes that do not belong to cls instances
                continue
            setattr(instance, attr, copy.deepcopy(value, memo))
        return instance

    def addBulkLayers(self, rp, n=1):
        """Returns a copy of the slab with n bulk units appended at the
        bottom, and a list of the new atoms that were added."""
        ts = copy.deepcopy(self) # temporary slab
        newbulkats = []
        duplicated = []
        zdiff = 0.
        for _ in range(n):
            blayers = [lay for lay in ts.layers if lay.isBulk]
            if isinstance(rp.BULK_REPEAT, np.ndarray):
                bulkc = np.copy(rp.BULK_REPEAT)
                if bulkc[2] < 0:
                    # perhaps vector given from surface to bulk instead of reverse...
                    bulkc = -bulkc
            else:
                cvec = ts.ucell[:, 2]
                if zdiff == 0. and rp.BULK_REPEAT is None:
                    # assume that interlayer vector from bottom non-bulk to top
                    # bulk layer is the same as between bulk units
                    zdiff = (blayers[-1].cartbotz
                             - ts.layers[blayers[0].num-1].cartbotz)
                elif zdiff == 0. and isinstance(rp.BULK_REPEAT,
                                                (float, np.floating)):
                    zdiff = rp.BULK_REPEAT
                bulkc = cvec * zdiff / cvec[2]
            ts.getCartesianCoordinates()
            cfact = (ts.ucell[2, 2] + abs(bulkc[2])) / ts.ucell[2, 2]
            ts.ucell[:, 2] = ts.ucell[:, 2] * cfact
            bulkc[2] = -bulkc[2]
            original_atoms = ts.atlist[:] # all atoms before adding layers

            # split bulkc into parts parallel and orthogonal to unit cell c
            # this allows to keep the same ucell and shift correctly the new bulk layers
            c_direction = ts.ucell[:, 2] / np.dot(ts.ucell[:, 2], ts.ucell[:, 2])
            bulkc_project_to_c = np.dot(bulkc, ts.ucell[:, 2]) * c_direction
            bulkc_perp_to_c = bulkc - bulkc_project_to_c
            added_this_loop = []
            for at in original_atoms:
                if at.layer.isBulk and at not in duplicated:
                    new_atom = at.duplicate()
                    newbulkats.append(new_atom)
                    duplicated.append(at)
                    added_this_loop.append(new_atom)
                    new_atom.oriN = len(ts.atlist)

                # old atoms get shifted up along ucell c
                at.cartpos += bulkc_project_to_c
            for at in added_this_loop:
                # new atoms get shifted perpendicular to ucell c
                at.cartpos -= bulkc_perp_to_c
            # TODO: could be done outside loop?
            ts.collapseCartesianCoordinates(updateOrigin=True)
            ts.sortOriginal()
        return ts, newbulkats

    # def check_a_b_in_plane(self):
    def check_a_b_out_of_plane(self):
        """Raise InvalidUnitCellError if a, b have out-of-plane components."""
        if any(self.ucell[2, :2]):
            _err = ('Unit cell a and b vectors must not '
                    'have an out-of-surface (Z) component!')
            _LOGGER.error(_err)
            raise InvalidUnitCellError(_err)

    def createLayers(self, rparams, bulk_cuts=[]):
        """Creates a list of Layer objects based on the N_BULK_LAYERS and
        LAYER_CUTS parameters in rparams. If layers were already defined,
        overwrite. The bulk_cuts kwarg allows specifically inserting
        automatically detected bulk layer cuts. Returns the cuts as a sorted
        list of floats."""
        # first interpret LAYER_CUTS parameter - can be a list of strings
        self.check_a_b_out_of_plane()

        if self.is_bulk:
            bulk_cuts = ()

        ct = []
        rgx = re.compile(r'\s*(dz|dc)\s*\(\s*(?P<cutoff>[0-9.]+)\s*\)')
        al = self.atlist[:]
        al.sort(key=lambda atom: atom.pos[2])
        for (i, s) in enumerate(rparams.LAYER_CUTS):
            if type(s) == float:
                ct.append(s)
                continue
            s = s.lower()
            if 'dz' in s or 'dc' in s:
                m = rgx.match(s)
                if not m:
                    _LOGGER.warning('Error parsing part of LAYER_CUTS: ' + s)
                    continue
                cutoff = float(m.group('cutoff'))
                lowbound = 0.
                if bulk_cuts:
                    lowbound = max(bulk_cuts)
                highbound = 1.
                val = None
                if (i > 1) and (rparams.LAYER_CUTS[i-1] in ['<', '>']):
                    try:
                        val = float(rparams.LAYER_CUTS[i-2])
                    except ValueError:
                        _LOGGER.warning('LAYER_CUTS: Error parsing left-hand '
                                        'boundary for ' + s)
                    if val is not None:
                        if rparams.LAYER_CUTS[i-1] == '<':
                            lowbound = val
                        else:
                            highbound = val
                if i < len(rparams.LAYER_CUTS) - 2 and (rparams.LAYER_CUTS[i+1]
                                                        in ['<', '>']):
                    try:
                        val = float(rparams.LAYER_CUTS[i+2])
                    except ValueError:
                        _LOGGER.warning('LAYER_CUTS: Error parsing right-hand '
                                        'boundary for ' + s)
                    if val is not None:
                        if rparams.LAYER_CUTS[i+1] == '>':
                            lowbound = val
                        else:
                            highbound = val
                if 'dc' in s:
                    cutoff *= (self.ucell[2, 2]
                               / np.linalg.norm(self.ucell[:, 2]))
                for i in range(1, len(al)):
                    if ((abs(al[i].cartpos[2]-al[i-1].cartpos[2]) > cutoff)
                            and al[i].pos[2] > lowbound
                            and al[i].pos[2] < highbound
                            and al[i-1].pos[2] > lowbound
                            and al[i-1].pos[2] < highbound):
                        ct.append(abs((al[i].pos[2]+al[i-1].pos[2])/2))
            elif s not in ['<', '>']:
                try:
                    ct.append(float(s))
                except ValueError:
                    _LOGGER.warning('LAYER_CUTS: Could not parse value: ' + s)
                    continue
        if bulk_cuts:
            ct = [v for v in ct if v > max(bulk_cuts) + 1e-6] + bulk_cuts
        ct.sort()
        self.layers = []
        tmplist = self.atlist[:]
        self.sort_by_z()
        laynum = 0
        b = True if rparams.N_BULK_LAYERS > 0 else False
        newlayer = Layer(self, 0, b)
        self.layers.append(newlayer)
        for atom in self.atlist:
            # only check for new layer if we're not in the top layer already
            if laynum < len(ct):
                if atom.pos[2] > ct[laynum]:
                    # if atom is higher than the next cutoff, make a new layer
                    laynum += 1
                    b = True if rparams.N_BULK_LAYERS > laynum else False
                    newlayer = Layer(self, laynum, b)
                    self.layers.append(newlayer)
                    check = True    # check for empty layer
                    while check:
                        if laynum >= len(ct):
                            check = False
                        elif atom.pos[2] <= ct[laynum]:
                            check = False
                        else:
                            laynum += 1
                            b = (True if rparams.N_BULK_LAYERS > laynum
                                 else False)
                            newlayer = Layer(self, laynum, b)
                            self.layers.append(newlayer)
            atom.layer = newlayer
            newlayer.atlist.append(atom)
        dl = []
        for layer in self.layers:
            if not layer.atlist:
                _LOGGER.warning('A layer containing no atoms was found. Layer '
                                'will be deleted. Check LAYER_CUTS parameter.')
                rparams.setHaltingLevel(2)
                dl.append(layer)
        for layer in dl:
            if layer.isBulk:
                self.layers[layer.num+1].isBulk = True
            self.layers.remove(layer)
            del layer
        self.layers.reverse()
        for i, layer in enumerate(self.layers):
            layer.getLayerPos()
            layer.num = i
        self.atlist = tmplist
        self.layers_initialized = True
        return ct

    def createSublayers(self, eps=0.001):
        """Sorts the atoms in the slab into sublayers, sorted by element and Z
        coordinate."""
        self.sort_by_z()
        subl = []  # will be a list of sublayers, using the Layer class
        for el in self.elements:
            sublists = [[a for a in self.atlist if a.el == el]]
            # first, split at points where two atoms are more than eps apart
            i = 0
            while i < len(sublists):
                brk = False
                if len(sublists[i]) > 1:
                    tmplist = sublists[i][:]
                    for j in range(1, len(tmplist)):
                        if (abs(tmplist[j].cartpos[2]
                                - tmplist[j-1].cartpos[2]) > eps):
                            sublists.append(tmplist[:j])
                            sublists.append(tmplist[j:])
                            sublists.pop(i)
                            brk = True
                            break
                    if not brk:
                        i += 1
                else:
                    i += 1
            # now, go through again and split sublayers at greatest interlayer
            #   distance, if they are too thick overall
            i = 0
            while i < len(sublists):
                brk = False
                if len(sublists[i]) > 1:
                    if abs(sublists[i][0].cartpos[2]
                           - sublists[i][-1].cartpos[2]) > eps:
                        maxdist = abs(sublists[i][1].cartpos[2]
                                      - sublists[i][0].cartpos[2])
                        maxdistindex = 1
                        for j in range(2, len(sublists[i])):
                            d = abs(sublists[i][j].cartpos[2]
                                    - sublists[i][j-1].cartpos[2])
                            if d > maxdist:
                                maxdist = d
                                maxdistindex = j
                        sublists.append(sublists[i][:maxdistindex])
                        sublists.append(sublists[i][maxdistindex:])
                        sublists.pop(i)
                        brk = True
                else:
                    i += 1
                if not brk:
                    i += 1
            # now, create sublayers based on sublists:
            for ls in sublists:
                newsl = Layer(self, 0, sublayer=True)
                subl.append(newsl)
                newsl.atlist = ls
                newsl.cartbotz = ls[0].cartpos[2]
        self.sublayers = []
        subl.sort(key=lambda sl: -sl.cartbotz)
        while subl:
            acc = [subl.pop()]  # accumulate sublayers with same z
            while subl:
                if abs(subl[-1].cartbotz - acc[0].cartbotz) < eps:
                    acc.append(subl.pop())
                else:
                    break
            acc.sort(key=lambda sl: sl.atlist[0].el)  # sort by element
            self.sublayers.extend(acc)
        for (i, sl) in enumerate(self.sublayers):
            sl.num = i

    def collapseCartesianCoordinates(self, updateOrigin=False):
        """Finds atoms outside the parallelogram spanned by the unit vectors
        a and b and moves them inside. If keepOriZ is True, the old value of
        the top atom position will be preserved.."""
        self.getFractionalCoordinates()
        self.collapseFractionalCoordinates()
        self.getCartesianCoordinates(updateOrigin=updateOrigin)

    def collapseFractionalCoordinates(self):
        """Finds atoms outside the parallelogram spanned by the unit vectors
        a and b and moves them inside."""
        for at in self.atlist:
            at.pos = at.pos % 1.0

    # def full_update(self, rparams):
    def fullUpdate(self, rpars):
        """readPOSCAR initializes the slab with information from POSCAR;
        fullUpdate re-initializes the atom list, then uses the information
        from the parameters file to create layers, calculate cartesian
        coordinates (absolute and per layer), and to update elements and
        sites."""
        self.collapseFractionalCoordinates()
        self.getCartesianCoordinates()
        if not self.layers_initialized:
            self.createLayers(rpars)
        self.updateElements(rpars)
        if not self.sites_initialized:
            self.initSites(rpars)
        if rpars.fileLoaded['VIBROCC']:
            for at in self.atlist:
                at.initDisp()

    @abstractmethod
    def getBulkRepeat(self, rp):
        """Based on a pre-existing definition of the bulk, tries to identify
        a repeat vector for which the bulk matches the slab above. Returns that
        vector in cartesian coordinates, or None if no match is found."""

    def getCartesianCoordinates(self, updateOrigin=False):
        """Assigns absolute cartesian coordinates to all atoms, with x,y using
        the unit cell (top plane), while z = 0 for the topmost atom and
        positive going down through the slab. If updateOrigin is set True, the
        cartesian origin relative to the fractional origin will be updated,
        otherwise it is static."""
        al = self.atlist[:]     # temporary copy
        al.sort(key=lambda atom: atom.pos[2])
        topat = al[-1]
        topcart = np.dot(self.ucell, topat.pos)
        if updateOrigin or self.topat_ori_z is None:
            self.topat_ori_z = topcart[2]
        for atom in al:
            atom.cartpos = np.dot(self.ucell, atom.pos)
            atom.cartpos[2] = self.topat_ori_z - atom.cartpos[2]

    def getFractionalCoordinates(self):
        """Calculates fractional coordinates for all atoms from their
        cartesian coordinates, using the slab unit cell."""
        uci = np.linalg.inv(self.ucell)
        for at in self.atlist:
            tp = np.copy(at.cartpos)
            tp[2] = self.topat_ori_z-tp[2]
            at.pos = np.dot(uci, tp)

    # @property
    # def fewest_atoms_sublayer(self):
    def getLowOccLayer(self):
        """Finds and returns the lowest occupancy sublayer"""
        minlen = len(self.sublayers[0].atlist)
        lowocclayer = self.sublayers[0]
        for lay in self.sublayers:
            if len(lay.atlist) < minlen:
                lowocclayer = lay
                minlen = len(lay.atlist)
        return lowocclayer

    def getMinLayerSpacing(self):
        """Returns the minimum distance (cartesian) between two layers in the
        slab. Returns zero if there is only one layer, or none are defined."""
        if len(self.layers) < 2:
            return 0
        self.getCartesianCoordinates()
        return min([(self.layers[i].cartori[2] - self.layers[i-1].cartbotz)
                    for i in range(1, len(self.layers))])

    def getMinUnitCell(self, rp, warn_convention=False):
        """Check if there is a 2D unit cell smaller than the current one.

        Parameters
        ----------
        rp : RunParams
            The current parameters. The only attributes
            used are SYMMETRY_EPS and SYMMETRY_EPS_Z.
        warn_convention : bool, optional
            If True, warnings are added to the current
            logger in case making the reduced unit cell
            stick to the conventions would result in a
            sub-optimal superlattice matrix. Default is
            False.

        Returns
        -------
        can_be_reduced : bool
            True if there is a smaller 2D unit cell. The
            unit cell is considered minimizable if there
            is a mincell with area smaller than the one
            of the current cell. A lower limit for the
            area of mincell is taken as 1 A**2.
        mincell : np.ndarray
            The minimal 2D unit cell, if it can be reduced,
            otherwise the current one. Notice that mincell is
            such that (a, b) = mincell, i.e., it is transposed
            with respect to self.ucell.
        """
        # TODO: write a testcase for the reduction of POSCAR Sb on Si(111)
        eps = rp.SYMMETRY_EPS
        epsz = rp.SYMMETRY_EPS_Z
        abst = self.ucell[:2, :2].T

        # Create a test slab: C projected to Z
        ts = copy.deepcopy(self)
        ts.projectCToZ()
        ts.sort_by_z()
        ts.createSublayers(epsz)

        # Use the lowest-occupancy sublayer (the one
        # with fewer atoms of the same site type)
        lowocclayer = ts.getLowOccLayer()
        n_atoms = len(lowocclayer.atlist)
        if n_atoms < 2:
            # Cannot be smaller if there's only 1 atom
            return False, abst

        # Create a list of candidate translation vectors, selecting
        # only those for which the slab is translation symmetric
        plist = [at.cartpos[0:2] for at in lowocclayer.atlist]
        vlist = ((p1 - p2) for (p1, p2) in itertools.combinations(plist, 2))
        tvecs = [v for v in vlist if ts.isTranslationSymmetric(v, eps)]
        if not tvecs:
            return False, abst

        # Now try to reduce the cell: test whether we can use a pair of
        # vectors from [a, b, *tvecs] to make the cell smaller. Keep in
        # mind that with n_atoms, we cannot reduce the area by more than
        # a factor 1/n_atoms (which would give 1 atom per mincell).
        mincell = abst.copy()
        mincell_area = abs(np.linalg.det(mincell))
        smaller = False
        smallest_area = mincell_area / n_atoms
        for vec in tvecs:
            # Try first replacing the current second unit vector
            tcell = np.array([mincell[0], vec])
            tcell_area = abs(np.linalg.det(tcell))
            if (tcell_area >= smallest_area - eps**2
                    and tcell_area < mincell_area - eps**2):
                mincell = tcell
                mincell_area = tcell_area
                smaller = True
                continue

            # Try replacing the current first unit vector instead
            tcell = np.array([mincell[1], vec])
            tcell_area = abs(np.linalg.det(tcell))
            if (tcell_area >= smallest_area - eps**2
                    and tcell_area < mincell_area - eps**2):
                mincell = tcell
                mincell_area = tcell_area
                smaller = True

        if not smaller:
            return False, abst

        # Use Minkowski reduction to make mincell high symmetry
        mincell, _, _ = leedbase.reduceUnitCell(mincell)

        # Cosmetic corrections
        if abs(mincell[0, 0]) < eps and abs(mincell[1, 1]) < eps:
            # Swap a and b when matrix is off-diagonal
            mincell[[0, 1]] = mincell[[1, 0]]
        if abs(mincell[1, 0]) < eps and abs(mincell[0, 1]) < eps:
            # If matrix is diagonal, make elements positive
            mincell = abs(mincell)
        # By convention, make the shorter vector the first one
        if np.linalg.norm(mincell[0]) > np.linalg.norm(mincell[1]) + eps:
            if abs(mincell[1, 0]) < eps and abs(mincell[0, 1]) < eps:
                # if matrix is diagonal, DO NOT make it off-diagonal
                if warn_convention:
                    _LOGGER.warning(
                        'The unit cell orientation does not follow '
                        'standard convention: to keep SUPERLATTICE matrix '
                        'diagonal, the first bulk vector must be larger '
                        'than the second. Consider swapping the unit cell '
                        'vectors.'
                        )
            else:
                mincell = np.dot([[0, 1], [-1, 0]], mincell)
        # Finally, make sure it's right-handed
        if angle(mincell[0], mincell[1]) < 0:
            mincell = np.dot([[1, 0], [0, -1]], mincell)
        return True, mincell

    def getNearestNeigbours(self):
        """Returns a list listing the nearest neighbor distance for all atoms in the slab taking periodic
        boundary conditions into account. For this calculation, the cell is internally expanded into a supercell."""

        #unit vectors
        a = self.ucell[:,0] # vector a
        b = self.ucell[:,1] # vector b

        # Compare unit vector lengths and decide based on this how many cells to add around
        # A minimum 3x3 supercell is constructed for nearest neighbor query, but may be exteneded if vector lengths
        # are very different
        max_length = max(np.linalg.norm(a), np.linalg.norm(b))
        i = np.ceil(max_length/np.linalg.norm(a))
        j = np.ceil(max_length/np.linalg.norm(b))

        # Makes supercell minimum size 3x3 original
        transform = np.array([[2*i+1,0],
                              [0,2*j+1]])
        supercell = self.makeSupercell(transform)


        atom_coords = [atom.cartpos for atom in supercell.atlist] # Atom coordinates in supercell
        # For NN query use KDTree from scipy.spacial
        tree = KDTree(atom_coords)

        NN_dict = {} # Dict containing Atom and NN will be returned

        # Now query atoms in center cell for NN distances and save to dict
        for atom in self.atlist:
            coord = atom.cartpos
            coord += (i+1)*a + (j+1)*b # central cell

            dists, _ = tree.query(coord,k=2) # second argument irrelevant; would be index of NN atoms (supercell, not original!)
            NN_dict[atom] = dists[1] # element 0 is distance to atom itself (< 1e-15)

        return NN_dict

    def initSites(self, rp):
        """Goes through the atom list and supplies them with appropriate
        SiteType objects, based on the SITE_DEF parameters from the supplied
        Rparams."""
        atlist = self.atlist[:]     # copy to not have any permanent changes
        atlist.sort(key=lambda atom: atom.oriN)
        sl = []
        for el in rp.SITE_DEF:
            for sitename in rp.SITE_DEF[el]:
                newsite = Sitetype(el, sitename)
                sl.append(newsite)
                for i in rp.SITE_DEF[el][sitename]:
                    try:
                        if atlist[i-1].el != el:
                            _LOGGER.warning(
                                'SITE_DEF tries to assign atom number '
                                + str(i) + ' as ' + el + ', but POSCAR has it '
                                'as '+atlist[i-1].el+'. Atom will be skipped '
                                'and left as default site type!')
                            rp.setHaltingLevel(1)
                        else:
                            atlist[i-1].site = newsite
                    except IndexError:
                        _LOGGER.error('SITE_DEF: atom number out of bounds.')
                        raise
        for el in self.elements:
            newsite = Sitetype(el, 'def')
            found = False
            for at in atlist:
                if at.el == el and at.site is None:
                    at.site = newsite
                    found = True
            if found:
                sl.append(newsite)
        for site in [s for s in sl if s.el in rp.ELEMENT_MIX]:
            site.mixedEls = rp.ELEMENT_MIX[site.el][:]
        self.sitelist = sl
        self.sites_initialized = True

    def isEquivalent(self, slab, eps=0.001):
        """Compares the slab to another slab, returns True if all atom cartpos
        match (with at least one other atom, if there are duplicates), False
        if not. Both slabs are copied and collapsed to the (0,0) cell
        before."""
        slab1 = copy.deepcopy(self)
        slab2 = copy.deepcopy(slab)
        slab1.collapseCartesianCoordinates()
        slab2.collapseCartesianCoordinates()
        # reorder sublayers by Z to then compare by index
        slab1.sublayers.sort(key=lambda sl: sl.cartbotz)
        slab2.sublayers.sort(key=lambda sl: sl.cartbotz)
        ab = self.ucell[:2, :2]
        for (i, sl) in enumerate(slab1.sublayers):
            if (len(sl.atlist) != len(slab2.sublayers[i].atlist)
                    or abs(sl.cartbotz-slab2.sublayers[i].cartbotz) > eps
                    or sl.atlist[0].el != slab2.sublayers[i].atlist[0].el):
                return False
            for at1 in sl.atlist:
                complist = [at1.cartpos[0:2]]
                # if we're close to an edge or corner, also check translations
                for j in range(0, 2):
                    releps = eps / np.linalg.norm(ab[:, j])
                    if abs(at1.pos[j]) < releps:
                        complist.append(at1.cartpos[:2] + ab[:, j])
                    if abs(at1.pos[j]-1) < releps:
                        complist.append(at1.cartpos[:2] - ab[:, j])
                if len(complist) == 3:
                    # coner - add the diagonally opposed one
                    complist.append(complist[1] + complist[2] - complist[0])
                found = False
                for at2 in slab2.sublayers[i].atlist:
                    for p in complist:
                        if np.linalg.norm(p-at2.cartpos[0:2]) < eps:
                            found = True
                            break
                    if found:
                        break
                if not found:
                    return False
        return True

    # def makeSupercell(self, transform):                                         # surface only?
    def makeSupercell(self, transform):
        """Returns a copy of the slab with the unit cell transformed by the
        given integer-valued, (2x2) transformation matrix."""
        if np.any(abs(np.round(transform) - transform) > 1e-6):
            raise ValueError('Slab.makeSupercell: transformation matrix '
                             'contains non-integer elements')
        transform = np.round(transform).astype(int)
        transformSize = int(round(abs(np.linalg.det(transform))))
        ts = copy.deepcopy(self)
        if transformSize > 1:
            transformDiag = [1, 1]
            if np.max(transform[:, 0]) > np.max(transform[:, 1]):
                longSide = 0
            else:
                longSide = 1
            transformDiag[longSide] = np.max(transform)
            while transformSize / transformDiag[longSide] % 1 != 0:
                transformDiag[longSide] -= 1
            transformDiag[1-longSide] = int(transformSize
                                            / transformDiag[longSide])
            cpatlist = ts.atlist[:]
            for at in cpatlist:
                for i in range(0, transformDiag[0]):
                    for j in range(0, transformDiag[1]):
                        if i == j == 0:
                            continue
                        tmpat = at.duplicate() # duplicate saves duplicated atom in slab
                        tmpat.pos[0] += i
                        tmpat.pos[1] += j
        ts.resetAtomOriN()
        ts.getCartesianCoordinates(updateOrigin=True)
        tm = np.identity(3, dtype=float)
        tm[:2, :2] = transform
        ts.ucell = np.transpose(np.dot(tm, np.transpose(ts.ucell)))
        ts.getFractionalCoordinates()
        ts.getCartesianCoordinates(updateOrigin=True)
        return ts

    def makeSymBaseSlab(self, rp, transform=None):
        """Copies self to create a symmetry base slab by collapsing to the
        cell defined by rp.SYMMETRY_CELL_TRANSFORM, then removing duplicates.
        Also assigns the duplicateOf variable for all atoms in self.atlist.
        By default, the transformation matrix will be taken from rp, but a
        different matrix can also be passed."""
        ssl = copy.deepcopy(self)
        ssl.resetSymmetry()
        ssl.getCartesianCoordinates()
        # reduce dimensions in xy
        transform3 = np.identity(3, dtype=float)
        if transform is not None:
            transform3[:2, :2] = transform
        else:
            transform3[:2, :2] = rp.SYMMETRY_CELL_TRANSFORM
        ssl.ucell = np.dot(ssl.ucell, np.linalg.inv(np.transpose(transform3)))
        ssl.collapseCartesianCoordinates(updateOrigin=True)
        ssl.ucell_mod = []
        # if self.ucell_mod is not empty, don't drag that into the new slab.
        # remove duplicates
        ssl.createSublayers(rp.SYMMETRY_EPS_Z)
        newatlist = []
        for subl in ssl.sublayers:
            i = 0
            while i < len(subl.atlist):
                j = i+1
                baseat = [a for a in self.atlist
                          if a.oriN == subl.atlist[i].oriN][0]
                while j < len(subl.atlist):
                    if subl.atlist[i].isSameXY(subl.atlist[j].cartpos[:2],
                                               eps=rp.SYMMETRY_EPS):
                        for a in [a for a in self.atlist
                                  if a.oriN == subl.atlist[j].oriN]:
                            a.duplicateOf = baseat
                        subl.atlist.pop(j)
                    else:
                        j += 1
                i += 1
            newatlist.extend(subl.atlist)
        ssl.atlist = newatlist
        ssl.updateElementCount()   # update number of atoms per element again
        # update the layers. Don't use Slab.createLayers here to keep it
        #   consistent with the slab layers
        for i, layer in enumerate(ssl.layers):
            layer.slab = ssl
            layer.getLayerPos()
            layer.num = i
            layer.atlist = [at for at in layer.atlist if at in ssl.atlist]
        return ssl

    def projectCToZ(self):
        """makes the c vector of the unit cell perpendicular to the surface,
        changing all atom coordinates to fit the new base"""
        if self.ucell[0, 2] != 0.0 or self.ucell[1, 2] != 0.0:
            self.getCartesianCoordinates()
            self.ucell[:, 2] = np.array([0, 0, self.ucell[2, 2]])
            self.collapseCartesianCoordinates()
            # implicitly also gets new fractional coordinates

    # def reset_symmetry(self):                                                   # base? NOT A GREAT NAME. The ucell_ori is changed to the current cell!
        # """Set all symmetry information back to default values."""
    def resetSymmetry(self):
        """Sets all symmetry information back to default values."""
        self.ucell_mod = []
        # self.ucell_ori = self.ucell.copy()
        self.ucell_ori = self.ucell
        self.celltype = 'unknown'
        self.foundplanegroup = self.planegroup = 'unknown'
        self.orisymplane = None

    # def update_atom_numbers(self):
    def resetAtomOriN(self):
        """Gets new 'original' numbers for atoms in the slab. If a bulkslab
        is defined, also updates the numbers there to keep the two consistent.
        """
        self.sortOriginal()
        self.sort_by_element()
        bulkAtsRenumbered = []
        for (i, at) in enumerate(self.atlist):
            if self.bulkslab is not None:
                for bat in [a for a in self.bulkslab.atlist
                            if a.oriN == at.oriN
                            and a not in bulkAtsRenumbered]:
                    bat.oriN = i+1
                    bulkAtsRenumbered.append(bat)
            at.oriN = i+1

    def revertUnitCell(self, restoreTo=None):
        """If the unit cell in a and b was transformed earlier, restore the
        original form and coordinates. If a 'restoreTo' argument is passed,
        restore only back to the point defined by the argument."""
        if restoreTo is None:
            restoreTo = []
        if len(self.ucell_mod) > 0:
            self.getCartesianCoordinates()
            oplist = self.ucell_mod[len(restoreTo):]
            for op in list(reversed(oplist)):
                if op[0] == 'add':
                    for at in self.atlist:
                        at.cartpos[0:2] -= op[1]
                    self.collapseCartesianCoordinates()
                elif op[0] == 'lmul':
                    self.ucell = np.dot(np.linalg.inv(op[1]), self.ucell)
                    self.collapseCartesianCoordinates()
                elif op[0] == 'rmul':
                    self.ucell = np.dot(self.ucell, np.linalg.inv(op[1]))
                    self.collapseCartesianCoordinates()
            self.ucell_mod = self.ucell_mod[:len(restoreTo)]

    def sort_by_element(self):                                                  # TODO: this could be simplified using sets
        """Sorts atlist by elements, preserving the element order from the
        original POSCAR"""
        # unfortunately, simply calling the sort function by element does not
        #    preserve the element order from the POSCAR
        esortlist = sorted(self.atlist, key=lambda atom: atom.el)
        lastel = ''
        tmpElList = []
        isoLists = []
        # generate sub-lists isolated by elements
        for at in esortlist:
            if at.el != lastel:
                tmpElList.append(at.el)
                isoLists.append([])
                lastel = at.el
            isoLists[-1].append(at)
        sortedlist = []
        # going through the elements in the order they appear in POSCAR, find
        #   the corresponding index in tmpElList and append the atoms of that
        #   type to sorted list
        for el in self.elements:
            try:
                i = tmpElList.index(el)
            except ValueError:
                _LOGGER.error('Unexpected point encountered '
                              'in Slab.sort_by_element: '
                              'Could not find element in element list')
            else:
                sortedlist.extend(isoLists[i])
        self.atlist = sortedlist

    def sort_by_z(self, botToTop=False):
        """Sorts atlist by z coordinate"""
        self.atlist.sort(key=lambda atom: atom.pos[2])
        if botToTop:
            self.atlist.reverse()

    def sortOriginal(self):
        """Sorts atlist by original atom order from POSCAR"""
        self.atlist.sort(key=lambda atom: atom.oriN)

    def updateElementCount(self):
        """Updates the number of atoms per element."""
        updated_n_per_element = {}
        for el in self.elements:
            n = len([at for at in self.atlist if at.el == el])
            if n > 0:
                updated_n_per_element[el] = n
        self.n_per_elem = updated_n_per_element

    def updateElements(self, rp):
        """Updates elements based on the ELEMENT_MIX parameter, and warns in
        case of a naming conflict."""
        if self.last_element_mix == rp.ELEMENT_MIX:
            return     # don't update if up to date
        # update nelem
        c = 0
        oldels = self.elements[:]
        for i, pel in enumerate(oldels):
            if pel not in rp.ELEMENT_MIX:
                c += 1
            else:
                c += len(rp.ELEMENT_MIX[pel])
                # check for overlapping names:
                for el in rp.ELEMENT_MIX[pel]:
                    if el in oldels:
                        _LOGGER.warning(
                            'Element name '+el+' given in ELEMENT_MIX is also '
                            'an element name in POSCAR. It is recommended you '
                            'rename the element in the POSCAR file.')
        self.chemelem = []
        for el in self.elements:
            if el in rp.ELEMENT_MIX:
                self.chemelem.extend([e.capitalize()
                                      for e in rp.ELEMENT_MIX[el]
                                      if not e.capitalize() in self.chemelem])
            else:
                self.chemelem.append(el.capitalize())
        self.last_element_mix = rp.ELEMENT_MIX

    def updateLayerCoordinates(self):
        """Update the Cartesian position of all `layers`."""
        for layer in self.layers:
            layer.getLayerPos()

    # ----------------------  TRANSFORMATIONS  ------------------------

    def apply_matrix_transformation(self, trafo_matrix):
        """Apply an orthogonal transformation to the unit cell and all atoms.

        The transformation is given as an orthogonal transformation
        matrix (O) which is applied to BOTH the unit cell and all
        Cartesian atomic coordinates. The unit cell (U, unit vectors
        as columns) is transformed to U' = O @ U. Atomic coordinates
        (v, as column vectors) are transformed to v' = O @ v. This
        transformation is essentially equivalent to a change of basis.

        This method differs from  `rotateUnitCell`, `rotateAtoms`, and
        `mirror` in that the latter two only cause a rotation of the
        atoms, but not of the unit cell, whereas the former rotates the
        unit cell but not the atoms. Here both unit cell and atoms are
        transformed.

        If the transformation is an out-of-plane rotation/mirror (i.e.,
        it changes the z components of unit vectors), layers, bulkslab,
        and sublayers are discarded and will need to be recalculated.
        Otherwise, the same coordinate transform is also applied to
        the `bulkslab`, if present.

        Parameters
        ----------
        trafo_matrix : Sequence
            `trafo_matrix` must be an orthogonal 3-by-3 matrix.
            Contains the transformation matrix (O) describing
            the applied transformation.

        Raises
        ------
        ValueError
            If `trafo_matrix` is not 3-by-3 or not orthogonal.

        Examples
        --------
        Apply a rotation by 90 deg around the z axis to the unit cell
        (in positive direction, i.e. clockwise when looking along z)
        >>> theta = np.pi/2
        >>> rot_mat = [[np.cos(theta), -np.sin(theta), 0],
                       [np.sin(theta),  np.cos(theta), 0],
                       [0, 0, 1]]
        >>> slab.apply_matrix_transformation(rot_mat)
        """
        trafo_matrix = np.asarray(trafo_matrix)
        if trafo_matrix.shape != (3, 3):
            raise ValueError('apply_matrix_transformation: '
                             'not a 3-by-3 matrix')
        if not np.allclose(np.linalg.inv(trafo_matrix), trafo_matrix.T):
            raise ValueError('apply_matrix_transformation: matrix is not '
                             'orthogonal. Consider using apply_scaling.')

        # Determine whether trafo_matrix will change
        # the z component of the unit vectors
        changes_z = not np.allclose(trafo_matrix[2], (0, 0, 1))

        self.ucell = trafo_matrix.dot(self.ucell)
        self.ucell[abs(self.ucell) < 1e-5] = 0.
        self.getCartesianCoordinates(updateOrigin=changes_z)

        # Update also 'layers', sublayers and bulkslab: if the
        # transformation touched 'z' we invalidate everything
        if changes_z:
            self.layers.clear()
            self.sublayers.clear()

        if self.is_bulk:
            return

        if changes_z:
            self.bulkslab = None
        elif self.bulkslab:
            self.bulkslab.apply_matrix_transformation(trafo_matrix)

    def apply_scaling(self, *scaling):
        """Rescale the unit-cell vectors.

        This can be used to stretch/compress along unit cell vectors
        in order to change lattice constants in some direction or to
        apply an isotropic scaling in all directions. To apply other
        (orthogonal) transformations (e.g., rotation, flipping), use
        `apply_matrix_transformation`.

        The same scaling is also applied to `bulkslab`, if this slab
        has one.

        Parameters
        ----------
        *scaling : Sequence
            If only one number, an isotropic scaling is applied to
            the unit cell and atom positions. If a sequence with
            three entries, the scaling will be applied along the
            unit-cell vectors in the given order.

        Returns
        -------
        scaling_matrix : numpy.ndarray
            The matrix used for scaling the unit vectors.

        Raises
        ------
        TypeError
            If `scaling` has neither 1 nor three elements, or
            any of the elements is not a number.
        ValueError
            If `scaling` would make the unit cell singular
            (i.e., reduce the length of a unit vector to zero)

        Examples
        ----------
        Stretch the unit cell by a factor of 2 along a, b and c.
        This doubles the lattice constant and increases the volume
        8-fold:
        >>> slab.apply_scaling(2)

        Compresses the unit cell by a factor of 3 along c:
        >>> slab.apply_scaling(1, 1, 1/3)
        """
        if len(scaling) not in (1, 3):
            raise TypeError(f'{type(self).__name__}.apply_scaling: '
                            'invalid number of arguments. Expected '
                            f'one or three, got {len(scaling)}.')
        if not all(isinstance(s, Real) for s in scaling):
            raise TypeError(f'{type(self).__name__}.apply_scaling: '
                            f'invalid scaling factor. Expected one '
                            'or three numbers.')
        if len(scaling) == 1:
            scaling *= 3
        if any(abs(s) < 1e-5 for s in scaling):
            raise ValueError(f'{type(self).__name__}.apply_scaling: cannot '
                             'reduce unit vector(s) to zero length')

        # Apply to unit cell (basis). Notice the inverted order,
        # because the unit cell is stored with unit vectors as
        # columns (i.e., a = ucell[:, 0])
        scaling_matrix = np.diag(scaling)
        self.ucell = self.ucell.dot(scaling_matrix)
        self.getCartesianCoordinates(updateOrigin=scaling[2] != 1)

        try:
            self.bulkslab.apply_scaling(*scaling)
        except AttributeError:
            pass
        return scaling_matrix

    def mirror(self, symplane, glide=False):
        """Translates the atoms in the slab to have the symplane in the
        origin, applies a mirror or glide matrix, then translates back.
        Very inefficient implementation!"""
        ang = angle(symplane.dir, np.array([1, 0]))
        rotm = rotation_matrix(ang)
        rotmirm = np.dot(np.linalg.inv(rotm),
                         np.dot(np.array([[1, 0], [0, -1]]), rotm))
        # rotates to have plane in x direction, mirrors on x
        if glide:
            abt = self.ucell[:2, :2].T
            glidevec = (symplane.par[0]*abt[0]+symplane.par[1]*abt[1])/2
        else:
            glidevec = np.zeros(2)
        for at in self.atlist:
            at.cartpos[:2] -= symplane.pos     # translate to plane
            at.cartpos[:2] = np.dot(rotmirm, at.cartpos[:2])    # apply mirror
            at.cartpos[:2] += symplane.pos     # translate back
            at.cartpos[:2] += glidevec   # 0 if not glides

    def rotateAtoms(self, axis, order):
        """Translates the atoms in the slab to have the axis in the origin,
        applies an order-fold rotation matrix to the atom positions, then
        translates back"""
        self.getCartesianCoordinates()
        m = rotation_matrix_order(order)
        for at in self.atlist:
            # translate origin to candidate point, rotate, translate back
            at.cartpos[0:2] = np.dot(m, at.cartpos[0:2] - axis) + axis
        self.getFractionalCoordinates()

    def rotateUnitCell(self, order, append_ucell_mod=True):
        """Rotates the unit cell (around the origin), leaving atom positions
        the same. Note that this rotates in the opposite direction as
        rotateAtoms."""
        self.getCartesianCoordinates()
        m = rotation_matrix_order(order)
        m3 = np.identity(3, dtype=float)
        m3[:2, :2] = m
        self.ucell = np.dot(m3, self.ucell)
        if append_ucell_mod:
            self.ucell_mod.append(('lmul', m3))
        self.getFractionalCoordinates()

    # ----------------- SYMMETRY UPON TRANSFORMATION ------------------

    def isMirrorSymmetric(self, symplane, eps, glide=False):
        """Evaluates whether the slab is equivalent to itself when applying a
        mirror or glide operation at a given plane"""
        ang = angle(symplane.dir, np.array([1, 0]))
        rotm = rotation_matrix(ang)
        rotmirm = np.dot(np.linalg.inv(rotm),
                         np.dot(np.array([[1, 0], [0, -1]]), rotm))
        # rotates to have plane in x direction, mirrors on x
        ab = self.ucell[:2, :2]
        abt = ab.T
        releps = [eps / np.linalg.norm(abt[j]) for j in range(0, 2)]
        shiftv = symplane.pos.reshape(2, 1)
        if glide:
            glidev = ((symplane.par[0]*abt[0]+symplane.par[1]*abt[1])
                      / 2).reshape(2, 1)
        for sl in self.sublayers:
            coordlist = [at.cartpos[:2] for at in sl.atlist]
            shiftm = np.tile(shiftv, len(coordlist))  # shift all coordinates
            if glide:
                glidem = np.tile(glidev, len(coordlist))
            oricm = np.array(coordlist)  # original cartesian coordinate matrix
            oripm = np.dot(np.linalg.inv(ab), oricm.transpose()) % 1.0
            # collapse (relative) coordinates to base unit cell
            oricm = np.dot(ab, oripm).transpose()
            # original cartesian coordinates collapsed to base unit cell
            tmpcoords = np.copy(oricm).transpose()
            # copy of coordinate matrix to be rotated
            tmpcoords -= shiftm
            tmpcoords = np.dot(rotmirm, tmpcoords)
            tmpcoords += shiftm
            if glide:
                tmpcoords += glidem
            tmpcoords = np.dot(ab, (np.dot(np.linalg.inv(ab),
                                           tmpcoords) % 1.0))
            # collapse coordinates to base unit cell
            # for every point in matrix, check whether is equal:
            for (i, p) in enumerate(oripm.transpose()):
                # get extended comparison list for edges/corners:
                addlist = []
                for j in range(0, 2):
                    if abs(p[j]) < releps[j]:
                        addlist.append(oricm[i]+abt[j])
                    if abs(p[j]-1) < releps[j]:
                        addlist.append(oricm[i]-abt[j])
                if len(addlist) == 2:
                    # coner - add the diagonally opposed one
                    addlist.append(addlist[0]+addlist[1]-oricm[i])
                for v in addlist:
                    oricm = np.concatenate((oricm, v.reshape(1, 2)))
            distances = sps.distance.cdist(tmpcoords.T, oricm,
                                           'euclidean')
            for sublist in distances:
                if min(sublist) > eps:
                    return False
        return True

    def isRotationSymmetric(self, axis, order, eps):
        """Evaluates whether the slab is equivalent to itself when rotated
        around the axis with the given rotational order"""
        m = rotation_matrix_order(order)
        ab = self.ucell[:2, :2]
        abt = ab.T
        releps = [eps / np.linalg.norm(abt[j]) for j in range(0, 2)]
        shiftv = axis.reshape(2, 1)
        for sl in self.sublayers:
            coordlist = [at.cartpos[0:2] for at in sl.atlist]
            shiftm = np.tile(shiftv, len(coordlist))
            # matrix to shift all coordinates by axis
            oricm = np.array(coordlist)  # original cartesian coordinate matrix
            oripm = np.dot(np.linalg.inv(ab), oricm.transpose()) % 1.0
            # collapse (relative) coordinates to base unit cell
            oricm = np.dot(ab, oripm).transpose()
            # original cartesian coordinates collapsed to base unit cell
            tmpcoords = np.copy(oricm).transpose()
            # copy of coordinate matrix to be rotated
            tmpcoords -= shiftm
            tmpcoords = np.dot(m, tmpcoords)
            tmpcoords += shiftm
            tmpcoords = np.dot(ab,
                               (np.dot(np.linalg.inv(ab), tmpcoords) % 1.0))
            # collapse coordinates to base unit cell
            # for every point in matrix, check whether is equal:
            for (i, p) in enumerate(oripm.transpose()):
                # get extended comparison list for edges/corners:
                addlist = []
                for j in range(0, 2):
                    if abs(p[j]) < releps[j]:
                        addlist.append(oricm[i]+abt[j])
                    if abs(p[j]-1) < releps[j]:
                        addlist.append(oricm[i]-abt[j])
                if len(addlist) == 2:
                    # coner - add the diagonally opposed one
                    addlist.append(addlist[0]+addlist[1]-oricm[i])
                for v in addlist:
                    oricm = np.concatenate((oricm, v.reshape(1, 2)))
            distances = sps.distance.cdist(tmpcoords.transpose(), oricm,
                                           'euclidean')
            for sublist in distances:
                if min(sublist) > eps:
                    return False
        return True

    def isTranslationSymmetric(self, tv, eps, z_periodic=True, z_range=None):
        """
        Evaluates whether the slab is equivalent to itself when translated
        along the given cartesian translation vector tv.

        Parameters
        ----------
        tv : numpy array
            2- or 3-dimensional translation vectors are accepted.
        eps : float
            Error tolerance for positions (cartesian)
        z_periodic : bool, optional
            True for checking periodicity of a bulk slab, in which the c vector
            is a true unit cell vector. False otherwise.
        z_range : tuple of floats, optional
            Limit check to only atoms within a given range of cartesian
            coordinates. The default is None.

        Returns
        -------
        bool
            True if translation symmetric, else False.

        """
        self.check_a_b_out_of_plane()
        if len(tv) == 2:  # two-dimensional displacement. append zero for z
            tv = np.append(tv, 0.)
        uc = np.copy(self.ucell)
        uc[:, 2] *= -1   # mirror c vector down
        uct = np.transpose(uc)
        releps = [eps / np.linalg.norm(uct[j]) for j in range(0, 3)]
        shiftv = tv.reshape(3, 1)
        # unlike in-plane operations, this one cannot be done sublayer-internal
        coordlist = [at.cartpos for at in self.atlist]
        shiftm = np.tile(shiftv, len(coordlist))
        oricm = np.array(coordlist)  # original cartesian coordinate matrix
        oricm[:, 2] *= -1
        shiftm[2] *= -1
        oripm = np.dot(np.linalg.inv(uc), oricm.transpose()) % 1.0
        # collapse (relative) coordinates to base unit cell
        oricm = np.dot(uc, oripm).transpose()
        # original cartesian coordinates collapsed to base unit cell
        tmpcoords = np.copy(oricm).transpose()
        # copy of coordinate matrix to be manipulated
        # determine which z to check
        if z_range is None:
            min_z = np.min(tmpcoords[2]) - eps
            max_z = np.max(tmpcoords[2]) + eps
        else:
            z_range = tuple(-v for v in z_range)
            min_z, max_z = min(z_range) - eps, max(z_range) + eps
        tmpcoords += shiftm
        if not z_periodic:
            # discard atoms that moved out of range in z
            tmpcoords = tmpcoords[:, tmpcoords[2] >= min_z]
            tmpcoords = tmpcoords[:, tmpcoords[2] <= max_z]
        tmpcoords = np.dot(uc, (np.dot(np.linalg.inv(uc), tmpcoords) % 1.0))
        # collapse coordinates to base unit cell
        # for every point in matrix, check whether is equal:
        for (i, p) in enumerate(oripm.transpose()):
            # get extended comparison list for edges/corners:
            addlist = []
            for j in range(0, 3):
                if abs(p[j]) < releps[j]:
                    addlist.append(oricm[i]+uct[j])
                if abs(p[j]-1) < releps[j]:
                    addlist.append(oricm[i]-uct[j])
            if len(addlist) == 2:
                # 2D coner - add the diagonally opposed point
                addlist.append(addlist[0]+addlist[1]-oricm[i])
            elif len(addlist) == 3:
                # 3D corner - add all diagonally opposed points
                addlist.extend([(p1 + p2 - oricm[i]) for (p1, p2) in
                                itertools.combinations(addlist, 2)])
                addlist.append(addlist[0] + addlist[1] + addlist[2]
                               - 2*oricm[i])
            for v in addlist:
                oricm = np.concatenate((oricm, v.reshape(1, 3)))
        distances = sps.distance.cdist(tmpcoords.transpose(), oricm,
                                       'euclidean')
        # print(oricm)
        if any(min(sublist) > eps for sublist in distances):
            return False
        return True
