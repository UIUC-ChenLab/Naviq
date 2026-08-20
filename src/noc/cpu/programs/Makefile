CC ?= gcc
CFLAGS ?= -O2 -static -Wall -Wextra
FREESTANDING_CFLAGS ?= -O2 -static -nostdlib -ffreestanding -fno-stack-protector -fno-pie -no-pie -Wall -Wextra

HBM_DMA_BASE_FLAGS = -DDESC_BASE=0x4000000000ULL -DPACKET_BASE=0x4010000000ULL -DSCRATCH_BASE=0x4020000000ULL -DDESC_PTR_BASE=0x10000000ULL -DSCRATCH_PTR_BASE=0x12000000ULL -DDMA_CTRL_BASE=0x40000000ULL -DCPU_WRITES_DESCRIPTORS=0 -DCPU_INIT_SCRATCH=0
HBM_CPU_WRITE_DMA_BASE_FLAGS = -DDESC_BASE=0x4000000000ULL -DPACKET_BASE=0x4010000000ULL -DSCRATCH_BASE=0x4020000000ULL -DDESC_PTR_BASE=0x10000000ULL -DSCRATCH_PTR_BASE=0x12000000ULL -DDMA_CTRL_BASE=0x40000000ULL -DCPU_WRITES_DESCRIPTORS=1 -DCPU_INIT_SCRATCH=1

all: ddr_dma_control_x86 ddr_dma_control_data_only_pkt100_x86 ddr_dma_control_data_only_bp_pkt100_x86 ddr_dma_control_data_only_limiter_pkt100_x86 ddr_dma_control_data_only_limiter_pkt500_x86 ddr_dma_control_heavy_poll_pkt100_x86 ddr_dma_control_ddr_heavy_pkt100_x86 ddr_dma_control_data_only_pkt500_x86 ddr_dma_control_ddr_heavy_pkt500_x86 ddr_dma_control_data_only_hbm_pkt100_x86 ddr_dma_control_hbm_heavy_pkt100_x86 ddr_dma_control_hbm_cpuwrite_x86 ddr_dma_control_data_only_hbm_cpuwrite_pkt100_x86 ddr_dma_control_data_only_bp_hbm_cpuwrite_pkt100_x86 ddr_dma_control_data_only_limiter_hbm_cpuwrite_pkt100_x86 ddr_dma_control_data_only_limiter_hbm_cpuwrite_pkt500_x86 ddr_dma_control_heavy_poll_hbm_cpuwrite_pkt100_x86 ddr_dma_control_hbm_heavy_cpuwrite_pkt100_x86 ddr_dma_control_data_only_hbm_cpuwrite_pkt500_x86 ddr_dma_control_data_only_hbm_cpuwrite_pkt500_fixed1024_x86 ddr_dma_control_hbm_heavy_cpuwrite_pkt500_x86 cpu_ddr_memory_x86 cpu_ddr_walk_x86 ppe_flow_prefix_control_x86 ppe_flow_prefix_mmio_x86 ppe_five_tuple_hash_control_x86 ppe_five_tuple_hash_mmio_x86

ddr_dma_control_x86: ddr_dma_control.c
	$(CC) $(FREESTANDING_CFLAGS) -o $@ $<

ddr_dma_control_data_only_pkt100_x86: ddr_dma_control.c
	$(CC) $(FREESTANDING_CFLAGS) -DPACKETS=100 -DCONTROL_MODE_DEFAULT=1 -o $@ $<

ddr_dma_control_data_only_bp_pkt100_x86: ddr_dma_control.c
	$(CC) $(FREESTANDING_CFLAGS) -DPACKETS=100 -DCONTROL_MODE_DEFAULT=1 -DDATA_ONLY_POST_DONE_WAIT_ITERS=200000 -o $@ $<

ddr_dma_control_data_only_limiter_pkt100_x86: ddr_dma_control.c
	$(CC) $(FREESTANDING_CFLAGS) -DPACKETS=100 -DCONTROL_MODE_DEFAULT=0 -DMAX_POLL_ITERS=200000 -o $@ $<

ddr_dma_control_data_only_limiter_pkt500_x86: ddr_dma_control.c
	$(CC) $(FREESTANDING_CFLAGS) -DPACKETS=500 -DCONTROL_MODE_DEFAULT=0 -DMAX_POLL_ITERS=1000000 -o $@ $<

ddr_dma_control_heavy_poll_pkt100_x86: ddr_dma_control.c
	$(CC) $(FREESTANDING_CFLAGS) -DPACKETS=100 -DCONTROL_MODE_DEFAULT=2 -o $@ $<

ddr_dma_control_ddr_heavy_pkt100_x86: ddr_dma_control.c
	$(CC) $(FREESTANDING_CFLAGS) -DPACKETS=100 -DCONTROL_MODE_DEFAULT=3 -o $@ $<

ddr_dma_control_data_only_pkt500_x86: ddr_dma_control.c
	$(CC) $(FREESTANDING_CFLAGS) -DPACKETS=500 -DCONTROL_MODE_DEFAULT=1 -o $@ $<

ddr_dma_control_ddr_heavy_pkt500_x86: ddr_dma_control.c
	$(CC) $(FREESTANDING_CFLAGS) -DPACKETS=500 -DCONTROL_MODE_DEFAULT=3 -DDDR_HEAVY_READ_ITERS=8192 -o $@ $<

ddr_dma_control_data_only_hbm_pkt100_x86: ddr_dma_control.c
	$(CC) $(FREESTANDING_CFLAGS) -DPACKETS=100 -DCONTROL_MODE_DEFAULT=1 -DDATA_ONLY_WAIT_ATTEMPTS=200000 $(HBM_DMA_BASE_FLAGS) -o $@ $<

ddr_dma_control_hbm_heavy_pkt100_x86: ddr_dma_control.c
	$(CC) $(FREESTANDING_CFLAGS) -DPACKETS=100 -DCONTROL_MODE_DEFAULT=3 $(HBM_DMA_BASE_FLAGS) -o $@ $<

ddr_dma_control_hbm_cpuwrite_x86: ddr_dma_control.c
	$(CC) $(FREESTANDING_CFLAGS) $(HBM_CPU_WRITE_DMA_BASE_FLAGS) -o $@ $<

ddr_dma_control_data_only_hbm_cpuwrite_pkt100_x86: ddr_dma_control.c
	$(CC) $(FREESTANDING_CFLAGS) -DPACKETS=100 -DCONTROL_MODE_DEFAULT=1 -DDATA_ONLY_WAIT_ATTEMPTS=200000 $(HBM_CPU_WRITE_DMA_BASE_FLAGS) -o $@ $<

ddr_dma_control_data_only_bp_hbm_cpuwrite_pkt100_x86: ddr_dma_control.c
	$(CC) $(FREESTANDING_CFLAGS) -DPACKETS=100 -DCONTROL_MODE_DEFAULT=1 -DDATA_ONLY_POST_DONE_WAIT_ITERS=200000 $(HBM_CPU_WRITE_DMA_BASE_FLAGS) -o $@ $<

ddr_dma_control_data_only_limiter_hbm_cpuwrite_pkt100_x86: ddr_dma_control.c
	$(CC) $(FREESTANDING_CFLAGS) -DPACKETS=100 -DCONTROL_MODE_DEFAULT=0 -DMAX_POLL_ITERS=200000 $(HBM_CPU_WRITE_DMA_BASE_FLAGS) -o $@ $<

ddr_dma_control_data_only_limiter_hbm_cpuwrite_pkt500_x86: ddr_dma_control.c
	$(CC) $(FREESTANDING_CFLAGS) -DPACKETS=500 -DCONTROL_MODE_DEFAULT=0 -DMAX_POLL_ITERS=1000000 $(HBM_CPU_WRITE_DMA_BASE_FLAGS) -o $@ $<

ddr_dma_control_heavy_poll_hbm_cpuwrite_pkt100_x86: ddr_dma_control.c
	$(CC) $(FREESTANDING_CFLAGS) -DPACKETS=100 -DCONTROL_MODE_DEFAULT=2 $(HBM_CPU_WRITE_DMA_BASE_FLAGS) -o $@ $<

ddr_dma_control_hbm_heavy_cpuwrite_pkt100_x86: ddr_dma_control.c
	$(CC) $(FREESTANDING_CFLAGS) -DPACKETS=100 -DCONTROL_MODE_DEFAULT=3 $(HBM_CPU_WRITE_DMA_BASE_FLAGS) -o $@ $<

ddr_dma_control_data_only_hbm_cpuwrite_pkt500_x86: ddr_dma_control.c
	$(CC) $(FREESTANDING_CFLAGS) -DPACKETS=500 -DCONTROL_MODE_DEFAULT=1 $(HBM_CPU_WRITE_DMA_BASE_FLAGS) -o $@ $<

ddr_dma_control_data_only_hbm_cpuwrite_pkt500_fixed1024_x86: ddr_dma_control.c
	$(CC) $(FREESTANDING_CFLAGS) -DPACKETS=500 -DCONTROL_MODE_DEFAULT=1 -DFIXED_PAYLOAD_BYTES=996 $(HBM_CPU_WRITE_DMA_BASE_FLAGS) -o $@ $<

ddr_dma_control_hbm_heavy_cpuwrite_pkt500_x86: ddr_dma_control.c
	$(CC) $(FREESTANDING_CFLAGS) -DPACKETS=500 -DCONTROL_MODE_DEFAULT=3 -DDDR_HEAVY_READ_ITERS=8192 $(HBM_CPU_WRITE_DMA_BASE_FLAGS) -o $@ $<

cpu_ddr_memory_x86: cpu_ddr_memory.c
	$(CC) $(FREESTANDING_CFLAGS) -o $@ $<

cpu_ddr_walk_x86: cpu_ddr_walk.c
	$(CC) $(FREESTANDING_CFLAGS) -o $@ $<

ppe_flow_prefix_control_x86: ppe_flow_prefix_control.c
	$(CC) $(FREESTANDING_CFLAGS) -o $@ $<

ppe_flow_prefix_mmio_x86: ppe_flow_prefix_mmio.c
	$(CC) $(FREESTANDING_CFLAGS) -o $@ $<

ppe_five_tuple_hash_control_x86: ppe_five_tuple_hash_control.c
	$(CC) $(FREESTANDING_CFLAGS) -o $@ $<

ppe_five_tuple_hash_mmio_x86: ppe_five_tuple_hash_mmio.c
	$(CC) $(FREESTANDING_CFLAGS) -o $@ $<

clean:
	rm -f ddr_dma_control_x86 ddr_dma_control_data_only_pkt100_x86 ddr_dma_control_data_only_bp_pkt100_x86 ddr_dma_control_data_only_limiter_pkt100_x86 ddr_dma_control_data_only_limiter_pkt500_x86 ddr_dma_control_heavy_poll_pkt100_x86 ddr_dma_control_ddr_heavy_pkt100_x86 ddr_dma_control_data_only_pkt500_x86 ddr_dma_control_ddr_heavy_pkt500_x86 ddr_dma_control_data_only_hbm_pkt100_x86 ddr_dma_control_hbm_heavy_pkt100_x86 ddr_dma_control_hbm_cpuwrite_x86 ddr_dma_control_data_only_hbm_cpuwrite_pkt100_x86 ddr_dma_control_data_only_bp_hbm_cpuwrite_pkt100_x86 ddr_dma_control_data_only_limiter_hbm_cpuwrite_pkt100_x86 ddr_dma_control_data_only_limiter_hbm_cpuwrite_pkt500_x86 ddr_dma_control_heavy_poll_hbm_cpuwrite_pkt100_x86 ddr_dma_control_hbm_heavy_cpuwrite_pkt100_x86 ddr_dma_control_data_only_hbm_cpuwrite_pkt500_x86 ddr_dma_control_data_only_hbm_cpuwrite_pkt500_fixed1024_x86 ddr_dma_control_hbm_heavy_cpuwrite_pkt500_x86 cpu_ddr_memory_x86 cpu_ddr_walk_x86 ppe_flow_prefix_control_x86 ppe_flow_prefix_mmio_x86 ppe_five_tuple_hash_control_x86 ppe_five_tuple_hash_mmio_x86

.PHONY: all clean
