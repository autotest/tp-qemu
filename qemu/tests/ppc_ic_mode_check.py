import re

from virttest import error_context
from virttest.virt_vm import VMCreateError


@error_context.context_aware
def run(test, params, env):
    """
    Check the interrupt controller mode.

    1) Launch a guest with kernel-irqchip=on/off and ic-mode=xics/xive.
    2) Get pic info from human monitor and get interrupts info inside guest.
    3) Check whether irqchip and ic-mode match what we set.

    :param test: the test object.
    :param params: the test params.
    :param env: test environment.
    """
    ic_mode = params["ic_mode"]
    kernel_irqchip = params["kernel_irqchip"]
    params["start_vm"] = "yes"
    vm = env.get_vm(params["main_vm"])

    error_context.base_context("Try to create a qemu instance...", test.log.info)
    try:
        vm.create(params=params)
    except VMCreateError as e:
        if re.search(
            r"kernel_irqchip requested but unavailable|" r"XIVE-only machines", e.output
        ):
            test.cancel(e.output)
        raise
    else:
        vm.verify_alive()
        session = vm.wait_for_login()

    error_context.context("Get irqchip and ic-mode information.", test.log.info)
    pic_o = vm.monitor.info("pic")
    irqchip_match = re.search(r"^irqchip: %s" % kernel_irqchip, pic_o, re.M)
    ic_mode_match = (
        session.cmd_status("grep %s /proc/interrupts" % ic_mode.upper()) == 0
    )

    error_context.context("Check wherever irqchip/ic-mode match.", test.log.info)
    if not irqchip_match:
        test.fail("irqchip does not match to '%s'." % kernel_irqchip)
    elif not ic_mode_match:
        test.fail("ic-mode does not match to '%s'." % ic_mode)
