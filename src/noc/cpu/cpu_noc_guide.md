# Simulating CPUs with the Garnet NoC

This guide explains how to boot a Full System (FS) Linux environment over the simulated Garnet Network-on-Chip (NoC). The CPU and its caches connect to the NoC via `CpuNocBridge` components (acting as Network Master Units or NMUs), while the physical memory connects via DDR memory controllers (Network Slave Units or NSUs).

## General Usage

To simulate a CPU, use the `noc_config_fs.py` script. The script automatically mounts the CPU, caches, and memory controllers into a unified address map according to your chosen NoC topology file.

> **Release status:** the CPU scripts below are retained historical examples,
> not portable public-release commands. The old flat `1nmu_to_ddr` topology was
> archived because it is not a complete supported topology bundle. Replace
> `<supported-topology-bundle>` only after validating a complete bundle and
> documenting its command and regression.

### Important Options

- `--noc-topology`: **(Required)** The path to the `.nts` topology file. **Ensure this topology has a memory controller mapped to the architecture's main memory address (e.g., `0x80000000` for RISC-V)**. If you use a topology without a memory controller (like `1_to_1_far.nts`), the simulation will panic when the OS tries to access unmapped memory.
- `--cpu-type`: Choose the CPU model (`TimingSimple`, `AtomicSimple`, `O3`). `TimingSimple` is recommended for accurate NoC stalling behavior.
- `--kernel` and `--disk-image`: Provide the path to the Linux kernel and the root filesystem disk image.

---

## Running in Syscall Emulation (SE) Mode

If you do not need to boot a full operating system and simply want to test how a standalone userspace binary runs over the NoC memory map, use the `noc_config_cpu_test.py` script.

SE mode avoids the lengthy Linux boot process and checkpointing entirely. It maps the requested binary directly into the NoC's memory address space and translates all system calls on the host OS.

### Example (ARM)

```bash
build/ARM/gem5.opt \
  --outdir=m5out_arm_se \
  src/noc/setup/legacy/noc_config_cpu_test.py \
  --noc-topology=<supported-topology-bundle> \
  --binary=tests/test-progs/hello/bin/arm/linux/hello
```

### Example (X86)

```bash
build/X86/gem5.opt \
  --outdir=m5out_x86_se \
  src/noc/setup/legacy/noc_config_cpu_test.py \
  --noc-topology=<supported-topology-bundle> \
  --binary=tests/test-progs/hello/bin/x86/linux/hello
```

### Example (RISC-V)

```bash
build/RISCV/gem5.opt \
  --outdir=m5out_riscv_se \
  src/noc/setup/legacy/noc_config_cpu_test.py \
  --noc-topology=<supported-topology-bundle> \
  --binary=tests/test-progs/hello/bin/riscv/linux/hello
```

> **Note:** `noc_config.py` (without `_cpu_test`) uses synthetic traffic generators instead of real CPUs. Use `noc_config_cpu_test.py` for CPU-based SE workloads.

---

## Running with RISC-V

RISC-V is the default architecture tested for NoC integration.

```bash
build/RISCV/gem5.opt \
  --outdir=m5out_riscv_noc \
  src/noc/setup/legacy/noc_config_fs.py \
  --kernel=fs_resources/riscv/bootloader-vmlinux-5.10 \
  --disk-image=fs_resources/riscv/riscv-disk.img \
  --noc-topology=<supported-topology-bundle> \
  --cpu-type=TimingSimple
```

### ISA Modifications for RISC-V
When running RISC-V in FS mode with `bbl` (Berkeley Boot Loader) or OpenSBI firmware, you may encounter an infinite nested trap loop during the first timer interrupt due to the firmware illegally accessing the FPU when `status.fs == OFF`. 

To fix this, the following lines in `src/arch/riscv/isa/decoder.isa` and `src/arch/riscv/isa/formats/fp.isa` must be modified so that Machine Mode (`PRV_M`) bypasses the exception check:

```cpp
// Check for disabled FPU
if (xc->readMiscReg(MISCREG_STATUS_FS) == FPUStatus::OFF && xc->readMiscReg(MISCREG_PRV) != PRV_M) {
    return std::make_shared<IllegalInstFault>("FPU is off", machInst);
}
```
*Note: If you run other ISAs like ARM or x86, you do not need these specific RISC-V firmware fixes.*

---

## Running with ARM

ARM support is built into the `noc_config_fs.py` script. It automatically detects the ISA built and configures the `VExpress_GEM5_V2` platform. 

Make sure you have compiled the ARM gem5 binary (`build/ARM/gem5.opt`).

```bash
build/ARM/gem5.opt \
  --outdir=m5out_arm_noc \
  src/noc/setup/legacy/noc_config_fs.py \
  --kernel=fs_resources/arm/binaries/vmlinux.arm64 \
  --disk-image=fs_resources/arm/ubuntu-18.04-arm64-docker.img \
  --noc-topology=<supported-topology-bundle> \
  --cpu-type=TimingSimple
```
*(Ensure paths point to your actual ARM kernel and rootfs).*

---

## Running with x86

X86 support dynamically integrates gem5's `makeLinuxX86System` PC component map to correctly construct its dual APIC/I8259 layout. Like ARM, it detects the `x86` ISA gracefully.

Ensure you have compiled the X86 object (`build/X86/gem5.opt`).

```bash
build/X86/gem5.opt \
  --outdir=m5out_x86_noc \
  src/noc/setup/legacy/noc_config_fs.py \
  --kernel=fs_resources/x86/vmlinux-5.4.49 \
  --disk-image=fs_resources/x86/x86-ubuntu-18.04.img \
  --noc-topology=<supported-topology-bundle> \
  --cpu-type=TimingSimple
```
*(Ensure paths point to your actual x86 kernel and rootfs).*

---

## Connecting to the Simulation Terminal (`m5term`)
When booting in Full System mode, you interact with the simulated machine's shell by connecting to its proxy terminal (default port `3456`). This requires the `m5term` utility, which is located inside the gem5 source tree but must be compiled separately before first use.

**Compile `m5term`:**
```bash
cd util/term
make
cd ../..
```

**Connect to the active simulation:**
In a separate terminal window, while your gem5 simulation is running, execute:
```bash
./util/term/m5term localhost 3456
```
*(If you are running multiple gem5 simulations simultaneously, the port will auto-increment to 3457, 3458, etc.)*

---

## Fast Booting using Checkpoints

Simulating the full Linux boot process through the NoC with detailed CPU models (like `TimingSimpleCPU`) can be impractically slow, often taking hours just to reach the login prompt.

To bypass this slow boot process, use a **checkpoint/restore workflow**:

### Step 1: Create a Fast-Boot Checkpoint
Use a baseline configuration without the NoC (e.g., `AtomicSimpleCPU`) to boot the system quickly.

**For RISC-V:**
```bash
build/RISCV/gem5.opt configs/example/riscv/fs_linux_simple.py \
    --kernel=fs_resources/riscv/bootloader-vmlinux-5.10 \
    --disk-image=fs_resources/riscv/riscv-disk.img \
    --checkpoint-at-end
```
When it reaches the login prompt over the terminal (`m5term localhost 3456`), press `Ctrl-C` to generate the checkpoint.

**For ARM:**
```bash
M5_PATH=$(pwd)/fs_resources/arm build/ARM/gem5.opt configs/example/arm/starter_fs.py \
    --kernel=fs_resources/arm/binaries/vmlinux.arm64 \
    --disk-image=fs_resources/arm/ubuntu-18.04-arm64-docker.img \
    --checkpoint
```
When it reaches the login prompt over the terminal (`m5term localhost 3456`), type `m5 checkpoint` inside the simulated Linux system. This will trigger the `starter_fs.py` script to drop a checkpoint to the `m5out/cpt.*` directory and exit.

**For X86:**
```bash
build/X86/gem5.opt configs/deprecated/example/fs.py \
    --kernel=fs_resources/x86/vmlinux-5.4.49 \
    --disk-image=fs_resources/x86/x86-ubuntu-18.04.img \
    --script=configs/boot/hack_back_ckpt.rcS
```
This script will automatically boot the kernel, execute the `hack_back_ckpt.rcS` script, take a checkpoint at the `m5out/cpt.*` directory, and terminate itself without manual interaction via `m5term`.

### Step 2: Restore Checkpoint into NoC Simulation
Restore the generated checkpoint into your NoC simulation using the `--checkpoint-dir` flag. The syntax is identical regardless of ISA.

**Example Restore Command (RISC-V):**
```bash
build/RISCV/gem5.opt src/noc/setup/legacy/noc_config_fs.py \
    --noc-topology=<supported-topology-bundle> \
    --kernel=fs_resources/riscv/bootloader-vmlinux-5.10 \
    --disk-image=fs_resources/riscv/riscv-disk.img \
    --checkpoint-dir=m5out/cpt.<TICKNUMBER> \
    --cpu-type=TimingSimple
```

**Example Restore Command (X86):**
```bash
build/X86/gem5.opt \
    --outdir=m5out_x86_noc \
    src/noc/setup/legacy/noc_config_fs.py \
    --kernel=fs_resources/x86/vmlinux-5.4.49 \
    --disk-image=fs_resources/x86/x86-ubuntu-18.04.img \
    --noc-topology=<supported-topology-bundle> \
    --checkpoint-dir=m5out/cpt.<TICKNUMBER> \
    --cpu-type=TimingSimple
```
*(Replace `<TICKNUMBER>` with the actual tick number from your checkpoint directory, e.g. `cpt.3540660275500`.)*

The simulation will instantly resume from the checkpoint, routing all subsequent traffic through the simulated Garnet NoC.

### Step 3: Connect via m5term
In a separate terminal, connect to the simulated serial console:
```bash
./util/term/m5term localhost 3456
```

### Providing a Script After Restore
By default, the `hack_back_ckpt.rcS` checkpoint script drops into a non-interactive `/bin/bash` that is **not** connected to the serial console (`ttyS0`). This means you **cannot** type commands interactively via `m5term` unless you provide a script.

Use `--script=<path>` to specify what runs after the checkpoint is restored:

**Interactive login prompt (X86):**
```bash
--script=configs/boot/interact.rcS
```
This spawns `getty` on `ttyS0`, giving you a login prompt. Be patient — spawning `getty` takes significant simulated time with `TimingSimpleCPU`.

**Run a specific command and exit:**
Create your own `.rcS` script:
```bash
#!/bin/sh
echo "Running my workload..."
ls -la /
/sbin/m5 exit
```
Then pass `--script=my_workload.rcS`. Output appears in `m5out/system.pc.com_1.device`.

---

## Getting Kernels and Disk Images

To run Full System (FS) mode, you **must** supply both a compiled Linux Kernel and a compatible ext-based disk image harboring a root filesystem. Without these, the gem5 PC simulator cannot boot an OS.

You can download standard, pre-compiled distributions natively provided by the gem5 project. You should store these within an `fs_resources/<architecture>/` directory matching your build.

### X86 Resources
You will need an x86 statically-compiled kernel and a compatible `x86` ubuntu image.

```bash
mkdir -p fs_resources/x86

# Download the x86 Kernel (v5.4.49)
wget -O fs_resources/x86/vmlinux-5.4.49 https://dist.gem5.org/dist/v22-0/kernels/x86/static/vmlinux-5.4.49

# Download and Extract the Ubuntu 18.04 X86 Image
wget -O fs_resources/x86/x86-ubuntu-18.04.img.gz https://dist.gem5.org/dist/v22-0/images/x86/ubuntu-18-04/x86-ubuntu.img.gz
gunzip fs_resources/x86/x86-ubuntu-18.04.img.gz
```

### ARM Resources
ARM platforms require AArch64 kernels. You can fetch similar resources geared for ARM64 generic devices:

```bash
mkdir -p fs_resources/arm

# Download the ARM64 Kernel
wget -O fs_resources/arm/vmlinux.arm64 https://dist.gem5.org/dist/v22-0/kernels/arm/static/vmlinux.arm64

# Download and Extract the Ubuntu 18.04 ARM64 Image
wget -O fs_resources/arm/ubuntu-18.04-arm64-docker.img.gz https://dist.gem5.org/dist/v22-0/images/arm/ubuntu-18-04/ubuntu-18.04-arm64-docker.img.gz
gunzip fs_resources/arm/ubuntu-18.04-arm64-docker.img.gz
```

You must pass the explicit paths pointing to these freshly downloaded files via the `--kernel=` and `--disk-image=` parameters whenever testing `noc_config_fs.py`.
