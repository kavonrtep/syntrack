# Source data:


List of directories containing assembly fai files and blast tables with location SCM
- fai: `pseudomolecules+unanchored.fasta.fai`
- SCM blast table: `./analysis/painting_probes_CAM/all_oligos/assembly_x_oligos_CAMv2r2.blast_out`

Genomes:

- `/mnt/ceph/454_data/Pisum_pangenome/assemblies/JI1006_2026-01-19`
- `/mnt/ceph/454_data/Pisum_pangenome/assemblies/JI15_2026-01-19`
- `/mnt/ceph/454_data/Pisum_pangenome/assemblies/IPIP201118_2026-01-27`
- `/mnt/ceph/454_data/Pisum_pangenome/assemblies/JI2822_2026-02-02`
- `/mnt/ceph/454_data/Pisum_pangenome/assemblies/IPIP200590_2026-02-04`
- `/mnt/ceph/454_data/Pisum_pangenome/assemblies/JI281_2026-02-05`
- `/mnt/ceph/454_data/Pisum_pangenome/assemblies/IPIP200731_2026-04-14`
- `/mnt/ceph/454_data/Pisum_pangenome/assemblies/IPIP200579_2026-04-14`



# data linking
 - create symbolic links to the data in the `data` directory of this repository
 - use name of the directory. for example `JI1006_2026-01-19.fai` and `JI1006_2026-01-19.blast_out` for the fai and blast table respectively.
 - create also corresponding `genomes.csv` file with fai and SCM columns
 - Handle creation of links and table using bash script so it can be later easily updated when new data is added.
