#include <stdint.h>

#define PPE_CTRL_BASE 0xFFFC0000ULL
#define FLOW_ID 0x35U
#define FLOW_TDEST 7U
#define STEERING_ENTRY_STRIDE 4U

static volatile uint32_t *const ppe_ctrl =
    (volatile uint32_t *)(uintptr_t)PPE_CTRL_BASE;

static int
run(void)
{
    volatile uint32_t *entry =
        ppe_ctrl + ((FLOW_ID * STEERING_ENTRY_STRIDE) / 4U);

    *entry = FLOW_TDEST;
    if (*entry != FLOW_TDEST) {
        return 1;
    }

    *entry = FLOW_TDEST + 1U;
    if (*entry != FLOW_TDEST + 1U) {
        return 2;
    }

    *entry = FLOW_TDEST;
    if (*entry != FLOW_TDEST) {
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
