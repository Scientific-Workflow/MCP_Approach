molecular_dynamics = """I would like to have a 2-task workflow consisting of one producer and one consumer task.
The producer runs a LAMMPS molecular dynamics simulation of crystallization and generates trajectory data.
The consumer runs OVITO, which reads the resulting trajectory dump file, identifies diamond structures
using the diamond structure identification modifier, renders each frame using the TachyonRenderer, and
saves the output as PNG images."""

cosmology = """Submit /lcrc/project/PEDAL/jacoboh/HACC/SampleRun_go/subme.pbs via qsub (run qsub from that directory so $PBS_O_WORKDIR resolves correctly),
poll with qstat until it finishes, then visualize the resulting output. Use only the paper and whatever you find by exploring output/ and analysis/
under that same directory -- do not assume any configuration or code beyond what's actually there. The workflow consists of three tasks: a producer
(simulation) task, an analysis task, and a visualization task. The producer task executes a HACC cosmological simulation using 8 MPI ranks.
It generates particle snapshot data representing the state of a dark matter universe at a given timestep. The snapshot is distributed across MPI
ranks and contains particle properties including positions, velocities, masses, and gravitational potentials. The analysis task identifies halos in
the simulation particle snapshots using a two-step approach. First, it identifies Friends-of-Friends (FOF) halos by linking particles whose separations
are below a chosen linking length. For each FOF halo, the halo center is defined as the position of the particle with the minimum gravitational potential.
Each FOF halo is then associated with a Spherical Overdensity (SOD) halo by growing spherical shells around the FOF center until the enclosed mean density
reaches a specified multiple of the critical density of the universe. The output of this task is a halo catalog containing halo properties such as
positions, masses, and characteristic radii (R_Delta, M_Delta). The visualization task generates 2D slices of selected physical fields in
the xy-plane, spanning the full simulation box with a fixed thickness of 4 Mpc/h in the z-direction. The slicing plane is positioned to intersect the
most massive halo in the simulation box, using its z-coordinate (e.g., z = 179.14 Mpc/h) as the slice center. The task computes and renders the dark matter
density field within this slice. The final output of the entire workflow is the dark matter density slice image, which visualizes the projected structure of
matter distribution in the simulation volume and highlights the region around the most massive halo. The workflow follows a producer-analysis-visualization
pattern in which both downstream tasks depend on the particle snapshot produced by the simulation. Once the snapshot is available, the analysis task produces
a halo catalog, and the visualization task generates the final dark matter density slice image for scientific interpretation. The visualized image must match
the image in the paper."""

eddy = """I would like to have a 2-task workflow consisting of one producer and one consumer task. The producer runs a Nek5000 computational fluid dynamics simulation
of the eddy_uv case -- an exact 2D solution to the Navier-Stokes equations based on Walsh's decaying vortex array with an additional translational velocity --
using the input files located at /lcrc/project/PEDAL/Nek5000/NekExamples-master/eddy_uv (specifically eddy_uv.rea, eddy_uv.usr, eddy_uv.map, SIZE, and SESSION.NAME)
and generates field output files. The consumer reads the resulting Nek5000 field files, computes the stream function from the velocity field, and renders contour plots
of the stream function to visualize the eddy vortex pattern as shown in Figure 1 of Walsh (1992), saving the output as PNG images. The producer runs on 8 MPI ranks and
the consumer runs on a single process."""
