from pipeline_experiment import run_direct_case


RUN_LABEL = "smartnic_hbm_direct_dma_pkt500_hbmclk1600_buf128_mo32_rrob128_funcpreload"

run_direct_case()

print(f"[{RUN_LABEL}] PASS")
