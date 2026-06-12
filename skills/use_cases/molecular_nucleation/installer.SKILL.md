---
name: use_cases/molecular_nucleation/installer
description: >
  Installer behavior for the molecular nucleation project. Covers pip-installable
  packages, the LAMMPS source-build requirement on Linux/WSL, and the package reuse
  skip logic.
---

# Molecular Nucleation — Installer Skill

Sets up the local venv with all packages needed for the LAMMPS water crystallization workflow.

---

## Current Installer Behavior

1. **Phase 1:** Read or generate `builds/requirements.txt`. Return it as `dockerfile`. Do NOT call an LLM to generate a new one if the file already exists.
2. **Orchestrator:** Always approves immediately (sets `dockerfile_approved=True`).
3. **Phase 2:** Check if all packages are already installed. If yes, skip pip install and return. If no, run `pip install -r builds/requirements.txt`.

---

## Package Requirements

```
ovito
parsl>=2024.0.0
numpy
matplotlib
Pillow
```

**LAMMPS:** Must be built from source (serial, no MPI) on Linux/WSL — it is NOT pip-installable for this use case. See build notes below.

**Do NOT add:** scipy, ase, mdanalysis, mpi4py, h5py, or any other package not listed above.

---

## LAMMPS Source Build (Linux/WSL)

LAMMPS must be compiled with `BUILD_MPI=off` to avoid MPI initialization errors in Parsl workers. The pip `lammps` wheel calls `MPI_Init` on import even in serial mode, causing `WorkerLost` / `ORTE_ERROR_LOG` crashes.

### System dependencies (apt)
```
python3-dev build-essential cmake wget git
libfftw3-dev libpng-dev libjpeg-dev
libosmesa6 libgl1 libegl1 libopengl0
libglib2.0-0 libxkbcommon0 libxcb-icccm4 libxcb-image0
libxcb-keysyms1 libxcb-render-util0 libxcb-xinerama0 libxcb-xkb1
libxrender1 libxi6 libxtst6
```

### cmake flags
```
-DBUILD_MPI=off -DBUILD_OMP=off -DBUILD_SHARED_LIBS=on
-DLAMMPS_EXCEPTIONS=on -DPKG_MANYBODY=on -DPKG_MOLECULE=on
-DPKG_KSPACE=on -DPKG_RIGID=on -DPKG_PYTHON=on -DFFT=FFTW3
```
Install to `/usr/local` via `make install`, then set `LD_LIBRARY_PATH=/usr/local/lib`.

### LAMMPS Python bindings
After the shared library is installed, install the Python bindings from the source tarball:
```bash
cd lammps-<version>/python && pip install .
```

### Environment variables (set before running)
```
LIBGL_ALWAYS_SOFTWARE=1
PYOPENGL_PLATFORM=osmesa
OVITO_GUI_MODE=0
LD_LIBRARY_PATH=/usr/local/lib
```

---

## Notes

- LAMMPS source build takes ~20 min; once installed in the venv it is reused across runs
- `builds/.requirements_hash` can store an MD5 of the last installed requirements for skip detection
