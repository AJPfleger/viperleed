"""Package sections of viperleed.calc.

This package contains the main functionality that runs the various
logically different parts of TensErLEED, and takes care of using the
output produced by TensErLEED to modify all the pPthon objects used
for managing the state of a calculation.

Modules
-------
_sections:
    Contains base definitions, especially which sections are available
cleanup:
    The (python-only) section that takes care of sorting the mess of
    files generated by TensErLEED after a calculation has finished.
deltas:
    Generate delta-amplitudes, i.e., the perturbative effect on the
    scattered beam amplitudes due to a (small) generalized displacement
errorcalc:
    Estimate the uncertainty on fit parameters by "displacing" atoms
    only along one "direction".
fd_optimization:
    Optimize one of the parameters that cannot be optimized using the
    tensor-LEED perturbative approximation.
initialization:
    Read and process user input
refcalc:
    Run a full-dynamic (ie, including multiple scattering) calculation
    if the complex amplitudes and intensities of scattered beams
run_sections:
    Manage the mechanics of running subsequent sections as well as
    cleaning up after each one of them.
search:
    Run a tensor-LEED-based optimization of generalized atomic
    displacements to best fit the calculated I(V) curves to
    those measured experimentally.
superpos:
    Process the output of search or errorcalc to generate I(V) curves
    of configuration that are displaced with respect to the one in
    refcalc
"""

__authors__ = (
    'Florian Kraushofer (@fkraushofer)',
    'Alexander M. Imre (@amimre)',
    'Michele Riva (@michele-riva)',
    )
__copyright__ = 'Copyright (c) 2019-2024 ViPErLEED developers'
__created__ = '2020-08-11'
__license__ = 'GPLv3+'
