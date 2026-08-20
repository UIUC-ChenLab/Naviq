from pipeline_experiment import run_ppe_case


RUN_LABEL = "smartnic_hbm_ppe_dma_pkt500_hbmclk1600_buf128_mo32_rrob128_funcpreload"

run_ppe_case()

print(f"[{RUN_LABEL}] PASS")
