#include <stdint.h>

#define PPE_CTRL_BASE 0xFFFC0000ULL
#define ENTRY_STRIDE 4U
#define TABLE_ENTRIES 256U
#define FLOW_TDEST 7U

static volatile uint32_t *const ppe_ctrl =
    (volatile uint32_t *)(uintptr_t)PPE_CTRL_BASE;

static int
run(void)
{
    for (uint32_t i = 0; i < TABLE_ENTRIES; ++i) {
        volatile uint32_t *entry = ppe_ctrl + ((i * ENTRY_STRIDE) / 4U);
        *entry = FLOW_TDEST;
    }

    if (ppe_ctrl[0] != FLOW_TDEST) {
        return 1;
    }
    if (ppe_ctrl[(0x55U * ENTRY_STRIDE) / 4U] != FLOW_TDEST) {
        return 2;
    }
    if (ppe_ctrl[((TABLE_ENTRIES - 1U) * ENTRY_STRIDE) / 4U] != FLOW_TDEST) {
        return 3;
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
