from avocado.utils import process
from virttest import error_context, utils_misc, utils_net


@error_context.context_aware
def run(test, params, env):
    """
    KVM sr-iov hotplug negatvie test:
    1) Boot up VM.
    2) Try to remove sr-iov device driver module (optional)
    3) Hotplug sr-iov device to VM with negative parameters
    4) Verify that qemu could handle the negative parameters
       check hotplug error message (optional)

    :param test: qemu test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def make_pci_add_cmd(pa_pci_id, pci_addr="auto"):
        pci_add_cmd = "pci_add pci_addr=%s host host=%s,if=%s" % (
            pci_addr,
            pa_pci_id,
            pci_model,
        )
        if params.get("hotplug_params"):
            assign_param = params.get("hotplug_params").split()
            for param in assign_param:
                value = params.get(param)
                if value:
                    pci_add_cmd += ",%s=%s" % (param, value)
        return pci_add_cmd

    def make_device_add_cmd(pa_pci_id, pci_addr=None):
        device_id = "%s" % pci_model + "-" + utils_misc.generate_random_id()
        pci_add_cmd = "device_add id=%s,driver=pci-assign,host=%s" % (
            device_id,
            pa_pci_id,
        )
        if pci_addr is not None:
            pci_add_cmd += ",addr=%s" % pci_addr
        if params.get("hotplug_params"):
            assign_param = params.get("hotplug_params").split()
            for param in assign_param:
                value = params.get(param)
                if value:
                    pci_add_cmd += ",%s=%s" % (param, value)
        return pci_add_cmd

    neg_msg = params.get("negative_msg")
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    rp_times = int(params.get("repeat_times", 1))
    pci_model = params.get("pci_model", "pci-assign")
    pci_invaild_addr = params.get("pci_invaild_addr")
    modprobe_cmd = params.get("modprobe_cmd")

    device = {}
    device["type"] = params.get("hotplug_device_type", "vf")
    device["mac"] = utils_net.generate_mac_address_simple()
    if params.get("device_name"):
        device["name"] = params.get("device_name")

    if vm.pci_assignable is not None:
        pa_pci_ids = vm.pci_assignable.request_devs(device)
    # Probe qemu to verify what is the supported syntax for PCI hotplug
    if vm.monitor.protocol == "qmp":
        cmd_output = vm.monitor.info("commands")
    else:
        cmd_output = vm.monitor.send_args_cmd("help")

    if not cmd_output:
        test.error("Unknown version of qemu")

    cmd_type = utils_misc.find_substring(str(cmd_output), "pci_add", "device_add")
    for j in range(rp_times):
        if cmd_type == "pci_add":
            pci_add_cmd = make_pci_add_cmd(pa_pci_ids[0], pci_invaild_addr)  # pylint: disable=E0606
        elif cmd_type == "device_add":
            pci_add_cmd = make_device_add_cmd(pa_pci_ids[0], pci_invaild_addr)
        try:
            msg = "Adding pci device with command '%s'" % pci_add_cmd  # pylint: disable=E0606
            error_context.context(msg, test.log.info)
            case_fail = False
            add_output = vm.monitor.send_args_cmd(pci_add_cmd, convert=False)
            case_fail = True
        except Exception as err:
            if neg_msg:
                msg = "Check negative hotplug error message"
                error_context.context(msg, test.log.info)
                if neg_msg not in str(err):
                    msg = "Could not find '%s' in" % neg_msg
                    msg += " command output '%s'" % add_output
                    test.fail(msg)
            test.log.debug("Could not boot up vm, %s", err)
        if case_fail:
            if neg_msg:
                msg = "Check negative hotplug error message"
                error_context.context(msg, test.log.info)
                if neg_msg not in str(add_output):
                    msg = "Could not find '%s' in" % neg_msg
                    msg += " command output '%s'" % add_output
                    test.fail(msg)
            test.log.debug("Could not boot up vm, %s", add_output)

    if modprobe_cmd:
        # negative test, both guest and host should still work well.
        msg = "Negative test:Try to remove sr-iov module in host."
        error_context.context(msg, test.log.info)
        driver = params.get("driver", "igb")
        modprobe_cmd = modprobe_cmd % driver
        try:
            process.system(modprobe_cmd, timeout=120, ignore_status=True, shell=True)
        except process.CmdError as err:
            test.log.error(err)
