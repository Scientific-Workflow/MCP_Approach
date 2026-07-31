import sys, os, traceback

# Ensure working directory exists
os.makedirs("/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0", exist_ok=True)
os.chdir("/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0")
try:
    # --- User task code ---
    import numpy as np
    from scipy.interpolate import griddata
    
    d = np.load("/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0/field_final.npz")
    X, Y, U, V = d["X"], d["Y"], d["U"], d["V"]
    
    # Flatten scattered nodal data
    xs = X.ravel(); ys = Y.ravel()
    us = U.ravel(); vs = V.ravel()
    
    L = 2*np.pi
    N = 128  # uniform grid resolution
    # periodic grid (exclude endpoint 2pi since periodic)
    gx = np.linspace(0, L, N, endpoint=False)
    gy = np.linspace(0, L, N, endpoint=False)
    GX, GY = np.meshgrid(gx, gy, indexing='xy')  # GX[j,i]=gx[i], GY[j,i]=gy[j]
    
    # To handle periodicity at interpolation, tile the scattered points into 3x3
    offs = [-L, 0, L]
    pts_list=[]; u_list=[]; v_list=[]
    for ox in offs:
        for oy in offs:
            pts_list.append(np.column_stack([xs+ox, ys+oy]))
            u_list.append(us); v_list.append(vs)
    pts = np.vstack(pts_list)
    uu = np.concatenate(u_list); vv = np.concatenate(v_list)
    
    Ug = griddata(pts, uu, (GX, GY), method='linear')
    Vg = griddata(pts, vv, (GX, GY), method='linear')
    print("NaNs U:", np.isnan(Ug).sum(), "NaNs V:", np.isnan(Vg).sum())
    
    # Remove mean flow (a constant mean cannot come from a periodic stream function;
    # psi is defined up to the mean-flow part). Keep record of means.
    Umean = np.nanmean(Ug); Vmean = np.nanmean(Vg)
    print("Umean,Vmean:", Umean, Vmean)
    Up = Ug - Umean
    Vp = Vg - Vmean
    
    # Vorticity omega = dV/dx - dU/dy, computed spectrally on periodic box
    kx = np.fft.fftfreq(N, d=L/N) * 2*np.pi   # wavenumbers
    ky = np.fft.fftfreq(N, d=L/N) * 2*np.pi
    KX, KY = np.meshgrid(kx, ky, indexing='xy')  # matches GX,GY layout (axis0=y,axis1=x)
    
    Uhat = np.fft.fft2(Up)
    Vhat = np.fft.fft2(Vp)
    # derivatives: d/dx -> i*KX (axis1), d/dy -> i*KY (axis0)
    dVdx = np.fft.ifft2(1j*KX*Vhat)
    dUdy = np.fft.ifft2(1j*KY*Uhat)
    omega = np.real(dVdx - dUdy)
    
    # Poisson: laplacian(psi) = -omega  (since omega = v_x - u_y and u=psi_y, v=-psi_x
    #   => omega = -psi_xx - psi_yy = -lap(psi)  => lap(psi) = -omega)
    omghat = np.fft.fft2(omega)
    K2 = KX**2 + KY**2
    K2[0,0] = 1.0  # avoid div by zero; mean of psi arbitrary
    psihat = omghat / K2   # lap psi = -omega -> -K2 psihat = -omghat -> psihat=omghat/K2
    psihat[0,0] = 0.0
    psi = np.real(np.fft.ifft2(psihat))
    
    print("psi range:", psi.min(), psi.max())
    
    np.savez("/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0/psi_final.npz",
             psi=psi, GX=GX, GY=GY, omega=omega,
             Ug=Ug, Vg=Vg, Umean=Umean, Vmean=Vmean, time=float(d["time"]))
    print("saved psi_final.npz")
    # --- End user code ---
    print("__TASK_SUCCESS__")
except Exception as e:
    print(f"__TASK_FAILED__: {e}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)
