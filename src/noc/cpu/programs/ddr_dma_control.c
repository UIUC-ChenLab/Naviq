#include <stdint.h>

#ifndef DESC_BASE
#define DESC_BASE 0x10000000ULL
#endif
#ifndef PACKET_BASE
#define PACKET_BASE 0x11000000ULL
#endif
#ifndef SCRATCH_BASE
#define SCRATCH_BASE 0x12000000ULL
#endif
#ifndef DESC_PTR_BASE
#define DESC_PTR_BASE DESC_BASE
#endif
#ifndef SCRATCH_PTR_BASE
#define SCRATCH_PTR_BASE SCRATCH_BASE
#endif
#ifndef DMA_CTRL_BASE
#define DMA_CTRL_BASE 0x40000000ULL
#endif
#ifndef PACKET_STRIDE
#define PACKET_STRIDE 2048U
#endif
#ifndef PACKETS
#define PACKETS 4U
#endif
#define DESC_STRIDE 64U

#define CONTROL_MODE_LEGACY_POLL 0U
#define CONTROL_MODE_DATA_ONLY 1U
#define CONTROL_MODE_HEAVY_POLL 2U
#define CONTROL_MODE_DDR_HEAVY 3U

#ifndef CONTROL_MODE_DEFAULT
#define CONTROL_MODE_DEFAULT CONTROL_MODE_LEGACY_POLL
#endif

#ifndef DATA_ONLY_WAIT_ITERS
#define DATA_ONLY_WAIT_ITERS 64U
#endif

#ifndef DATA_ONLY_WAIT_ATTEMPTS
#define DATA_ONLY_WAIT_ATTEMPTS 8U
#endif

#ifndef DATA_ONLY_POST_DONE_WAIT_ITERS
#define DATA_ONLY_POST_DONE_WAIT_ITERS 0U
#endif

#ifndef MAX_POLL_ITERS
#define MAX_POLL_ITERS 10000000U
#endif

#ifndef DDR_HEAVY_READ_ITERS
#define DDR_HEAVY_READ_ITERS 1024U
#endif

#ifndef DDR_HEAVY_PREFETCH_LINES
#define DDR_HEAVY_PREFETCH_LINES 1024U
#endif
#ifndef CPU_WRITES_DESCRIPTORS
#define CPU_WRITES_DESCRIPTORS 1U
#endif
#ifndef CPU_INIT_SCRATCH
#define CPU_INIT_SCRATCH 1U
#endif

#define SCRATCH_REGION_BYTES (1U << 16)
#define SCRATCH_LINE_STRIDE_WORDS 16U
#define SCRATCH_LINE_COUNT (SCRATCH_REGION_BYTES / (SCRATCH_LINE_STRIDE_WORDS * sizeof(uint32_t)))

#define DESC_FLAG_VALID 0x0001U
#define DESC_FLAG_EOC 0x0004U

#define DMA_CONTROL 0x00U
#define DMA_STATUS 0x04U
#define DMA_DESC_BASE_LO 0x08U
#define DMA_DESC_BASE_HI 0x0cU
#define DMA_PACKET_COUNT 0x10U
#define DMA_MAX_READ_BURST_BEATS 0x14U
#define DMA_COMPLETED_PACKETS 0x18U
#define DMA_ERROR_CODE 0x1cU

#define CONTROL_START 0x1U
#define CONTROL_CLEAR_STATUS 0x2U

#define STATUS_BUSY 0x1U
#define STATUS_DONE 0x2U
#define STATUS_ERROR 0x4U
#define STATUS_EOC_SEEN 0x8U

static volatile uint32_t *const dma =
    (volatile uint32_t *)(uintptr_t)DMA_CTRL_BASE;
static volatile uint32_t *const scratch =
    (volatile uint32_t *)(uintptr_t)SCRATCH_PTR_BASE;

static inline uint32_t __attribute__((always_inline))
payload_size_for_index(uint32_t index)
{
#ifdef FIXED_PAYLOAD_BYTES
    (void)index;
    return FIXED_PAYLOAD_BYTES;
#else
    const uint32_t rem = index & 3U;
    uint32_t base = 16U;
    base += 84U * (uint32_t)(rem == 1U);
    base += 144U * (uint32_t)(rem == 2U);
    base += 212U * (uint32_t)(rem == 3U);
    const uint32_t group = index / 4U;
    return base + 4U * group;
#endif
}

static void
write_desc(uint32_t index)
{
    volatile uint8_t *desc =
        (volatile uint8_t *)(uintptr_t)(DESC_PTR_BASE + index * DESC_STRIDE);
    volatile uint64_t *desc64 = (volatile uint64_t *)desc;
    volatile uint32_t *desc32 = (volatile uint32_t *)desc;
    const uint32_t packet_len = payload_size_for_index(index) + 28U;
    const uint16_t flags =
        DESC_FLAG_VALID | ((index == (PACKETS - 1U)) ? DESC_FLAG_EOC : 0U);

    desc64[0] = PACKET_BASE + (uint64_t)index * PACKET_STRIDE;
    desc32[2] = packet_len;
    desc32[3] = (3U << 16);                    /* tid:tdest */
    desc32[4] = ((uint32_t)flags << 16) | 0x55U; /* flags:tuser */
}

static void
local_wait(uint32_t iters)
{
    for (uint32_t i = 0; i < iters; ++i) {
        __asm__ volatile("" ::: "memory");
    }
}

static void
init_scratch_region(void)
{
    for (uint32_t line = 0; line < SCRATCH_LINE_COUNT; ++line) {
        scratch[line * SCRATCH_LINE_STRIDE_WORDS] = line ^ 0x5a5a1234U;
    }
}

static uint32_t
read_scratch_line(uint32_t line)
{
    volatile uint64_t *scratch64 = (volatile uint64_t *)scratch;
    const uint32_t base = line * 8U;
    uint64_t acc = 0;
    for (uint32_t word = 0; word < 8U; ++word) {
        acc ^= scratch64[base + word];
    }
    return (uint32_t)(acc ^ (acc >> 32));
}

static uint64_t
read_scratch_stream(uint32_t qwords)
{
#if defined(__x86_64__)
    const uint32_t max_qwords = SCRATCH_REGION_BYTES / sizeof(uint64_t);
    if (qwords > max_qwords) {
        qwords = max_qwords;
    }
    const uint64_t *src = (const uint64_t *)(uintptr_t)SCRATCH_PTR_BASE;
    uint64_t last = 0;
    __asm__ volatile(
        "rep lodsq"
        : "+S"(src), "+c"(qwords), "=a"(last)
        :
        : "memory");
    return last;
#else
    volatile uint64_t *scratch64 = (volatile uint64_t *)scratch;
    const uint32_t max_qwords = SCRATCH_REGION_BYTES / sizeof(uint64_t);
    uint64_t acc = 0;
    if (qwords > max_qwords) {
        qwords = max_qwords;
    }
    for (uint32_t i = 0; i < qwords; ++i) {
        acc ^= scratch64[i];
    }
    return acc;
#endif
}

static void
prefetch_scratch_stream(uint32_t lines)
{
#if defined(__x86_64__)
    if (lines > SCRATCH_LINE_COUNT) {
        lines = SCRATCH_LINE_COUNT;
    }
    for (uint32_t i = 0; i < lines; ++i) {
        const void *addr = (const void *)(uintptr_t)(
            SCRATCH_PTR_BASE + (uint64_t)i * SCRATCH_LINE_STRIDE_WORDS * sizeof(uint32_t));
        __asm__ volatile("prefetcht0 (%0)" :: "r"(addr) : "memory");
    }
#else
    (void)lines;
#endif
}

static int
run(void)
{
#if CPU_WRITES_DESCRIPTORS
    for (uint32_t i = 0; i < PACKETS; ++i) {
        write_desc(i);
    }
#endif
#if CPU_INIT_SCRATCH
    init_scratch_region();
#endif

    dma[DMA_CONTROL / 4U] = CONTROL_CLEAR_STATUS;
    dma[DMA_DESC_BASE_LO / 4U] = (uint32_t)(DESC_BASE & 0xffffffffULL);
    dma[DMA_DESC_BASE_HI / 4U] = (uint32_t)(DESC_BASE >> 32);
    dma[DMA_PACKET_COUNT / 4U] = PACKETS;
    dma[DMA_MAX_READ_BURST_BEATS / 4U] = 16U;
    dma[DMA_CONTROL / 4U] = CONTROL_START;

    uint32_t status = 0;
    if (CONTROL_MODE_DEFAULT == CONTROL_MODE_DATA_ONLY) {
        for (uint32_t attempt = 0; attempt < DATA_ONLY_WAIT_ATTEMPTS; ++attempt) {
            local_wait(DATA_ONLY_WAIT_ITERS);
            status = dma[DMA_STATUS / 4U];
            if ((status & STATUS_ERROR) != 0U) {
                return 10 + (int)dma[DMA_ERROR_CODE / 4U];
            }
            if ((status & STATUS_DONE) != 0U) {
                local_wait(DATA_ONLY_POST_DONE_WAIT_ITERS);
                break;
            }
        }
    } else if (CONTROL_MODE_DEFAULT == CONTROL_MODE_DDR_HEAVY) {
        prefetch_scratch_stream(DDR_HEAVY_PREFETCH_LINES);
        volatile uint64_t sink = read_scratch_stream(DDR_HEAVY_READ_ITERS);
        sink ^= read_scratch_line((uint32_t)sink % SCRATCH_LINE_COUNT);
        __asm__ volatile("" :: "r"(sink) : "memory");
        for (uint32_t i = 0; i < MAX_POLL_ITERS; ++i) {
            status = dma[DMA_STATUS / 4U];
            if ((status & STATUS_ERROR) != 0U) {
                return 10 + (int)dma[DMA_ERROR_CODE / 4U];
            }
            if ((status & STATUS_DONE) != 0U) {
                break;
            }
        }
    } else if (CONTROL_MODE_DEFAULT == CONTROL_MODE_HEAVY_POLL) {
        for (uint32_t i = 0; i < MAX_POLL_ITERS; ++i) {
            status = dma[DMA_STATUS / 4U];
            (void)dma[DMA_COMPLETED_PACKETS / 4U];
            if ((status & STATUS_ERROR) != 0U) {
                return 10 + (int)dma[DMA_ERROR_CODE / 4U];
            }
            if ((status & STATUS_DONE) != 0U) {
                break;
            }
        }
    } else {
        for (uint32_t i = 0; i < MAX_POLL_ITERS; ++i) {
            status = dma[DMA_STATUS / 4U];
            if ((status & STATUS_ERROR) != 0U) {
                return 10 + (int)dma[DMA_ERROR_CODE / 4U];
            }
            if ((status & STATUS_DONE) != 0U) {
                break;
            }
        }
    }

    if ((status & STATUS_DONE) == 0U) {
        return 1;
    }
    if ((status & STATUS_EOC_SEEN) == 0U) {
        return 2;
    }
    if ((status & STATUS_BUSY) != 0U) {
        return 3;
    }
    if (dma[DMA_COMPLETED_PACKETS / 4U] != PACKETS) {
        return 4;
    }

    return 0;
}

static void
sys_exit(int code)
{
    __asm__ volatile(
        "syscall"
        :
        : "a"(60), "D"(code)
        : "rcx", "r11", "memory");
    __builtin_unreachable();
}

void
_start(void)
{
    sys_exit(run());
}
