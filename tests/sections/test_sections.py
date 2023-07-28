import pytest
import shutil, tempfile
import sys
import os
from pathlib import Path
from copy import deepcopy
import numpy as np

vpr_path = str(Path(__file__).parent.parent.parent)
if os.path.abspath(vpr_path) not in sys.path:
    sys.path.append(os.path.abspath(vpr_path))


from viperleed.tleedmlib.files.displacements import readDISPLACEMENTS, readDISPLACEMENTS_block
from viperleed.tleedmlib.files.poscar import readPOSCAR
from viperleed.tleedmlib.files.vibrocc import readVIBROCC
from viperleed.tleedmlib.symmetry import findSymmetry, enforceSymmetry
from viperleed.tleedmlib.psgen import runPhaseshiftGen_old
from viperleed.tleedmlib.classes.atom import Atom
from viperleed.tleedmlib.classes.rparams import Rparams
from viperleed.tleedmlib.classes.slab import Slab, SymPlane



class TestRefCalc:
    @pytest.mark.parametrize('expected_file', (('THEOBEAMS.csv',)))
    def test_refcalc_files_present(self, refcalc_files, expected_file):
        assert refcalc_files.expected_file_exists(expected_file)


class TestDeltasAg100():
    def test_delta_input_written(self, delta_files_ag100):
        assert delta_files_ag100.expected_file_exists("delta-input")


    def test_exit_code_0(self, delta_files_ag100):
        assert delta_files_ag100.exit_code == 0


    def test_deltas_zip_created(self, delta_files_ag100):
        assert delta_files_ag100.expected_file_exists(Path("Deltas") / "Deltas_001.zip")


class TestSearchAg100():
    def test_exit_code_0(self, search_files_ag100):
        assert search_files_ag100.exit_code == 0
        
    @pytest.mark.parametrize('expected_file', ('search.steu',))
    def test_search_input_exist(self, search_files_ag100, expected_file):
        assert search_files_ag100.expected_file_exists(expected_file)

    @pytest.mark.parametrize('expected_file', ('SD.TL', 'control.chem'))
    def test_search_raw_files_exist(self, search_files_ag100, expected_file):
        assert search_files_ag100.expected_file_exists(expected_file)

    @pytest.mark.parametrize('expected_file', ('Search-report.pdf', 'Search-progress.pdf'))
    def test_search_pdf_files_exist(self, search_files_ag100, expected_file):
        assert search_files_ag100.expected_file_exists(expected_file)


class TestPOSCARRead:
    def test_read_in_atoms(self, slab_and_expectations):
        slab, *_ = slab_and_expectations
        assert len(slab.atlist) > 0

    def test_n_atom_correct(self, slab_and_expectations):
        slab, expected_n_atoms, *_ = slab_and_expectations
        assert len(slab.atlist) == expected_n_atoms


class TestPOSCARSymmetry(TestPOSCARRead):                                       # TODO: this should probably be moved to a separate file (e.g. test_symmetry.py)
    def test_any_pg_found(self, slab_pg_rp):
        _, slab_pg, _ = slab_pg_rp
        assert slab_pg != 'unknown'

    def test_pg_correct(self, slab_and_expectations, slab_pg_rp):
        _, _, expected_pg, _ = slab_and_expectations
        _, slab_pg, _ = slab_pg_rp
        assert slab_pg == expected_pg

    @pytest.mark.parametrize("displacement", [(4, (np.array([0.2, 0, 0]),)),
                                            (4, (np.array([0, 0.2, 0]),)),
                                            (4, (np.array([0, 0, 0.2]),)),
                                            ])
    def test_preserve_symmetry_with_displacement(self, displacement, slab_and_expectations, slab_pg_rp):
        slab, _, expected_pg, offset_at = slab_and_expectations
        _, _, rp = slab_pg_rp
        sl_copy = deepcopy(slab)
        
        # manually assign displacements
        sl_copy.atlist[offset_at].assignDisp(*displacement)

        for at in sl_copy.atlist:
            disp = at.disp_geo_offset['all'][0]
            at.cartpos += disp
        sl_copy.getFractionalCoordinates()

        assert findSymmetry(sl_copy, rp) == expected_pg



class TestSlabTransforms:
    def test_mirror(self, manual_slab_3_atoms):
        slab = manual_slab_3_atoms
        mirrored_slab = deepcopy(slab)
        symplane = SymPlane(pos=(0,0),
                            dr=np.array([0,1]),
                            abt=slab.ucell.T[:2,:2])
        mirrored_slab.mirror(symplane)
        mirrored_slab.collapseCartesianCoordinates()
        assert all(at.isSameXY(mir_at.cartpos[:2])
                for at, mir_at in
                zip(slab.atlist, reversed(mirrored_slab.atlist)))

    def test_180_rotation(self, manual_slab_3_atoms):
        slab = manual_slab_3_atoms
        rotated_slab = deepcopy(slab)
        rotated_slab.rotateAtoms((0,0), order=2)
        rotated_slab.collapseCartesianCoordinates()
        assert all(at.isSameXY(mir_at.cartpos[:2])
                for at, mir_at in
                zip(slab.atlist, reversed(rotated_slab.atlist)))



class TestPhaseshifts:
    def test_phaseshifts_firstline_not_empty(self, run_phaseshift):
        _, _, firstline, _ = run_phaseshift
        assert firstline

    def test_phaseshifts_firstline_len(self, run_phaseshift):
        _, _, firstline, _ = run_phaseshift
        potential_param = firstline.split()
        assert len(potential_param) >= 4


    def test_phaseshift_log_exists(self, run_phaseshift):
        param, _, _, _ = run_phaseshift
        assert len(list(param.workdir.glob('phaseshift*.log'))) > 0


    def test_write_phaseshifts(self, run_phaseshift):
        from tleedmlib.files.phaseshifts import writePHASESHIFTS
        param, _, firstline, phaseshift = run_phaseshift
        writePHASESHIFTS(firstline, phaseshift, file_path=param.workdir/'PHASESHIFTS')
        assert len(list(param.workdir.glob('PHASESHIFTS'))) > 0


    def test_phaseshifts_not_empty(self, run_phaseshift):
        _, _, _, phaseshift = run_phaseshift
        assert len(phaseshift) > 0


# Slab Matrix operations

def test_rotation_on_trigonal_slab(manual_slab_1_atom_trigonal):
    rot_15 = np.array([[ 0.96592583, -0.25881905,  0.        ],
                       [ 0.25881905,  0.96592583,  0.        ],
                       [ 0.        ,  0.        ,  1.        ]])
    expected_cell = np.array([[ 0.44828774, -2.1906707 ,  1.        ],
                              [ 0.77645714,  2.89777748,  2.        ],
                              [ 0.        ,  0.        ,  3.        ]])
    expected_atom_cartpos = [0.63317754, 1.5903101]
    slab = manual_slab_1_atom_trigonal
    slab.apply_matrix_transformation(rot_15)
    assert np.allclose(slab.ucell.T, expected_cell)
    assert np.allclose(slab.atlist[0].cartpos[:2], expected_atom_cartpos)




@pytest.mark.parametrize('fixture', ('fe3o4_bulk_slab', 'fe3o4_thick_bulk_slab'))
def test_bulk_symmetry_thin(fixture, request):
    _, bulk, param = request.getfixturevalue(fixture)
    from viperleed.tleedmlib.symmetry import findBulkSymmetry
    findBulkSymmetry(bulk, param)
    assert bulk.bulk_screws == [4]
    assert len(bulk.bulk_glides) == 2




class Test_Atom_mergeDisp:
    def test_atom_mergeDisp_allowed(self, atom_with_disp_and_offset):
        """Test method mergeDisp of Atom.
        Offsets are allowed and should be combined with stored
        displacements.
        """
        atom = atom_with_disp_and_offset
        el = atom.el
        atom.offset_geo[el] = +0.1
        atom.offset_vib[el] = +0.1
        atom.offset_occ[el] = -0.1
        atom.mergeDisp(el)
        assert np.allclose(atom.disp_geo[el], [-0.1, 0.1, 0.3])
        assert np.allclose(atom.disp_vib[el], [0.0, 0.1, 0.2])
        assert np.allclose(atom.disp_occ[el], [0.6, 0.7, 0.8, 0.9])

    def test_atom_mergeDisp_not_allowed(self, atom_with_disp_and_offset):
        """Test method mergeDisp of Atom.
        Offsets are not allowed and should not be combined with stored
        displacements. Instead the final displacements should be unchanged.
        """
        atom = atom_with_disp_and_offset
        el = atom.el
        atom.offset_vib[el] = -0.1
        atom.offset_occ[el] = +0.2
        atom.mergeDisp(el)
        assert np.allclose(atom.disp_vib[el], [-0.1, 0.0, 0.1])
        assert np.allclose(atom.disp_occ[el], [0.7, 0.8, 0.9, 1.0])


class Test_readDISPLACEMENTS:
    def test_read_DISPLACEMENTS_geo(self, ag100_slab_with_displacements_and_offsets):
        slab, param = ag100_slab_with_displacements_and_offsets
        assert np.allclose(np.array(slab.atlist[0].disp_geo['all'])[:, 2], [0.2, 0.1, 0.0, -0.1, -0.2])

    def test_read_DISPLACEMENTS_vib(self, ag100_slab_with_displacements_and_offsets):
        slab, param = ag100_slab_with_displacements_and_offsets
        assert np.allclose(slab.atlist[0].disp_vib['all'], [-0.1, 0.0, 0.1])

    def test_read_DISPLACEMENTS_occ(self, ag100_slab_with_displacements_and_offsets):
        slab, param = ag100_slab_with_displacements_and_offsets
        assert np.allclose(slab.atlist[0].disp_occ['Ag'], [0.5, 0.6, 0.7, 0.8, 0.9, 1.0])


class Test_readVIBROCC:
    def test_read_VIBROCC_offset_occ(self, ag100_slab_with_displacements_and_offsets):
        slab, param = ag100_slab_with_displacements_and_offsets
        assert np.allclose(slab.atlist[0].offset_occ['Ag'], -0.1)

    def test_interpret_VIBROCC_offset_allowed(self, ag100_slab_with_displacements_and_offsets):
        slab, param = ag100_slab_with_displacements_and_offsets
        for atom in slab.atlist:
            atom.mergeDisp(atom.el)
        assert np.allclose(slab.atlist[0].disp_occ['Ag'], [0.4, 0.5, 0.6, 0.7, 0.8, 0.9])

    def test_interpret_VIBROCC_offset_not_allowed(self, ag100_slab_with_displacements_and_offsets):
        slab, param = ag100_slab_with_displacements_and_offsets
        atom = slab.atlist[0]
        atom.offset_occ[atom.el] = +0.2
        atom.mergeDisp(atom.el)
        assert np.allclose(atom.disp_occ['Ag'], [0.5, 0.6, 0.7, 0.8, 0.9, 1.0])


class Test_restore_oristate:
    def test_save_restore_oristate_geo(self, ag100_slab_with_displacements_and_offsets):
            slab, param = ag100_slab_with_displacements_and_offsets
            slab_copy = deepcopy(slab)
            for at in slab.atlist:
                at.disp_geo_offset['all'] = np.array([0.1, 0.0, 0.0])
                at.offset_geo['all'] = np.array([0.0, 0.0, 0.1])
                at.mergeDisp(at.el)

            slab.restoreOriState()
            for (at_rest, at_orig) in zip(slab.atlist, slab_copy.atlist):
                assert np.allclose(at_rest.disp_geo['all'], at_orig.disp_geo['all'])

    def test_save_restore_oristate_vib(self, ag100_slab_with_displacements_and_offsets):
            slab, param = ag100_slab_with_displacements_and_offsets
            slab_copy = deepcopy(slab)
            for at in slab.atlist:
                at.offset_vib['all'] = 0.1
                at.mergeDisp(at.el)

            slab.restoreOriState()
            for (at_rest, at_orig) in zip(slab.atlist, slab_copy.atlist):
                assert np.allclose(at_rest.disp_vib['all'], at_orig.disp_vib['all'])

    def test_save_restore_oristate_occ(self, ag100_slab_with_displacements_and_offsets):
            slab, param = ag100_slab_with_displacements_and_offsets
            slab_copy = deepcopy(slab)
            for at in slab.atlist:
                at.offset_occ[at.el] = 0.1
                at.mergeDisp(at.el)

            slab.restoreOriState()
            for (at_rest, at_orig) in zip(slab.atlist, slab_copy.atlist):
                assert np.allclose(at_rest.disp_occ[at_rest.el], at_orig.disp_occ[at_rest.el])