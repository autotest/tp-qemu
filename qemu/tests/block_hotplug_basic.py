import logging

from virttest import error_context
from virttest import utils_misc
from virttest import utils_test
from virttest.qemu_devices import qdevices

from qemu.lib.block import block_hotplug


@error_context.context_aware
def run(test, params, env):
    """
    Test hotplug of block devices.

    1) Boot up guest with/without block device(s).
    2) Hoplug block device and verify
    3) Do read/write data on hotplug block.
    4) Unplug block device and verify

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """
    def run_sub_test(test, params, env, plug_op):
        """
        Run sub test before/after hotplug/unplug device
        """
        sub_type = params.get("sub_type_%s" % plug_op)
        if sub_type:
            error_context.context("Running sub test '%s' %s" % (sub_type, plug_op),
                                  logging.info)
            utils_test.run_virt_sub_test(test, params, env, sub_type)
            if sub_type != "shutdown":
                vm = env.get_vm(params["main_vm"])
                if vm.is_dead():
                    test.fail("VM dead after sub test %s %s" % (sub_type, plug_op))
            else:
                env["test_cont"] = "no"

    blk_num = int(params.get("blk_num", 1))
    repeat_times = int(params.get("repeat_times", 3))
    iozone_test_cmd = params.get("iozone_test_cmd")

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()

    for iteration in xrange(repeat_times):
        dev_contr_dict = {"devs": [], "contrs": [], "contr_dev_map": {}}
        if params.get("need_plug") == "yes":
            error_context.context("Run block hotplug/unplug for iteration: %d" % iteration, logging.info)

        for num in xrange(blk_num):
            if params.get("need_plug") == "yes":

                plug_op = "before_plug"
                run_sub_test(test, params, env, plug_op)

                disks_before_hotplug = block_hotplug.find_disk(vm, params)
                err, dev_contr_dict = block_hotplug.hotplug_device(vm, params, dev_contr_dict, num)
                plug_unplug = "plug"
                error_context.context("Check devices in guest after plug", logging.info)
                status = block_hotplug.check_device_in_guest(vm, params, plug_unplug, disks_before_hotplug)
                if not status:
                    test.fail("Failed to plug device in guest")
                if iozone_test_cmd:
                    new_disks = block_hotplug.get_new_disks_in_guest(vm, params, disks_before_hotplug)
                    iozone_test = utils_misc.IozoneTest(session, params)
                    for disk in new_disks:
                        if params.get("os_type") == "linux":
                            mountpoint = disk
                        elif params.get("os_type") == "windows":
                            mountpoint = chr(ord("H") + int(disk))
                        else:
                            test.cancel("Unsupported OS type '%s'" % params.get("os_type"))
                        error_context.context("Run iozone test here")
                        status, output = iozone_test.run_iozone_in_guest(disk, mountpoint)
                        if status:
                            test.fail("Failed to do IO test after hotplug,"
                                      "Output: %r" % output)
                    iozone_test.iozone_clean()

                plug_op = "after_plug"
                run_sub_test(test, params, env, plug_op)

            else:
                pci_type = params.get("pci_type", "virtio_blk_pci")
                img_list = params.get("images").split()
                device = qdevices.QDevice(pci_type)
                device.set_param("id", img_list[num + 1])
                dev_contr_dict["devs"].append(device)

        plug_op = "before_unplug"
        run_sub_test(test, params, env, plug_op)

        if env.get("test_cont", "yes") == "yes":
            if params.get("need_plug") == "no":
                error_context.context("Run block unplug for iteration: %d" % iteration, logging.info)

            error_context.context("Unplug device", logging.info)
            plug_unplug = "unplug"
            disks_before_unplug = block_hotplug.find_disk(vm, params)
            block_hotplug.unplug_device(vm, dev_contr_dict)

            error_context.context("Check devices in guest after unplug", logging.info)
            status = block_hotplug.check_device_in_guest(vm, params, plug_unplug, disks_before_unplug, blk_num)
            if not status:
                test.fail("Failed to unplug device in guest")
            dev_contr_dict["contr_dev_map"].clear()
            del dev_contr_dict["devs"][:], dev_contr_dict["contrs"][:]

            plug_op = "after_unplug"
            run_sub_test(test, params, env, plug_op)
