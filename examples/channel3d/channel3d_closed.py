# Idealised channel flow in 3D
# ============================
#
# Solves hydrostatic flow in a closed rectangular channel.
#
# Tuomas Karna 2015-03-03

from scipy.interpolate import interp1d
from cofs.utility import *
from cofs.physical_constants import physical_constants
import cofs.timeIntegration as timeIntegration
import cofs.solver as solverMod

op2.init(log_level=WARNING)  # DEBUG, INFO, WARNING, ERROR, CRITICAL

# set physical constants
physical_constants['z0_friction'].assign(5.0e-5)

use_wd = False
nonlin = True
n_layers = 6
outputDir = createDirectory('outputs')
mesh2d = Mesh('channel_mesh.msh')
T = 48 * 3600
Umag = Constant(4.2)  # 4.2 closed
TExport = 100.0

# bathymetry
P1_2d = FunctionSpace(mesh2d, 'CG', 1)
bathymetry2d = Function(P1_2d, name='Bathymetry')

depth_oce = 20.0
depth_riv = 5.0  # 5.0 closed
bath_x = np.array([0, 100e3])
bath_v = np.array([depth_oce, depth_riv])


def bath(x, y, z):
    padval = 1e20
    x0 = np.hstack(([-padval], bath_x, [padval]))
    vals0 = np.hstack(([bath_v[0]], bath_v, [bath_v[-1]]))
    return interp1d(x0, vals0)(x)

x_func = Function(P1_2d).interpolate(Expression('x[0]'))
bathymetry2d.dat.data[:] = bath(x_func.dat.data, 0, 0)

bathfile = File(os.path.join(outputDir, 'bath.pvd'))
bathfile << bathymetry2d

# create solver
solver = solverMod.flowSolver(mesh2d, bathymetry2d, n_layers)
solver.nonlin = nonlin
solver.use_wd = use_wd
solver.TExport = TExport
solver.T = T
solver.uAdvection = Umag
solver.checkVolConservation2d = True
solver.checkVolConservation3d = True
solver.checkSaltConservation = True
solver.checkSaltDeviation = True
solver.fieldsToExport = ['uv2d', 'elev2d', 'elev3d', 'uv3d',
                         'w3d', 'w3d_mesh', 'salt3d',
                         'uv2d_dav', 'uv2d_bot', 'nuv3d']


# initial conditions
elev_x = np.array([0, 30e3, 100e3])
elev_v = np.array([6, 0, 0])


def elevation(x, y, z, x_array, val_array):
    padval = 1e20
    x0 = np.hstack(([-padval], x_array, [padval]))
    vals0 = np.hstack(([val_array[0]], val_array, [val_array[-1]]))
    return interp1d(x0, vals0)(x)

x_func = Function(P1_2d).interpolate(Expression('x[0]'))
elev_init = Function(P1_2d)
elev_init.dat.data[:] = elevation(x_func.dat.data, 0, 0,
                                  elev_x, elev_v)
salt_init3d = Constant(4.5)

solver.assingInitialConditions(elev=elev_init, salt=salt_init3d)
solver.iterate()