import sys, os, traceback

# Ensure working directory exists
os.makedirs("/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0", exist_ok=True)
os.chdir("/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0")
try:
    # --- User task code ---
    import numpy as np
    import pymech
    from pymech.neksuite import readnek
    from scipy.interpolate import griddata
    
    CASE = "/lcrc/project/PEDAL/jacoboh/Nek5000/NekExamples-master/eddy_uv"
    IDX = 1
    f = f"{CASE}/eddy_uv0.f{IDX:05d}"
    fld = readnek(f)
    X = np.array([e.pos[0] for e in fld.elem]).ravel()
    Y = np.array([e.pos[1] for e in fld.elem]).ravel()
    Uf = np.array([e.vel[0] for e in fld.elem]).ravel()
    Vf = np.array([e.vel[1] for e in fld.elem]).ravel()
    
    L=2*np.pi; N=128
    gx=np.linspace(0,L,N,endpoint=False); gy=np.linspace(0,L,N,endpoint=False)
    GX,GY=np.meshgrid(gx,gy,indexing='xy')
    offs=[-L,0,L]; P=[];UU=[];VV=[]
    for ox in offs:
        for oy in offs:
            P.append(np.column_stack([X+ox,Y+oy])); UU.append(Uf); VV.append(Vf)
    P=np.vstack(P); UU=np.concatenate(UU); VV=np.concatenate(VV)
    Ug=griddata(P,UU,(GX,GY),method='linear'); Vg=griddata(P,VV,(GX,GY),method='linear')
    Umean=np.nanmean(Ug); Vmean=np.nanmean(Vg)
    Up=Ug-Umean; Vp=Vg-Vmean
    kx=np.fft.fftfreq(N,d=L/N)*2*np.pi; ky=kx
    KX,KY=np.meshgrid(kx,ky,indexing='xy')
    Uhat=np.fft.fft2(Up); Vhat=np.fft.fft2(Vp)
    omega=np.real(np.fft.ifft2(1j*KX*Vhat)-np.fft.ifft2(1j*KY*Uhat))
    K2=KX**2+KY**2; K2[0,0]=1.0
    psihat=np.fft.fft2(omega)/K2; psihat[0,0]=0.0
    psi=np.real(np.fft.ifft2(psihat))
    ke=0.5*np.mean(Ug**2+Vg**2)
    np.savez(f"/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0/psi_frame{IDX:02d}.npz",psi=psi,GX=GX,GY=GY,
             time=float(fld.time),ke=ke,Umean=Umean,Vmean=Vmean)
    print(f"frame {IDX} t={fld.time} psi[{psi.min():.4f},{psi.max():.4f}] ke={ke:.5f}")
    # --- End user code ---
    print("__TASK_SUCCESS__")
except Exception as e:
    print(f"__TASK_FAILED__: {e}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)
