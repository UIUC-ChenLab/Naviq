# Experiment 5 Endpoint Width Sensitivity Analysis

Source result: `noc_testing/artifacts/generated/results/gem5_endpoint_width_incast_exp5_parameter_sweep_exp5_endpoint_width.csv`
Plan: `noc_testing/sweep_plans/parameter_sweep/endpoint_width_incast_exp5.csv`

This rerun uses the 4-NMU/1-NSU AXI-MM incast topology with interleaved reads/writes, 1000 transactions per source, fixed 512-byte payloads, and fixed buffers `buffers_per_data_vc=4`, `buffers_per_ctrl_vc=4`. Endpoint width is swept at 128, 256, and 512 bits for both spread and compact placements.

The controlled rows now use `bandwidth_MBps=400` per source. The plan also forces `param.tg_*.address_increment=512` so the fixed 512-byte transactions do not overlap and do not trigger the unaligned 256-byte NPP split/RROB tag artifact seen in the first run.

All 48 source-level result rows completed with `gem5_return_code=0`. Full-sweep tracing was off for this rerun.

## Aggregate Results

| row | placement | load | width | mean W lat | mean R lat | W spread | R spread | W CV | R CV | total W BW | total R BW | W/R JFI | max W/R | runtime | RC |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | spread | unlimited | 128 | 246.27 | 239.86 | 17.64 | 17.21 | 0.0261 | 0.0277 | 8089.09 | 8091.12 | 0.9994/0.9994 | 332/361 | 33.19 | 0 |
| 2 | spread | unlimited | 256 | 246.07 | 240.44 | 19.87 | 19.58 | 0.0296 | 0.0306 | 8101.28 | 8103.21 | 0.9992/0.9992 | 339/358 | 33.15 | 0 |
| 3 | spread | unlimited | 512 | 247.13 | 244.53 | 15.16 | 15.76 | 0.0223 | 0.0267 | 8060.58 | 8062.51 | 0.9995/0.9995 | 327/310 | 32.83 | 0 |
| 4 | compact | unlimited | 128 | 134.59 | 6877.51 | 6.74 | 1750.09 | 0.0247 | 0.1251 | 14472.85 | 12815.90 | 1.0/1.0 | 246/10281 | 7.96 | 0 |
| 5 | compact | unlimited | 256 | 134.41 | 6748.10 | 7.66 | 2410.83 | 0.0274 | 0.1696 | 14496.32 | 12812.65 | 1.0/1.0 | 254/10281 | 7.11 | 0 |
| 6 | compact | unlimited | 512 | 134.42 | 6729.89 | 7.52 | 2485.86 | 0.0267 | 0.1715 | 14488.85 | 12811.60 | 1.0/1.0 | 265/10281 | 6.97 | 0 |
| 7 | spread | controlled 400 MB/s/src | 128 | 280.84 | 234.70 | 75.72 | 49.93 | 0.1022 | 0.0764 | 1601.61 | 1601.68 | 1.0/1.0 | 338/293 | 31.13 | 0 |
| 8 | spread | controlled 400 MB/s/src | 256 | 280.79 | 235.78 | 75.99 | 50.29 | 0.1022 | 0.0763 | 1601.61 | 1601.66 | 1.0/1.0 | 336/285 | 30.31 | 0 |
| 9 | spread | controlled 400 MB/s/src | 512 | 281.00 | 238.63 | 75.60 | 50.31 | 0.1015 | 0.0759 | 1601.61 | 1601.66 | 1.0/1.0 | 337/288 | 30.29 | 0 |
| 10 | compact | controlled 400 MB/s/src | 128 | 140.09 | 104.72 | 55.18 | 23.82 | 0.1630 | 0.0862 | 1601.82 | 1601.91 | 1.0/1.0 | 194/164 | 9.65 | 0 |
| 11 | compact | controlled 400 MB/s/src | 256 | 140.07 | 106.77 | 53.85 | 24.13 | 0.1596 | 0.0847 | 1601.81 | 1601.88 | 1.0/1.0 | 194/192 | 9.58 | 0 |
| 12 | compact | controlled 400 MB/s/src | 512 | 140.39 | 108.86 | 55.15 | 24.71 | 0.1563 | 0.0864 | 1601.83 | 1601.90 | 1.0/1.0 | 193/172 | 9.61 | 0 |

## Per-Source Metrics

Latencies are cycles and bandwidths are MB/s.

### Row 1: `spread_unlimited_width128`

| src | avg W | P95 W | P99 W | max W | avg R | P95 R | P99 R | max R | W BW | R BW |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 244.83 | 265 | 281 | 319 | 240.87 | 266 | 275 | 296 | 2032.96 | 2033.77 |
| 1 | 239.03 | 276 | 286 | 304 | 228.80 | 259 | 265 | 301 | 2079.23 | 2079.69 |
| 2 | 244.56 | 264 | 275 | 306 | 243.77 | 274 | 290 | 304 | 2034.55 | 2034.79 |
| 3 | 256.67 | 291 | 310 | 332 | 246.01 | 281 | 294 | 361 | 1942.34 | 1942.87 |

### Row 2: `spread_unlimited_width256`

| src | avg W | P95 W | P99 W | max W | avg R | P95 R | P99 R | max R | W BW | R BW |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 244.06 | 264 | 280 | 319 | 244.66 | 275 | 290 | 312 | 2039.56 | 2040.36 |
| 1 | 238.03 | 274 | 287 | 304 | 228.96 | 260 | 267 | 299 | 2089.63 | 2089.64 |
| 2 | 244.31 | 267 | 285 | 309 | 239.58 | 264 | 275 | 304 | 2038.81 | 2039.52 |
| 3 | 257.90 | 294 | 311 | 339 | 248.54 | 282 | 299 | 358 | 1933.28 | 1933.70 |

### Row 3: `spread_unlimited_width512`

| src | avg W | P95 W | P99 W | max W | avg R | P95 R | P99 R | max R | W BW | R BW |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 245.67 | 265 | 285 | 308 | 248.50 | 279 | 292 | 299 | 2025.57 | 2025.89 |
| 1 | 240.84 | 275 | 288 | 297 | 233.27 | 264 | 275 | 302 | 2066.49 | 2066.72 |
| 2 | 246.02 | 268 | 281 | 319 | 247.33 | 274 | 286 | 310 | 2022.40 | 2023.16 |
| 3 | 256.00 | 290 | 312 | 327 | 249.03 | 283 | 296 | 302 | 1946.12 | 1946.75 |

### Row 4: `compact_unlimited_width128`

| src | avg W | P95 W | P99 W | max W | avg R | P95 R | P99 R | max R | W BW | R BW |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 131.20 | 166 | 176 | 192 | 7721.10 | 10241 | 10241 | 10241 | 3704.75 | 3208.16 |
| 1 | 137.89 | 180 | 206 | 223 | 6029.96 | 10240 | 10240 | 10241 | 3535.86 | 3199.82 |
| 2 | 131.32 | 169 | 189 | 246 | 7754.53 | 10241 | 10280 | 10281 | 3700.33 | 3207.32 |
| 3 | 137.94 | 181 | 189 | 234 | 6004.44 | 10240 | 10240 | 10241 | 3531.91 | 3200.60 |

### Row 5: `compact_unlimited_width256`

| src | avg W | P95 W | P99 W | max W | avg R | P95 R | P99 R | max R | W BW | R BW |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 130.65 | 165 | 174 | 188 | 7877.34 | 10240 | 10241 | 10241 | 3719.42 | 3208.16 |
| 1 | 137.86 | 181 | 196 | 222 | 5722.06 | 10240 | 10240 | 10241 | 3536.25 | 3199.80 |
| 2 | 130.80 | 171 | 192 | 204 | 7901.91 | 10241 | 10280 | 10281 | 3717.58 | 3204.11 |
| 3 | 138.31 | 180 | 191 | 254 | 5491.08 | 10240 | 10240 | 10240 | 3523.07 | 3200.58 |

### Row 6: `compact_unlimited_width512`

| src | avg W | P95 W | P99 W | max W | avg R | P95 R | P99 R | max R | W BW | R BW |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 130.72 | 165 | 173 | 218 | 7861.48 | 10241 | 10241 | 10241 | 3715.29 | 3208.10 |
| 1 | 137.78 | 184 | 214 | 223 | 5758.93 | 10240 | 10240 | 10241 | 3537.84 | 3199.74 |
| 2 | 130.94 | 171 | 188 | 237 | 7892.51 | 10241 | 10280 | 10281 | 3713.24 | 3203.24 |
| 3 | 138.24 | 182 | 192 | 265 | 5406.65 | 10240 | 10240 | 10240 | 3522.48 | 3200.52 |

### Row 7: `spread_controlled400_width128`

| src | avg W | P95 W | P99 W | max W | avg R | P95 R | P99 R | max R | W BW | R BW |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 290.91 | 323 | 326 | 327 | 238.77 | 267 | 275 | 279 | 400.39 | 400.42 |
| 1 | 232.61 | 256 | 260 | 261 | 210.10 | 243 | 243 | 243 | 400.41 | 400.44 |
| 2 | 291.50 | 323 | 326 | 328 | 229.92 | 263 | 275 | 293 | 400.42 | 400.40 |
| 3 | 308.33 | 329 | 335 | 338 | 260.03 | 280 | 283 | 285 | 400.39 | 400.42 |

### Row 8: `spread_controlled400_width256`

| src | avg W | P95 W | P99 W | max W | avg R | P95 R | P99 R | max R | W BW | R BW |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 288.60 | 324 | 327 | 329 | 239.18 | 267 | 276 | 280 | 400.41 | 400.38 |
| 1 | 232.84 | 256 | 260 | 261 | 211.08 | 244 | 244 | 244 | 400.43 | 400.41 |
| 2 | 292.90 | 323 | 326 | 328 | 231.51 | 267 | 283 | 283 | 400.39 | 400.45 |
| 3 | 308.83 | 329 | 334 | 336 | 261.37 | 281 | 283 | 285 | 400.39 | 400.42 |

### Row 9: `spread_controlled400_width512`

| src | avg W | P95 W | P99 W | max W | avg R | P95 R | P99 R | max R | W BW | R BW |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 292.32 | 324 | 326 | 327 | 242.22 | 270 | 279 | 283 | 400.41 | 400.38 |
| 1 | 233.27 | 256 | 260 | 261 | 214.48 | 247 | 247 | 247 | 400.41 | 400.43 |
| 2 | 289.52 | 324 | 326 | 328 | 233.03 | 267 | 286 | 286 | 400.40 | 400.43 |
| 3 | 308.87 | 330 | 334 | 337 | 264.79 | 284 | 284 | 288 | 400.40 | 400.42 |

### Row 10: `compact_controlled400_width128`

| src | avg W | P95 W | P99 W | max W | avg R | P95 R | P99 R | max R | W BW | R BW |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 119.54 | 177 | 181 | 184 | 99.49 | 164 | 164 | 164 | 400.47 | 400.49 |
| 1 | 119.02 | 181 | 185 | 187 | 95.56 | 130 | 144 | 144 | 400.46 | 400.47 |
| 2 | 147.60 | 181 | 186 | 186 | 104.46 | 132 | 156 | 156 | 400.44 | 400.48 |
| 3 | 174.20 | 191 | 193 | 194 | 119.38 | 151 | 153 | 153 | 400.44 | 400.47 |

### Row 11: `compact_controlled400_width256`

| src | avg W | P95 W | P99 W | max W | avg R | P95 R | P99 R | max R | W BW | R BW |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 119.74 | 177 | 181 | 182 | 102.01 | 165 | 165 | 165 | 400.44 | 400.44 |
| 1 | 119.79 | 180 | 185 | 186 | 97.26 | 136 | 145 | 149 | 400.47 | 400.48 |
| 2 | 147.15 | 181 | 185 | 187 | 106.42 | 133 | 144 | 157 | 400.47 | 400.49 |
| 3 | 173.59 | 191 | 193 | 194 | 121.39 | 152 | 154 | 192 | 400.43 | 400.46 |

### Row 12: `compact_controlled400_width512`

| src | avg W | P95 W | P99 W | max W | avg R | P95 R | P99 R | max R | W BW | R BW |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 122.99 | 177 | 181 | 184 | 103.12 | 148 | 168 | 168 | 400.47 | 400.47 |
| 1 | 119.05 | 181 | 184 | 186 | 99.31 | 140 | 148 | 155 | 400.47 | 400.49 |
| 2 | 145.33 | 180 | 185 | 186 | 108.98 | 136 | 160 | 160 | 400.45 | 400.48 |
| 3 | 174.20 | 191 | 193 | 193 | 124.02 | 155 | 157 | 172 | 400.44 | 400.46 |

## Interpretation

- The previous 128-bit compact unlimited failure is gone after forcing 512-byte address increments. This confirms that the prior failure was an address stepping/NPP split artifact, not a fundamental 128-bit endpoint-width failure.
- Spread placement remains stable across widths. Unlimited aggregate bandwidth stays around 8.06-8.10 GB/s and latency changes only slightly, so endpoint width is not the dominant limit in the spread case.
- Compact placement under unlimited injection reaches higher write bandwidth, about 14.47-14.50 GB/s aggregate, but read latency is still pathological. Mean read latency is around 6.7K-6.9K cycles with max read latency around 10.28K cycles for all widths.
- Controlled 400 MB/s/source rows behave as expected: aggregate read/write bandwidth is about 1.60 GB/s for every width. Compact placement has much lower controlled-load latency than spread placement because the paths are shorter/local, and the read pathology does not appear under this load cap.
- Width has weak impact compared with placement and offered load. Increasing endpoint width does not materially improve spread bandwidth, does not remove compact read-response congestion under unlimited load, and has only small latency effects under controlled load.

## Takeaway

Experiment 5 now cleanly separates endpoint-width effects from the address-increment artifact. The main behavioral result is that offered load and placement dominate this incast workload: compact placement is excellent for writes but still creates a severe read-response tail at unlimited injection, while controlled injection keeps all widths stable near the configured aggregate bandwidth.
