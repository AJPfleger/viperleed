# -*- coding: utf-8 -*-
"""
Created on Mon Aug 17 15:24:16 2020

@author: Florian Kraushofer
"""

import os
import logging
import subprocess
import numpy as np
import fortranformat as ff

logger = logging.getLogger("tleedm.beamgen")

def runBeamGen(sl,rp,beamgensource=os.path.join('.','source','beamgen3.out')):
    """Writes necessary input for the beamgen3 code, the runs it. The relevant 
    output file will be renamed to _BEAMLIST."""
    output = ''
    f74x2 = ff.FortranRecordWriter('2F7.4')
    if sl.bulkslab is None:
        sl.bulkslab = sl.makeBulkSlab(rp)
    ucbulk = np.transpose(sl.bulkslab.ucell[:2,:2])
    ol = f74x2.write(ucbulk[0])
    ol = ol.ljust(36)
    output += ol + 'ARA1\n'
    ol = f74x2.write(ucbulk[1])
    ol = ol.ljust(36)
    output += ol + 'ARA2\n'
    i3x2 = ff.FortranRecordWriter('2I3')
    ol = i3x2.write([int(round(f)) for f in rp.SUPERLATTICE[0]])
    ol = ol.ljust(36)
    output += ol + 'LATMAT - overlayer\n'
    ol = i3x2.write([int(round(f)) for f in rp.SUPERLATTICE[1]])
    ol = ol.ljust(36)
    output += ol + 'LATMAT -  matrix\n'
    output +=('  1                                 SSYM - symmetry code - cf. '
              'van Hove / Tong 1979, always 1\n')
    sl.getCartesianCoordinates()
    mindist = sl.layers[1].carttopz - sl.layers[0].cartbotz
    for i in range(2,len(sl.layers)):
        d = sl.layers[i].carttopz - sl.layers[i-1].cartbotz
        if d < mindist: mindist = d
    dmin = mindist*0.7
    f71 = ff.FortranRecordWriter('F7.1')
    f41 = ff.FortranRecordWriter('F4.1')
    ol = f71.write([rp.THEO_ENERGIES[1]]) + f41.write([dmin])
    ol = ol.ljust(36)
    output += (ol + 'EMAX,DMIN - max. energy, min. interlayer distance for '
              'layer doubling\n')
    output += ('   {:.4f}                           TST - convergence '
              'criterion for fd. reference calculation\n'
              .format(rp.ATTENUATION_EPS))
    output += ('9999                                KNBMAX - max. number of '
              'beams to be written (may be a format problem!)')
    try:
        with open('DATA', 'w') as wf:
            wf.write(output)
    except:
        logger.error("Failed to write DATA for _BEAMLIST generation.")
        raise
    if os.name == 'nt':
        logger.error("Beamlist generation is currently not "
                         "supported on Windows. Use a linux shell to run "
                         "beamlist generation script.")
        raise EnvironmentError("Beamlist generation is currently not "
                               "supported on Windows.")
    else:
        try:
            subprocess.call(beamgensource)
        except:
            logger.error("Failed to execute beamgen script.")
            raise
    # clean up folder, rename files
    try:
        os.remove('BELIST')
        os.remove('PROT')
    except:
        logger.warning("_BEAMLIST generation: Failed to remove BELIST or "
                        "PROT file")
    try:
        os.rename('DATA','beamgen3-input')
    except:
        logger.warning("Failed to rename beamlist generation input file "
                        "DATA to beamgen3-input")
    try:
        os.rename('NBLIST','_BEAMLIST')
    except:
        logger.error("Failed to rename beamlist generation output file "
                      "NBLIST to _BEAMLIST")
        raise
    logger.debug("Wrote to _BEAMLIST successfully.")
    return 0