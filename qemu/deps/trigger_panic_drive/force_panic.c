/*
 * This driver will force a kernel panic to test whether
 * the Dump device can work normally.
 * This driver needs kernel-devel related RPM to compile.
 * Then run "make" and "insmod ./force_panic.ko" to load.
 */

#ifdef __KERNEL__
#include <linux/module.h>
#include <linux/kernel.h>
static int __init panic_init(void)
{
panic("force-panic");
return 0;
}

static void __exit panic_exit(void)
{
}
module_init(panic_init);
module_exit(panic_exit);
#endif
MODULE_LICENSE("gpl");
