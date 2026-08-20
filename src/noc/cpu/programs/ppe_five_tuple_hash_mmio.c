#include <stdint.h>

#define PPE_CTRL_BASE 0xFFFC0000ULL
#define ENTRY_STRIDE 4U
#define ENTRY0 0x12U
#define ENTRY1 0xA7U
#define TDEST0 7U
#define TDEST1 8U

static volatile uint32_t *const ppe_ctrl =
    (volatile uint32_t *)(uintptr_t)PPE_CTRL_BASE;

static int
run(void)
{
    volatile uint32_t *entry0 = ppe_ctrl + ((ENTRY0 * ENTRY_STRIDE) / 4U);
    volatile uint32_t *entry1 = ppe_ctrl + ((ENTRY1 * ENTRY_STRIDE) / 4U);

    *entry0 = TDEST0;
    if (*entry0 != TDEST0) {
        return 1;
    }

    *entry1 = TDEST1;
    if (*entry1 != TDEST1) {
        return 2;
    }

    *entry0 = TDEST1;
    if (*entry0 != TDEST1) {
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
