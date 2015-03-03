# Idealised channel flow in 3D
# ============================
#
# Solves hydrostatic flow in a rectangular channel.
#
# Tuomas Karna 2015-03-03

from firedrake import *
import numpy as np
import os
import sys
import time as timeMod
from mpi4py import MPI
from scipy.interpolate import interp1d
import cofs.module_2d as mode2d
import cofs.module_3d as mode3d
from cofs.utility import *

# HACK to fix unknown node: XXX / (F0) COFFEE errors
op2.init()
parameters['coffee']['O2'] = False

#parameters['form_compiler']['quadrature_degree'] = 6  # 'auto'
parameters['form_compiler']['optimize'] = False
parameters['form_compiler']['cpp_optimize'] = True
parameters['form_compiler']['cpp_optimize_flags'] = '-O3 -xhost'

#from pyop2 import op2
commrank = op2.MPI.comm.rank
op2.init(log_level=WARNING)  # DEBUG, INFO, WARNING, ERROR, CRITICAL


def createDirectory(path):
    if commrank == 0:
        if os.path.exists(path):
            if not os.path.isdir(path):
                raise Exception('file with same name exists', path)
        else:
            os.makedirs(path)
    return path

mesh2d = Mesh('channel_mesh.msh')

# Function spaces for 2d mode
P1_2d = FunctionSpace(mesh2d, 'CG', 1)
U_2d = VectorFunctionSpace(mesh2d, 'DG', 1)
U_visu_2d = VectorFunctionSpace(mesh2d, 'CG', 1)
U_scalar_2d = FunctionSpace(mesh2d, 'DG', 1)
H_2d = FunctionSpace(mesh2d, 'CG', 2)

# Mean free surface height (bathymetry)
h_mean = Function(P1_2d, name='Bathymetry')

use_wd = False
nonlin = True
swe2d = mode2d.freeSurfaceEquations(mesh2d, U_2d, H_2d, h_mean,
                                    nonlin=nonlin, use_wd=use_wd)

# TODO add friction in mom3d
# TODO stabilize 3d momentum eq?
# TODO add uv correction
# TODO implement SSPRK3 for tracers
# TODO add vertical advection of momentum NOTE only works for moving mesh
# TODO add timers in solver loop DONE
# TODO FIXME advection of mom is unstable on full DG mesh
# TODO FIXME closed boundaries of mom3d incorrect uv!=0

# TODO find candidates for good element pairs
# TODO try mimetic (RT1, P1DG) for 2D solver only

#bath_x = np.array([0, 10e3, 30e3, 45e3, 100e3])
#bath_v = np.array([20, 20, 6, 15, 5])
depth_oce = 20.0
depth_riv = 5.0
bath_x = np.array([0, 100e3])
bath_v = np.array([depth_oce, depth_riv])
depth = 20.0


def bath(x, y, z):
    padval = 1e20
    x0 = np.hstack(([-padval], bath_x, [padval]))
    vals0 = np.hstack(([bath_v[0]], bath_v, [bath_v[-1]]))
    return interp1d(x0, vals0)(x)

#define a bath func depending on x,y,z
x_func = Function(P1_2d).interpolate(Expression('x[0]'))
h_mean.dat.data[:] = bath(x_func.dat.data, 0, 0)

outputDir = createDirectory('outputs')
bathfile = File(os.path.join(outputDir, 'bath.pvd'))
bathfile << h_mean

elev_x = np.array([0, 30e3, 100e3])
elev_v = np.array([2, 0, 0])


def elevation(x, y, z, x_array, val_array):
    padval = 1e20
    x0 = np.hstack(([-padval], x_array, [padval]))
    vals0 = np.hstack(([val_array[0]], val_array, [val_array[-1]]))
    return interp1d(x0, vals0)(x)

x_func = Function(H_2d).interpolate(Expression('x[0]'))
elev_init = Function(H_2d)
elev_init.dat.data[:] = elevation(x_func.dat.data, 0, 0,
                                  elev_x, elev_v)

# create 3d equations

# extrude mesh
n_layers = 6
mesh = extrudeMeshSigma(mesh2d, n_layers, h_mean)

# function spaces
P1 = FunctionSpace(mesh, 'CG', 1, vfamily='CG', vdegree=1)
U = VectorFunctionSpace(mesh, 'DG', 1, vfamily='CG', vdegree=1)
U_visu = VectorFunctionSpace(mesh, 'CG', 1, vfamily='CG', vdegree=1)
U_scalar = FunctionSpace(mesh, 'DG', 1, vfamily='CG', vdegree=1)
H = FunctionSpace(mesh, 'CG', 2, vfamily='CG', vdegree=1)

eta3d = Function(H, name='Elevation')
bathymetry3d = Function(P1, name='Bathymetry')
copy2dFieldTo3d(swe2d.bathymetry, bathymetry3d)
uv3d = Function(U, name='Velocity')
w3d = Function(H, name='Velocity')
salt3d = Function(H, name='Salinity')

mom_eq3d = mode3d.momentumEquation(mesh, U, U_scalar, uv3d, eta3d,
                                   w3d,
                                   bathymetry3d,
                                   swe2d.boundary_markers,
                                   swe2d.boundary_len, nonlin=nonlin)
salt_eq3d = mode3d.tracerEquation(mesh, H, salt3d, eta3d, uv3d, w3d,
                                  swe2d.boundary_markers,
                                  swe2d.boundary_len)

T = 2 * 24 * 3600  # 100*24*3600
TExport = 80.0
Umag = Constant(1.5)
mesh_dt = swe2d.getTimeStepAdvection(Umag=Umag)
dt = float(np.floor(mesh_dt.dat.data.min()/20.0))
mesh2d_dt = swe2d.getTimeStep(Umag=Umag)
dt_2d = mesh2d_dt.dat.data.min()/20.0
M_modesplit = int(np.ceil(dt/dt_2d))
dt_2d = float(dt/M_modesplit)
if commrank == 0:
    print 'dt =', dt
    print '2D dt =', dt_2d, M_modesplit
    sys.stdout.flush()

# weak boundary conditions
solution_ext_2d = Function(swe2d.space)
u_ext_2d, h_ext_2d = split(solution_ext_2d)
h_amp = 1.0
h_T = 12 * 3600  # 44714.0
uv_river = -0.05
flux_river = -750.0
t = 0.0
T_ramp = 7200.0
ocean_elev_func = lambda t: h_amp * sin(2 * pi * t / h_T)
ocean_elev = Function(swe2d.space.sub(1)).interpolate(Expression(ocean_elev_func(t)))
ocean_elev_3d = Function(H).interpolate(Expression(ocean_elev_func(t)))
river_flux_func = lambda t: flux_river
river_flux = Function(U_scalar_2d).interpolate(Expression(river_flux_func(t)))
river_flux_3d = Function(U_scalar).interpolate(Expression(river_flux_func(t)))
ocean_funcs = {'elev': ocean_elev}
river_funcs = {'flux': river_flux}
ocean_funcs_3d = {'elev': ocean_elev_3d}
river_funcs_3d = {'flux': river_flux_3d}
#swe2d.bnd_functions = {2: ocean_funcs, 1: river_funcs}
#mom_eq3d.bnd_functions = {2: ocean_funcs_3d, 1: river_funcs_3d}

timeStepper2d = mode2d.AdamsBashforth3(swe2d, dt_2d)
uv2d_old, eta2d_old = timeStepper2d.solution_old.split()

timeStepper_mom3d = mode3d.LeapFrogAM3(mom_eq3d, dt)
timeStepper_salt3d = mode3d.LeapFrogAM3(salt_eq3d, dt)

U_2d_file = exporter(U_visu_2d, 'Depth averaged velocity', outputDir, 'Velocity2d.pvd')
eta_2d_file = exporter(P1_2d, 'Elevation', outputDir, 'Elevation2d.pvd')
eta_3d_file = exporter(P1, 'Elevation', outputDir, 'Elevation3d.pvd')
uv_3d_file = exporter(U_visu, 'Velocity', outputDir, 'Velocity3d.pvd')
w_3d_file = exporter(P1, 'V.Velocity', outputDir, 'VertVelo3d.pvd')
salt_3d_file = exporter(P1, 'Salinity', outputDir, 'Salinity3d.pvd')

# assign initial conditions
uv2d, eta2d = swe2d.solution.split()
eta2d.assign(elev_init)
eta2d_old.assign(elev_init)
U_n, eta_n = timeStepper2d.solution_n.split()
eta_n.assign(elev_init)
salt3d.interpolate(Expression('x[0]/1.0e5*10.0+2.0'))
timeStepper_salt3d.solution_old.assign(salt3d)
copy2dFieldTo3d(elev_init, eta3d)

# Export initial conditions
U_2d_file.export(timeStepper2d.solution_old.split()[0])
eta_2d_file.export(timeStepper2d.solution_old.split()[1])
eta_3d_file.export(eta3d)
uv_3d_file.export(uv3d)
w_3d_file.export(w3d)
salt_3d_file.export(w3d)

# The time-stepping loop
T_epsilon = 1.0e-14
cputimestamp = timeMod.clock()
t = 0
i = 1
iExp = 1
next_export_t = t + TExport


def updateForcings(t_new):
    ocean_elev.dat.data[:] = ocean_elev_func(t_new)
    river_flux.dat.data[:] = river_flux_func(t_new)


def updateForcings3d(t_new):
    ocean_elev_3d.dat.data[:] = ocean_elev_func(t_new)
    river_flux_3d.dat.data[:] = river_flux_func(t_new)

from pyop2.profiling import timed_region, timed_function, timing

while t <= T + T_epsilon:

    # For DIRK3 2d time integrator
    #print('solving 2d mode')
    #timeStepper2d.advance(t, dt, swe2d.solution, updateForcings)
    #print('preparing 3d fields')
    #copy2dFieldTo3d(swe2d.solution.split()[1], eta3d)
    #print('solving 3d mode')
    #timeStepper_mom3d.advance(t, dt, uv3d, updateForcings3d)
    #print('solving 3d continuity')
    #computeVertVelocity(w3d, uv3d, bathymetry3d)
    #print('solving 3d tracers')
    #timeStepper_salt3d.advance(t, dt, salt3d, None)

    # LF-AM3 time integration loop
    with timed_region('aux_functions'):
        eta_n = timeStepper2d.solution_nplushalf.split()[1]
        copy2dFieldTo3d(eta_n, eta3d)  # at t_{n+1/2}
    #print('solving 3d tracers')  # salt3d is at t_{n+1/2}
    with timed_region('saltEq'):
        timeStepper_salt3d.predict(t, dt, salt3d, updateForcings3d)
    #print('solving 3d mode')  # uv3d is at t_{n+1/2}
    with timed_region('momentumEq'):
        timeStepper_mom3d.predict(t, dt, uv3d, None)
    #print('solving 3d continuity')  # w3d is at t_{n+1/2}
    with timed_region('continuityEq'):
        computeVertVelocity(w3d, uv3d, bathymetry3d)
    #print('solving 2d mode')  # swe2d.solution is at t_{n+1}
    with timed_region('mode2d'):
        #timeStepper2d.advance(t, dt, swe2d.solution, updateForcings)
        timeStepper2d.advanceMacroStep(t, dt_2d, M_modesplit,
                                       swe2d.solution, updateForcings)
    #print('preparing 3d fields')
    with timed_region('aux_functions'):
        eta_nplushalf = timeStepper2d.solution_nplushalf.split()[1]
        copy2dFieldTo3d(eta_nplushalf, eta3d)  # at t_{n+1/2}
    #print('solving 3d tracers')
    with timed_region('saltEq'):
        timeStepper_salt3d.correct(t, dt, salt3d, updateForcings3d)  # at t{n+1}
    #print('solving 3d mode')
    with timed_region('momentumEq'):
        timeStepper_mom3d.correct(t, dt, uv3d, None)  # at t{n+1}
    #print('solving 3d continuity')
    with timed_region('continuityEq'):
        computeVertVelocity(w3d, uv3d, bathymetry3d)  # at t{n+1}

    # Write the solution to file
    if t >= next_export_t - T_epsilon:
        cputime = timeMod.clock() - cputimestamp
        cputimestamp = timeMod.clock()
        norm_h = norm(swe2d.solution.split()[1])
        norm_u = norm(swe2d.solution.split()[0])

        if commrank == 0:
            line = ('{iexp:5d} {i:5d} T={t:10.2f} '
                    'eta norm: {e:10.4f} u norm: {u:10.4f} {cpu:5.2f}')
            print(line.format(iexp=iExp, i=i, t=t, e=norm_h,
                              u=norm_u, cpu=cputime))
            sys.stdout.flush()
        U_2d_file.export(timeStepper2d.solution_old.split()[0])
        eta_2d_file.export(timeStepper2d.solution_old.split()[1])
        eta_3d_file.export(eta3d)
        uv_3d_file.export(uv3d)
        w_3d_file.export(w3d)
        salt_3d_file.export(salt3d)
        next_export_t += TExport
        iExp += 1

        if commrank == 0:
            print 'iter', i, 'dt', dt
            labels = ['mode2d', 'momentumEq', 'saltEq', 'continuityEq',
                      'aux_functions']
            cost = {}
            relcost = {}
            totcost = 0
            for label in labels:
                value = timing(label, reset=True)
                cost[label] = value
                totcost += value
            for label in labels:
                c = cost[label]
                relcost = c/totcost
                print '{0:25s} : {1:11.6f} {2:11.2f}'.format(label, c, relcost)
                sys.stdout.flush()

    # Move to next time step
    t += dt
    i += 1
