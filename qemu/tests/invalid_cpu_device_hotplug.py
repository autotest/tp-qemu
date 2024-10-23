import json
import re

from virttest import arch, error_context, utils_misc
from virttest.qemu_monitor import QMPCmdError

from provider import cpu_utils, win_wora


@error_context.context_aware
def run(test, params, env):
    """
    Test hotplug invalid vcpu device.

    1) Boot up guest without vcpu device.
    2) Hotplug an invalid vcpu device we want
    3) Check error messages and analyze if it is correct

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    not_match_err = (
        "Hotplug %s failed but the error description does not " "match: '%s'"
    )
    expected_info = "Hotplug %s failed as expected, error description: '%s'"
    hotplug_pass_err = "Still able to hotplug %s via qmp"

    def hotplug_inuse_vcpu():
        """Hotplug 2 in use vcpu devices: main vcpu and duplicate vcpu"""
        # Main vCPU
        main_vcpu_props = {}
        for vcpu_prop in vcpu_props:
            main_vcpu_props.setdefault(vcpu_prop, "0")
        vm.params["vcpu_props_main_vcpu"] = json.dumps(main_vcpu_props)
        error_context.context(
            "Define the invalid vcpu: %s" % "main_vcpu", test.log.info
        )
        in_use_vcpu_dev = vm.devices.vcpu_device_define_by_params(
            vm.params, "main_vcpu"
        )
        try:
            error_context.context("Hotplug the main vcpu", test.log.info)
            in_use_vcpu_dev.enable(vm.monitor)
        except QMPCmdError as err:
            qmp_desc = err.data["desc"]
            if not re.match(error_desc.format("0"), qmp_desc):
                test.error(not_match_err % ("main vcpu", qmp_desc))
            test.log.info(expected_info, "main vcpu", qmp_desc)
        else:
            test.fail(hotplug_pass_err % "main vcpu")

        # New vCPU
        error_context.context("hotplug vcpu device: %s" % vcpu_device_id, test.log.info)
        vm.hotplug_vcpu_device(vcpu_device_id)
        if not utils_misc.wait_for(
            lambda: cpu_utils.check_if_vm_vcpus_match_qemu(vm), 10
        ):
            test.fail("Actual number of guest CPUs is not equal to expected")

        # Duplicate vCPU
        duplicate_vcpu_params = vm.devices.get_by_qid(vcpu_device_id)[0].params.copy()
        del duplicate_vcpu_params["id"]
        vm.params["vcpu_props_duplicate_vcpu"] = json.dumps(duplicate_vcpu_params)
        duplicate_vcpu_dev = vm.devices.vcpu_device_define_by_params(
            vm.params, "duplicate_vcpu"
        )
        try:
            error_context.context("hotplug the duplicate vcpu", test.log.info)
            duplicate_vcpu_dev.enable(vm.monitor)
        except QMPCmdError as err:
            dev_count = maxcpus
            if "ppc64" in arch_name:
                dev_count //= threads
            qmp_desc = err.data["desc"]
            if not re.match(error_desc.format(str(dev_count - 1)), qmp_desc):
                test.error(not_match_err % ("duplicate vcpu", qmp_desc))
            test.log.info(expected_info, "duplicate vcpu", qmp_desc)
        else:
            test.fail(hotplug_pass_err % "duplicate vcpu")

    def hotplug_invalid_vcpu():
        """Hotplug a vcpu device with invalid property id"""
        vcpu_device = vm.devices.get_by_qid(vcpu_device_id)[0]
        vm.devices.remove(vcpu_device)
        for invalid_id in params.objects("invalid_ids"):
            vcpu_device.set_param(params["invalid_property"], invalid_id)
            try:
                vcpu_device.enable(vm.monitor)
            except QMPCmdError as err:
                qmp_desc = err.data["desc"]
                if "ppc64" in arch_name:
                    # When the invalid_id is positive or negative, the initial
                    # letter format is different
                    qmp_desc = qmp_desc.lower()
                if error_desc.format(invalid_id) != qmp_desc:
                    test.error(not_match_err % ("invalid vcpu", qmp_desc))
                test.log.info(expected_info, "invalid vcpu", qmp_desc)
            else:
                test.fail(hotplug_pass_err % "invalid vcpu")

    def hotplug_outofrange_vcpu():
        """Hotplug a vcpu device with out of range property id"""
        vcpu_device = vm.devices.get_by_qid(vcpu_device_id)[0]
        vm.devices.remove(vcpu_device)
        outofrange_vcpu_num = max(vcpu_bus.addr_lengths)
        vcpu_device.set_param(vcpu_props[0], outofrange_vcpu_num)
        try:
            vcpu_device.enable(vm.monitor)
        except QMPCmdError as err:
            qmp_desc = err.data["desc"]
            if (
                error_desc.format(
                    outofrange_vcpu_num, vcpu_props[0], (vcpu_bus.addr_lengths[0] - 1)
                )
                != qmp_desc
            ):
                test.error(not_match_err % ("out_of_range vcpu", qmp_desc))
            test.log.info(expected_info, "out_of_range vcpu", qmp_desc)
        else:
            test.fail(hotplug_pass_err % "out_of_range vcpu")

    arch_name = params.get("vm_arch_name", arch.ARCH)
    vcpu_device_id = params["vcpu_devices"]
    error_desc = params["error_desc"]
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()

    if params.get_boolean("workaround_need"):
        win_wora.modify_driver(params, session)

    error_context.context("Check the number of guest CPUs after startup", test.log.info)
    if not cpu_utils.check_if_vm_vcpus_match_qemu(vm):
        test.error(
            "The number of guest CPUs is not equal to the qemu command "
            "line configuration"
        )

    vcpu_bus = vm.devices.get_buses({"aobject": "vcpu"})[0]
    vcpu_props = vcpu_bus.addr_items
    maxcpus = vm.cpuinfo.maxcpus
    threads = vm.cpuinfo.threads

    invalid_hotplug_tests = {
        "in_use_vcpu": hotplug_inuse_vcpu,
        "invalid_vcpu": hotplug_invalid_vcpu,
        "out_of_range_vcpu": hotplug_outofrange_vcpu,
    }
    invalid_hotplug_tests[params["execute_test"]]()
    session.close()
