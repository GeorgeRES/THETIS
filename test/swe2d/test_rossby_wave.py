"""
'Equatorial Rossby soliton' test case, taken from p.3-6 of [1].

An initial two peak Rossby soliton propagates around a non-dimensionalised periodic equatorial
channel. The test is inviscid and is set up such that the solution at time T=120 should be identical
to the initial condition.

The test case admits approximate solutions by asymptotic expansion, so we can compute error metrics
at the final time to assess how accurately Thetis handles dispersion and nonlinearity. The error
metrics chosen are relative mean peak height, relative mean phase speed and RMS error. In order to
compute the error metrics, we project onto the same high resolution mesh used for FVCOM comparisons.

[1] H. Huang, C. Chen, G.W. Cowles, C.D. Winant, R.C. Beardsley, K.S. Hedstrom and D.B. Haidvogel,
"FVCOM validation experiments: Comparisons with ROMS for three idealized barotropic test problems"
(2008), Journal of Geophysical Research: Oceans, 113(C7).
"""
from thetis import *
import os
import json
import numpy as np
import pytest
import weakref


def asymptotic_expansion_uv(U_2d, order=1, time=0.0, soliton_amplitude=0.395):
    x, y = SpatialCoordinate(U_2d.mesh())

    # Variables for asymptotic expansion
    t = Constant(time)
    B = Constant(soliton_amplitude)
    modon_propagation_speed = -1.0/3.0
    if order != 0:
        assert order == 1
        modon_propagation_speed -= 0.395*B*B
    c = Constant(modon_propagation_speed)
    xi = x - c*t
    psi = exp(-0.5*y*y)
    phi = 0.771*(B/cosh(B*xi))**2
    dphidx = -2*B*phi*tanh(B*xi)
    C = -0.395*B*B

    # Zeroth order terms
    u_terms = phi*0.25*(-9 + 6*y*y)*psi
    v_terms = 2*y*dphidx*psi
    if order == 0:
        return interpolate(as_vector([u_terms, v_terms]), U_2d)

    # Unnormalised Hermite series coefficients for u
    u = np.zeros(28)
    u[0] = 1.7892760e+00
    u[2] = 0.1164146e+00
    u[4] = -0.3266961e-03
    u[6] = -0.1274022e-02
    u[8] = 0.4762876e-04
    u[10] = -0.1120652e-05
    u[12] = 0.1996333e-07
    u[14] = -0.2891698e-09
    u[16] = 0.3543594e-11
    u[18] = -0.3770130e-13
    u[20] = 0.3547600e-15
    u[22] = -0.2994113e-17
    u[24] = 0.2291658e-19
    u[26] = -0.1178252e-21

    # Unnormalised Hermite series coefficients for v
    v = np.zeros(28)
    v[3] = -0.6697824e-01
    v[5] = -0.2266569e-02
    v[7] = 0.9228703e-04
    v[9] = -0.1954691e-05
    v[11] = 0.2925271e-07
    v[13] = -0.3332983e-09
    v[15] = 0.2916586e-11
    v[17] = -0.1824357e-13
    v[19] = 0.4920951e-16
    v[21] = 0.6302640e-18
    v[23] = -0.1289167e-19
    v[25] = 0.1471189e-21

    # Hermite polynomials
    polynomials = [Constant(1.0), 2*y]
    for i in range(2, 28):
        polynomials.append(2*y*polynomials[i-1] - 2*(i-1)*polynomials[i-2])

    # First order terms
    u_terms += C*phi*0.5625*(3 + 2*y*y)*psi
    u_terms += phi*phi*psi*sum(u[i]*polynomials[i] for i in range(28))
    v_terms += dphidx*phi*psi*sum(v[i]*polynomials[i] for i in range(28))

    return interpolate(as_vector([u_terms, v_terms]), U_2d)


def asymptotic_expansion_elev(H_2d, order=1, time=0.0, soliton_amplitude=0.395):
    x, y = SpatialCoordinate(H_2d.mesh())

    # Variables for asymptotic expansion
    t = Constant(time)
    B = Constant(soliton_amplitude)
    modon_propagation_speed = -1.0/3.0
    if order != 0:
        assert order == 1
        modon_propagation_speed -= 0.395*B*B
    c = Constant(modon_propagation_speed)
    xi = x - c*t
    psi = exp(-0.5*y*y)
    phi = 0.771*(B/cosh(B*xi))**2
    C = -0.395*B*B

    # Zeroth order terms
    eta_terms = phi*0.25*(3 + 6*y*y)*psi
    if order == 0:
        return interpolate(eta_terms, H_2d)

    # Unnormalised Hermite series coefficients for eta
    eta = np.zeros(28)
    eta[0] = -3.0714300e+00
    eta[2] = -0.3508384e-01
    eta[4] = -0.1861060e-01
    eta[6] = -0.2496364e-03
    eta[8] = 0.1639537e-04
    eta[10] = -0.4410177e-06
    eta[12] = 0.8354759e-09
    eta[14] = -0.1254222e-09
    eta[16] = 0.1573519e-11
    eta[18] = -0.1702300e-13
    eta[20] = 0.1621976e-15
    eta[22] = -0.1382304e-17
    eta[24] = 0.1066277e-19
    eta[26] = -0.1178252e-21

    # Hermite polynomials
    polynomials = [Constant(1.0), 2*y]
    for i in range(2, 28):
        polynomials.append(2*y*polynomials[i-1] - 2*(i-1)*polynomials[i-2])

    # First order terms
    eta_terms += C*phi*0.5625*(-5 + 2*y*y)*psi
    eta_terms += phi*phi*psi*sum(eta[i]*polynomials[i] for i in range(28))

    return interpolate(eta_terms, H_2d)


def run(refinement_level, **model_options):
    print_output("--- running refinement level {:}".format(refinement_level))
    order = model_options.pop('expansion_order')

    # Set up domain
    lx, ly = 48, 24
    nx, ny = 2*refinement_level, refinement_level
    params = {'partition': True, 'overlap_type': (DistributedMeshOverlapType.VERTEX, 10)}
    mesh2d = PeriodicRectangleMesh(nx, ny, lx, ly, distribution_parameters=params)
    x, y = SpatialCoordinate(mesh2d)
    mesh2d.coordinates.interpolate(as_vector([x-lx/2, y-ly/2]))
    T = 120.0

    physical_constants['g_grav'].assign(1.0)

    # Create solver object
    solver_obj = solver2d.FlowSolver2d(mesh2d, Constant(1.0))
    options = solver_obj.options
    options.timestepper_type = 'CrankNicolson'
    options.timestep = 0.96/refinement_level
    options.simulation_export_time = 5.0
    options.simulation_end_time = T
    options.use_grad_div_viscosity_term = False
    options.use_grad_depth_viscosity_term = False
    options.horizontal_viscosity = None
    options.no_exports = True and refinement_level <= 48
    solver_obj.create_function_spaces()
    options.coriolis_frequency = interpolate(y, solver_obj.function_spaces.P1_2d)
    options.update(model_options)

    # Apply boundary conditions
    for tag in mesh2d.exterior_facets.unique_markers:
        solver_obj.bnd_functions['shallow_water'][tag] = {'uv': Constant(as_vector([0., 0.]))}

    # Apply initial conditions (asymptotic solution at initial time)
    uv_a = asymptotic_expansion_uv(solver_obj.function_spaces.U_2d, order=order)
    elev_a = asymptotic_expansion_elev(solver_obj.function_spaces.H_2d, order=order)
    solver_obj.assign_initial_conditions(uv=uv_a, elev=elev_a)

    # Solve PDE and save to HDF5
    solver_obj.iterate()
    fname = "{:d}_{:d}".format(refinement_level, mesh2d.comm.size)
    di = create_directory(os.path.join(os.path.dirname(__file__), 'outputs'))
    with DumbCheckpoint(os.path.join(di, fname), mode=FILE_CREATE) as chk:
        chk.store(solver_obj.fields.elev_2d)


def compute_error_metrics(ref_list, reference_refinement_level, **options):
    order = options.pop('expansion_order')
    degree = options.get('polynomial_degree')
    family = options.get('element_family')
    if family in ('dg-dg', 'rt-dg'):
        family = 'Discontinuous Lagrange'
    elif family == 'dg-cg':
        family = 'Lagrange'
        degree += 1
    else:
        raise ValueError("Element pair {:s} not recognised.".format(family))

    # Build reference mesh
    lx, ly = 48, 24
    nx_fine, ny_fine = 2*reference_refinement_level, reference_refinement_level
    params = {'partition': True, 'overlap_type': (DistributedMeshOverlapType.VERTEX, 10)}
    ref_mesh = PeriodicRectangleMesh(nx_fine, ny_fine, lx, ly, distribution_parameters=params)
    x_fine, y_fine = SpatialCoordinate(ref_mesh)
    ref_mesh.coordinates.interpolate(as_vector([x_fine-lx/2, y_fine-ly/2]))

    # Get asymptotic solution at final time on a reference mesh
    P1_2d_ref = FunctionSpace(ref_mesh, "CG", 1)
    elev_a = asymptotic_expansion_elev(P1_2d_ref, order=order)

    # Compute metrics for each refinement level
    dx = [24/r for r in ref_list]
    dt = [0.96/r for r in ref_list]
    metrics = {'h+': [], 'h-': [], 'c+': [], 'c-': [], 'rms': [], 'dx': dx, 'dt': dt}
    formats = {'h+': '{:6.4f}', 'h-': '{:6.4f}', 'c+': '{:6.4f}', 'c-': '{:6.4f}', 'rms': '{:6.4e}'}
    di = create_directory(os.path.join(os.path.dirname(__file__), 'outputs'))
    for r in ref_list:
        nx, ny = 2*r, r
        mesh = PeriodicRectangleMesh(nx, ny, lx, ly, distribution_parameters=params)
        x, y = SpatialCoordinate(mesh)
        mesh.coordinates.interpolate(as_vector([x-lx/2, y-ly/2]))

        # Read solution from HDF5
        H_2d = FunctionSpace(mesh, family, degree)
        elev = Function(H_2d, name='elev_2d')
        fname = "{:d}_{:d}".format(r, mesh.comm.size)
        try:
            with DumbCheckpoint(os.path.join(di, fname), mode=FILE_READ) as chk:
                chk.load(elev)
        except ValueError:
            print_output("WARNING: Could not find simulation data for refinement level {:d} on {:d} processors.".format(r, mesh.comm.size))
            continue

        # Project solution into reference space
        ref_mesh._parallel_compatible = {weakref.ref(mesh)}
        elev_ref = project(elev, P1_2d_ref)
        xcoords = project(ref_mesh.coordinates[0], P1_2d_ref)

        # Calculate RMS error
        elev_diff = elev_a.vector().gather()
        elev_diff -= elev_ref.vector().gather()
        elev_diff *= elev_diff
        rms = np.sqrt(elev_diff.sum()/elev_diff.size)

        # Get mean peak heights
        elev_ref.interpolate(sign(y_fine)*elev_ref)  # Flip sign in southern hemisphere
        with elev_ref.dat.vec_ro as v:
            i_n, h_n = v.max()
            i_s, h_s = v.min()

            # Find ranks which own peaks
            ownership_range = v.getOwnershipRanges()
            for j in range(mesh.comm.size):
                if i_n >= ownership_range[j] and i_n < ownership_range[j+1]:
                    rank_with_n_peak = j
                if i_s >= ownership_range[j] and i_s < ownership_range[j+1]:
                    rank_with_s_peak = j

        # Get mean phase speeds
        x_n, x_s = None, None
        with xcoords.dat.vec_ro as xdat:
            if mesh.comm.rank == rank_with_n_peak:
                x_n = xdat[i_n]
            if mesh.comm.rank == rank_with_s_peak:
                x_s = xdat[i_s]
        x_n = mesh.comm.bcast(x_n, root=rank_with_n_peak)
        x_s = mesh.comm.bcast(x_s, root=rank_with_s_peak)

        # Get relative versions of metrics using high resolution FVCOM data
        h_n /= 0.1567020
        h_s /= -0.1567020  # Flip sign back
        c_n = (48.0 - x_n)/47.18
        c_s = (48.0 - x_s)/47.18

        # Gather outputs and print to screen
        msg = "Error metrics for refinement level {:d}:\n".format(r)
        for metric, value in zip(('h+', 'h-', 'c+', 'c-', 'rms'), (h_n, h_s, c_n, c_s, rms)):
            metrics[metric].append(value)
            msg = ' '.join([msg, ' '.join([metric, formats[metric].format(value)])])
        print_output(msg)
    return metrics


def run_convergence(ref_list, solve=True, reference_refinement_level=50, **options):
    """Runs test for a list of refinements and computes error convergence rate."""
    setup_name = 'rossby-soliton'

    # Run model on increasingly refined meshes
    if solve:
        for r in ref_list:
            run(r, **options)

    # Evaluate error metrics
    metrics = compute_error_metrics(ref_list, reference_refinement_level, **options)

    # Save metrics to .json file for model comparison
    di = create_directory(os.path.join(os.path.dirname(__file__), 'data'))
    with open(os.path.join(di, 'Thetis.json'), 'w+') as f:
        json.dump(metrics, f, ensure_ascii=False)

    # Check convergence of relative mean peak height and phase speed
    slope_rtol = 0.01
    for m in ('h+', 'h-', 'c+', 'c-', 'rms'):
        for i in range(1, len(ref_list)):
            slope = metrics[m][i-1]/metrics[m][i] if m == 'rms' else metrics[m][i]/metrics[m][i-1]
            msg = "{:s}: Divergence of error metric {:s}, expected {:.4f} > 1"
            assert slope > 1.0 - slope_rtol, msg.format(setup_name, m, slope)
            print_output("{:s}: error metric {:s} index {:d} PASSED".format(setup_name, m, i))


def generate_table():
    head = "|Model   |    dx    |    dt    |    h+    |    h-    |    c+    |    c-    |    rms    |"
    rule = "|--------|----------|----------|----------|----------|----------|----------|-----------|"
    out = '\n'.join([head, rule])
    msg = "|{:7s} |{:9.3f} |{:9.3f} |{:9.3f} |{:9.3f} |{:9.3f} |{:9.3f} |{:10.3e} |"
    msg_roms = "|{:7s} |{:9.3f} |{:9.3f} |{:9.3f} |{:9.3f} |{:9.3f} |{:9.3f} |           |"
    for model in ('FVCOM', 'ROMS', 'Thetis'):
        with open(os.path.join('data', model+'.json'), 'r') as f:
            data = json.load(f)
            for i in range(len(data['dx'])):
                vals = (model, data['dx'][i], data['dt'][i],)
                vals += (data['h+'][i], data['h-'][i], data['c+'][i], data['c-'][i],)
                m = msg
                if model == 'ROMS':
                    m = msg_roms
                else:
                    vals += (data['rms'][i],)
                out = '\n'.join([out, m.format(*vals)])
    return out+'\n'


# ---------------------------
# standard tests for pytest
# ---------------------------

@pytest.mark.parametrize(('stepper'),
                         [('CrankNicolson')])
def test_convergence(stepper):
    run_convergence([12, 24], reference_refinement_level=768,
                    polynomial_degree=1, element_family='dg-dg', expansion_order=1,
                    timestepper_type=stepper, no_exports=True)

# --------------------------------------------
# run individual setup for model comparison
# --------------------------------------------


if __name__ == "__main__":
    run_convergence([96, 192, 480], reference_refinement_level=1200,
                    polynomial_degree=1, element_family='dg-dg', expansion_order=1,
                    timestepper_type='CrankNicolson', no_exports=False)

    # Compare results against FVCOM and ROMS given in [1].
    table = generate_table()
    print_output(table)
    di = create_directory(os.path.join(os.path.dirname(__file__), 'outputs'))
    with open(os.path.join(di, 'model_comparison.md'), 'w+') as md:
        md.write(table)
