import re

import aexpect
from virttest import (
    arch,
    data_dir,
    error_context,
    qemu_monitor,
    storage,
    utils_misc,
    utils_test,
)


@error_context.context_aware
def run(test, params, env):
    """
    Test hotplug of PCI devices.

    (Elements between [] are configurable test parameters)
    1) PCI add one/multi device (NIC / block) with(or without) repeat
    2) Compare output of monitor command 'info pci'.
    3) Compare output of guest command [reference_cmd].
    4) Verify whether pci_model is shown in [pci_find_cmd].
    5) Check whether the newly added PCI device works fine.
    6) PCI delete the device, verify whether could remove the PCI device.
    7) reboot VM after guest wakeup form S3/S4 status (Optional Step).

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """

    # Select an image file
    def find_image(pci_num):
        image_params = params.object_params("%s" % img_list[pci_num + 1])
        o = storage.get_image_filename(image_params, data_dir.get_data_dir())
        return o

    def pci_add_nic(pci_num):
        pci_add_cmd = "pci_add pci_addr=auto nic model=%s" % pci_model
        return pci_add(pci_add_cmd)

    def pci_add_block(pci_num):
        image_filename = find_image(pci_num)
        pci_add_cmd = "pci_add pci_addr=auto storage file=%s,if=%s" % (
            image_filename,
            pci_model,
        )
        return pci_add(pci_add_cmd)

    def pci_add(pci_add_cmd):
        error_context.context("Adding pci device with command 'pci_add'", test.log.info)
        add_output = vm.monitor.send_args_cmd(pci_add_cmd, convert=False)
        pci_info.append(["", "", add_output, pci_model])

        if "OK domain" not in add_output:
            test.fail(
                "Add PCI device failed. "
                "Monitor command is: %s, Output: %r" % (pci_add_cmd, add_output)
            )
        return vm.monitor.info("pci")

    def is_supported_command(cmd1, cmd2):
        try:
            vm.monitor.verify_supported_cmd(cmd1)
            return cmd1
        except qemu_monitor.MonitorNotSupportedCmdError:
            try:
                vm.monitor.verify_supported_cmd(cmd2)
                return cmd2
            except qemu_monitor.MonitorNotSupportedCmdError:
                pass
        return None

    def is_supported_device(dev):
        # Probe qemu to verify what is the supported syntax for PCI hotplug
        cmd_type = is_supported_command("device_add", "pci_add")
        if not cmd_type:
            test.error("Unknown version of qemu")

        # Probe qemu for a list of supported devices
        probe_output = vm.monitor.human_monitor_cmd("%s ?" % cmd_type, debug=False)
        devices_supported = [
            j.strip('"')
            for j in re.findall(
                r"\"[a-z|0-9|\-|\_|\,|\.]*\"", probe_output, re.MULTILINE
            )
        ]
        test.log.debug(
            "QEMU reported the following supported devices for " "PCI hotplug: %s",
            devices_supported,
        )
        return dev in devices_supported

    def verify_supported_device(dev):
        if not is_supported_device(dev):
            test.error("%s doesn't support device: %s" % (cmd_type, dev))

    def device_add_nic(pci_num, queues=1):
        device_id = pci_type + "-" + utils_misc.generate_random_id()
        pci_info.append([device_id, device_id])

        pci_model = params.get("pci_model")
        if pci_model == "virtio":
            pci_model = "virtio-net-pci"
        verify_supported_device(pci_model)
        pci_add_cmd = "device_add id=%s,driver=%s" % (pci_info[pci_num][1], pci_model)
        if queues > 1 and "virtio" in pci_model:
            pci_add_cmd += ",mq=on"
        return device_add(pci_num, pci_add_cmd)

    def device_add_block(pci_num, queues=1):
        device_id = pci_type + "-" + utils_misc.generate_random_id()
        pci_info.append([device_id, device_id])

        image_format = params.get("image_format_%s" % img_list[pci_num + 1])
        if not image_format:
            image_format = params.get("image_format", "qcow2")
        image_filename = find_image(pci_num)
        data_image = params.get("images").split()[-1]
        serial_id = params["blk_extra_params_%s" % data_image].split("=")[1]

        pci_model = params.get("pci_model")
        controller_model = None
        if pci_model == "virtio":
            pci_model = "virtio-blk-pci"

        if pci_model == "scsi" or pci_model == "scsi-hd":
            if pci_model == "scsi":
                pci_model = "scsi-disk"
                if arch.ARCH in ("ppc64", "ppc64le"):
                    controller_model = "spapr-vscsi"
                else:
                    controller_model = "lsi53c895a"
            if pci_model == "scsi-hd":
                controller_model = "virtio-scsi-pci"
            verify_supported_device(controller_model)
            controller_id = "controller-" + device_id
            if vm.monitor.protocol == "human":
                controller_add_cmd = "device_add %s,id=%s" % (
                    controller_model,
                    controller_id,
                )
            else:
                controller_add_cmd = "device_add driver=%s,id=%s" % (
                    controller_model,
                    controller_id,
                )
            error_context.context("Adding SCSI controller.", test.log.info)
            vm.monitor.send_args_cmd(controller_add_cmd, convert=False)

        verify_supported_device(pci_model)
        driver_add_cmd = "%s auto file=%s,if=none,format=%s,id=%s,serial=%s" % (
            drive_cmd_type,
            image_filename,
            image_format,
            pci_info[pci_num][0],
            serial_id,
        )
        if drive_cmd_type == "__com.redhat_drive_add":
            driver_add_cmd = "%s file=%s,format=%s,id=%s,serial=%s" % (
                drive_cmd_type,
                image_filename,
                image_format,
                pci_info[pci_num][0],
                serial_id,
            )
        # add block device to vm device container
        image_name = img_list[pci_num + 1]
        image_params = params.object_params(image_name)
        image_name = pci_info[pci_num][0]
        blk_insert = vm.devices.images_define_by_params(
            image_name, image_params, "disk"
        )
        vm.devices.insert(blk_insert)
        env.register_vm(vm.name, vm)

        # add driver.
        error_context.context("Adding driver.", test.log.info)
        vm.monitor.send_args_cmd(driver_add_cmd, convert=False)

        pci_add_cmd = "device_add id=%s,driver=%s,drive=%s" % (
            pci_info[pci_num][1],
            pci_model,
            pci_info[pci_num][0],
        )
        return device_add(pci_num, pci_add_cmd)

    def device_add(pci_num, pci_add_cmd):
        error_context.context(
            "Adding pci device with command 'device_add'", test.log.info
        )
        if vm.monitor.protocol == "qmp":
            add_output = vm.monitor.send_args_cmd(pci_add_cmd, convert=False)
        else:
            add_output = vm.monitor.send_args_cmd(pci_add_cmd, convert=False)
        pci_info[pci_num].append(add_output)
        pci_info[pci_num].append(pci_model)

        after_add = vm.monitor.info("pci")
        if pci_info[pci_num][1] not in str(after_add):
            test.log.error(
                "Could not find matched id in monitor:" " %s", pci_info[pci_num][1]
            )
            test.fail(
                "Add device failed. Monitor command is: %s"
                ". Output: %r" % (pci_add_cmd, add_output)
            )
        return after_add

    # Hot add a pci device
    def add_device(pci_num, queues=1):
        info_pci_ref = vm.monitor.info("pci")
        reference = session.cmd_output(reference_cmd)

        try:
            # get function for adding device.
            add_fuction = local_functions["%s_%s" % (cmd_type, pci_type)]
        except Exception:
            test.error(
                "No function for adding '%s' dev with '%s'" % (pci_type, cmd_type)
            )
        after_add = None
        if add_fuction:
            # Do add pci device.
            after_add = add_fuction(pci_num, queues)

        try:
            # Define a helper function to compare the output
            def _new_shown():
                o = session.cmd_output(reference_cmd)
                return o != reference

            # Define a helper function to catch PCI device string
            def _find_pci():
                output = session.cmd_output(params.get("find_pci_cmd"))
                output = [line.strip() for line in output.splitlines()]
                ref = [line.strip() for line in reference.splitlines()]
                output = [_ for _ in output if _ not in ref]
                output = "\n".join(output)
                if re.search(params.get("match_string"), output, re.I | re.M):
                    return True
                return False

            error_context.context("Start checking new added device", test.log.info)
            # Compare the output of 'info pci'
            if after_add == info_pci_ref:
                test.fail(
                    "No new PCI device shown after executing "
                    "monitor command: 'info pci'"
                )

            secs = int(params.get("wait_secs_for_hook_up", 3))
            if not utils_misc.wait_for(_new_shown, test_timeout, secs, 3):
                test.fail(
                    "No new device shown in output of command "
                    "executed inside the guest: %s" % reference_cmd
                )

            if not utils_misc.wait_for(_find_pci, test_timeout, 3, 3):
                test.fail(
                    "PCI %s %s device not found in guest. "
                    "Command was: %s"
                    % (pci_model, pci_type, params.get("find_pci_cmd"))
                )

            # Test the newly added device
            try:
                if params.get("pci_test_cmd"):
                    test_cmd = re.sub(
                        "PCI_NUM", "%s" % (pci_num + 1), params.get("pci_test_cmd")
                    )
                    session.cmd(test_cmd, timeout=disk_op_timeout)
            except aexpect.ShellError as e:
                test.fail(
                    "Check for %s device failed after PCI "
                    "hotplug. Output: %r" % (pci_type, e.output)
                )

        except Exception:
            pci_del(pci_num, ignore_failure=True)
            raise

    # Hot delete a pci device
    def pci_del(pci_num, ignore_failure=False):
        def _device_removed():
            after_del = vm.monitor.info("pci")
            return after_del != before_del

        before_del = vm.monitor.info("pci")
        blk_removed = []
        if cmd_type == "pci_add":
            slot_id = int(pci_info[pci_num][2].split(",")[2].split()[1])
            cmd = "pci_del pci_addr=%s" % hex(slot_id)
            vm.monitor.send_args_cmd(cmd, convert=False)
            blk_removed.append(pci_info[pci_num][1])
        elif cmd_type == "device_add":
            if vm.monitor.protocol == "human":
                cmd = "device_del %s" % pci_info[pci_num][1]
            else:
                cmd = "device_del id=%s" % pci_info[pci_num][1]
            vm.monitor.send_args_cmd(cmd, convert=False)
            if params.get("cmd_after_unplug_dev"):
                cmd = re.sub(
                    "PCI_NUM", "%s" % (pci_num + 1), params.get("cmd_after_unplug_dev")
                )
                session.cmd(cmd, timeout=disk_op_timeout)
            blk_removed.append(pci_info[pci_num][1])
            pci_model = params.get("pci_model")
            if pci_model == "scsi" or pci_model == "scsi-hd":
                controller_id = "controller-" + pci_info[pci_num][0]
                if vm.monitor.protocol == "human":
                    controller_del_cmd = "device_del %s" % controller_id
                else:
                    controller_del_cmd = "device_del id=%s" % controller_id
                error_context.context("Deleting SCSI controller.", test.log.info)
                vm.monitor.send_args_cmd(controller_del_cmd, convert=False)
                blk_removed.append(controller_id)

        if (
            not utils_misc.wait_for(_device_removed, test_timeout, 0, 1)
            and not ignore_failure
        ):
            test.fail(
                "Failed to hot remove PCI device: %s. "
                "Monitor command: %s" % (pci_info[pci_num][3], cmd)
            )
        # Remove the device from vm device container
        for device in vm.devices:
            if device.str_short() in blk_removed:
                vm.devices.remove(device)
        env.register_vm(vm.name, vm)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)

    test_timeout = int(params.get("hotplug_timeout", 360))
    disk_op_timeout = int(params.get("disk_op_timeout", 360))
    reference_cmd = params["reference_cmd"]
    # Test if it is nic or block
    pci_type = params["pci_type"]
    pci_model = params["pci_model"]

    # Modprobe the module if specified in config file
    module = params.get("modprobe_module")
    if module:
        session.cmd("modprobe %s" % module)

    # check monitor type
    qemu_binary = utils_misc.get_qemu_binary(params)
    qemu_binary = utils_misc.get_path(test.bindir, qemu_binary)
    # Probe qemu to verify what is the supported syntax for PCI hotplug
    cmd_type = is_supported_command("device_add", "pci_add")
    if not cmd_type:
        test.error(
            "Could find a suitable method for hotplugging"
            " device in this version of qemu"
        )

    # Determine syntax of drive hotplug
    # __com.redhat_drive_add == qemu-kvm-0.12 on RHEL 6
    # drive_add == qemu-kvm-0.13 onwards
    drive_cmd_type = is_supported_command("drive_add", "__com.redhat_drive_add")
    if not drive_cmd_type:
        test.error(
            "Could find a suitable method for hotplugging"
            " drive in this version of qemu"
        )

    local_functions = locals()

    pci_num_range = int(params.get("pci_num"))
    queues = int(params.get("queues", 1))
    rp_times = int(params.get("repeat_times"))
    img_list = params.get("images").split()
    context_msg = "Running sub test '%s' %s"
    for j in range(rp_times):
        # pci_info is a list of list.
        # each element 'i' has 4 members:
        # pci_info[i][0] == device drive id, only used for device_add
        # pci_info[i][1] == device id, only used for device_add
        # pci_info[i][2] == output of device add command
        # pci_info[i][3] == device module name.
        pci_info = []
        for pci_num in range(pci_num_range):
            sub_type = params.get("sub_type_before_plug")
            if sub_type:
                error_context.context(
                    context_msg % (sub_type, "before hotplug"), test.log.info
                )
                utils_test.run_virt_sub_test(test, params, env, sub_type)

            error_context.context(
                "Start hot-adding pci device, repeat %d" % j, test.log.info
            )
            add_device(pci_num, queues)

            sub_type = params.get("sub_type_after_plug")
            if sub_type:
                error_context.context(
                    context_msg % (sub_type, "after hotplug"), test.log.info
                )
                utils_test.run_virt_sub_test(test, params, env, sub_type)
        for pci_num in range(pci_num_range):
            sub_type = params.get("sub_type_before_unplug")
            if sub_type:
                error_context.context(
                    context_msg % (sub_type, "before hotunplug"), test.log.info
                )
                utils_test.run_virt_sub_test(test, params, env, sub_type)

            error_context.context(
                "start hot-deleting pci device, repeat %d" % j, test.log.info
            )
            pci_del(-(pci_num + 1))

            sub_type = params.get("sub_type_after_unplug")
            if sub_type:
                error_context.context(
                    context_msg % (sub_type, "after hotunplug"), test.log.info
                )
                utils_test.run_virt_sub_test(test, params, env, sub_type)

    if params.get("reboot_vm", "no") == "yes":
        vm.reboot()
