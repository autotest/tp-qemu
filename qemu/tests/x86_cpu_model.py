import logging
import re

from avocado.utils import cpu
from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    Qemu reboot test:
    1) Start qemu to get cpu model supported by host
    3) Boot guest with the cpu model
    4) Check cpu model name in guest
    5) Check cpu flags in guest(only for linux guest)
    6) Reboot guest

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    error_context.context("Start qemu to get support cpu model", logging.info)
    vm = env.get_vm(params["main_vm"])
    out = vm.monitor.info("cpu-definitions")
    vm.destroy()
    model = params["model"]
    model_pattern = params["model_pattern"]
    flags = params["flags"]
    if cpu.get_cpu_vendor_name() == 'intel':
        model_ib = "%s-IBRS" % model
        flag_ib = " ibpb ibrs"
        name_ib = ", IBRS( update)?"
    else:
        model_ib = "%s-IBPB" % model
        flag_ib = " ibpb"
        name_ib = " \\(with IBPB\\)"

    models = [x["name"] for x in out if not x["unavailable-features"]]
    if model_ib in models:
        cpu_model = model_ib
        guest_model = model_pattern % name_ib
        flags += flag_ib
    elif model in models:
        cpu_model = model
        guest_model = model_pattern % ""
    else:
        test.cancel("This host doesn't support cpu model %s" % model)

    params["paused_after_start_vm"] = "no"
    params["cpu_model"] = cpu_model

    vm.create(params=params)
    vm.verify_alive()
    error_context.context("Try to log into guest", logging.info)
    session = vm.wait_for_login()

    error_context.context("Check cpu model inside guest", logging.info)
    cmd = params["get_model_cmd"]
    out = session.cmd_output(cmd)
    if not re.search(guest_model, out):
        test.fail("Guest cpu model is not right")

    if params["os_type"] == "linux":
        error_context.context("Check cpu flags inside guest", logging.info)
        cmd = params["check_flag_cmd"]
        out = session.cmd_output(cmd).split()
        missing = [f for f in flags.split() if f not in out]
        if missing:
            test.fail("Flag %s not in guest" % missing)

    if params.get("reboot_method"):
        error_context.context("Reboot guest '%s'." % vm.name, logging.info)
        vm.reboot(session=session)

    vm.verify_kernel_crash()
    session.close()
