import random
import re
import time

import aexpect
from virttest import arch, data_dir, env_process, error_context, storage, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    Test hotplug of PCI devices and check the status in guest.
    1 Boot up a guest
    2 Hotplug virtio disk to the guest. Record the id and partition name of
      the disk in a list.
    3 Random choice a disk in the list. Unplug the disk and check the
      partition status.
    4 Hotpulg the disk back to guest with the same monitor cmdline and same
      id which is record in step 2.
    5 Check the partition status in guest. And confirm the disk with dd cmd
    6 Repeat step 3 to 5 for N times

    :param test:   KVM test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """

    def prepare_image_params(params):
        pci_num = int(params["pci_num"])
        for i in range(pci_num):
            image_name = "%s_%s" % ("stg", i)
            params["images"] = " ".join([params["images"], image_name])
            image_image_name = "%s_%s" % ("image_name", image_name)
            params[image_image_name] = "%s_%s" % ("storage", i)
            image_image_format = "%s_%s" % ("image_format", image_name)
            params[image_image_format] = params.get("image_format_extra", "qcow2")
            image_image_size = "%s_%s" % ("image_size", image_name)
            params[image_image_size] = params.get("image_size_extra", "128K")
        return params

    def find_new_device(check_cmd, device_string, chk_timeout=30):
        end_time = time.time() + chk_timeout
        idx = ("wmic" in check_cmd and [0] or [-1])[0]
        time.sleep(2)
        while time.time() < end_time:
            new_line = session.cmd_output(check_cmd)
            for line in re.split("\n+", new_line.strip()):
                dev_name = re.split(r"\s+", line.strip())[idx]
                if dev_name not in device_string:
                    return dev_name
            time.sleep(3)
        return None

    def find_del_device(check_cmd, device_string, chk_timeout=30):
        end_time = time.time() + chk_timeout
        idx = ("wmic" in check_cmd and [0] or [-1])[0]
        time.sleep(2)
        while time.time() < end_time:
            new_line = session.cmd_output(check_cmd)
            for line in re.split("\n+", device_string.strip()):
                dev_name = re.split(r"\s+", line.strip())[idx]
                if dev_name not in new_line:
                    return dev_name
            time.sleep(3)
        return None

    # Select an image file
    def find_image(pci_num):
        image_params = params.object_params("%s" % img_list[pci_num + 1])
        o = storage.get_image_filename(image_params, data_dir.get_data_dir())
        return o

    def pci_add_block(pci_num, queues, pci_id):
        image_filename = find_image(pci_num)
        pci_add_cmd = "pci_add pci_addr=auto storage file=%s,if=%s" % (
            image_filename,
            pci_model,
        )
        return pci_add(pci_add_cmd)

    def pci_add(pci_add_cmd):
        guest_devices = session.cmd_output(chk_cmd)
        error_context.context("Adding pci device with command 'pci_add'")
        add_output = vm.monitor.send_args_cmd(pci_add_cmd, convert=False)
        guest_device = find_new_device(chk_cmd, guest_devices)
        pci_info.append(["", "", add_output, pci_model, guest_device])
        if "OK domain" not in add_output:
            test.fail(
                "Add PCI device failed. "
                "Monitor command is: %s, Output: %r" % (pci_add_cmd, add_output)
            )
        return vm.monitor.info("pci")

    def is_supported_device(dev):
        # Probe qemu to verify what is the supported syntax for PCI hotplug
        cmd_output = vm.monitor.human_monitor_cmd("?")
        if len(re.findall("\ndevice_add", cmd_output)) > 0:
            cmd_type = "device_add"
        elif len(re.findall("\npci_add", cmd_output)) > 0:
            cmd_type = "pci_add"
        else:
            test.error("Unknown version of qemu")

        # Probe qemu for a list of supported devices
        probe_output = vm.monitor.human_monitor_cmd("%s ?" % cmd_type)  # pylint: disable=E0606
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

    def device_add_block(pci_num, queues=1, pci_id=None):
        if pci_id is not None:
            device_id = pci_type + "-" + pci_id
        else:
            device_id = pci_type + "-" + utils_misc.generate_random_id()
            pci_info.append([device_id, device_id])

        image_format = params.get("image_format_%s" % img_list[pci_num + 1])
        if not image_format:
            image_format = params.get("image_format", "qcow2")
        image_filename = find_image(pci_num)

        pci_model = params.get("pci_model")
        controller_model = None
        bus_option = ""
        if (
            "q35" in params["machine_type"]
            or "arm64" in params["machine_type"]
            and drive_format == "virtio"
        ):
            bus_option = ",bus=pcie_extra_root_port_%d" % pci_num

        if pci_model == "virtio":
            pci_model = "virtio-blk-pci"

        if pci_model == "scsi":
            pci_model = "scsi-disk"
            if arch.ARCH in ("ppc64", "ppc64le"):
                controller_model = "spapr-vscsi"
            else:
                controller_model = "lsi53c895a"
            if nonlocal_vars["verify_device_flag"]:
                verify_supported_device(controller_model)
            controller_id = "controller-" + device_id
            controller_add_cmd = "device_add %s,id=%s" % (
                controller_model,
                controller_id,
            )
            error_context.context("Adding SCSI controller.")
            vm.monitor.send_args_cmd(controller_add_cmd)

        if nonlocal_vars["verify_device_flag"]:
            verify_supported_device(pci_model)
        nonlocal_vars["verify_device_flag"] = False

        add_cmd = "{0} driver=file,filename={1},node-name=file_{2}".format(
            drive_cmd_type, image_filename, pci_info[pci_num][0]
        )
        add_cmd += ";{0} driver={1},node-name={2},file=file_{2}".format(
            drive_cmd_type, image_format, pci_info[pci_num][0]
        )
        driver_add_cmd = add_cmd

        if drive_cmd_type == "drive_add":
            driver_add_cmd = "%s auto file=%s,if=none,format=%s,id=%s" % (
                drive_cmd_type,
                image_filename,
                image_format,
                pci_info[pci_num][0],
            )
        elif drive_cmd_type == "__com.redhat_drive_add":
            driver_add_cmd = "%s file=%s,format=%s,id=%s" % (
                drive_cmd_type,
                image_filename,
                image_format,
                pci_info[pci_num][0],
            )
        # add driver.
        error_context.context("Adding driver.")
        if drive_cmd_type != "blockdev-add":
            vm.monitor.send_args_cmd(driver_add_cmd, convert=False)
        elif pci_id is None:
            vm.monitor.send_args_cmd(driver_add_cmd, convert=False)

        pci_add_cmd = "device_add id=%s,driver=%s,drive=%s%s" % (
            pci_info[pci_num][1],
            pci_model,
            pci_info[pci_num][0],
            bus_option,
        )
        return device_add(pci_num, pci_add_cmd, pci_id=pci_id)

    def device_add(pci_num, pci_add_cmd, pci_id=None):
        error_context.context("Adding pci device with command 'device_add'")
        guest_devices = session.cmd_output(chk_cmd)
        if vm.monitor.protocol == "qmp":
            add_output = vm.monitor.send_args_cmd(pci_add_cmd)
        else:
            add_output = vm.monitor.send_args_cmd(pci_add_cmd, convert=False)
        guest_device = find_new_device(chk_cmd, guest_devices)
        if guest_device is None:
            test.fail("Failed add disk for %d" % pci_num)
        if pci_id is None:
            pci_info[pci_num].append(add_output)
            pci_info[pci_num].append(pci_model)
            pci_info[pci_num].append(guest_device)

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
    def add_device(pci_num, queues=1, pci_id=None):
        info_pci_ref = vm.monitor.info("pci")
        reference = session.cmd_output(reference_cmd)

        try:
            # get function for adding device.
            add_fuction = local_functions["%s_%s" % (cmd_type, pci_type)]
        except Exception:
            test.error(
                "No function for adding "
                + "'%s' dev " % pci_type
                + "with '%s'" % cmd_type
            )
        after_add = None
        if add_fuction:
            # Do add pci device.
            after_add = add_fuction(pci_num, queues, pci_id)

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
                if re.search(params.get("pci_id_pattern"), output, re.I):
                    return True
                return False

            error_context.context("Start checking new added device")
            # Compare the output of 'info pci'
            if after_add == info_pci_ref:
                test.fail(
                    "No new PCI device shown after "
                    "executing monitor command: 'info pci'"
                )

            secs = int(params.get("wait_secs_for_hook_up", 3))
            if not utils_misc.wait_for(_new_shown, test_timeout, secs, 3):
                test.fail(
                    "No new device shown in output of"
                    + "command executed inside the "
                    + "guest: %s" % reference_cmd
                )

            if not utils_misc.wait_for(_find_pci, test_timeout, 3, 3):
                test.fail(
                    "PCI %s %s " % (pci_model, pci_type)
                    + "device not found in guest. Command "
                    + "was: %s" % params.get("find_pci_cmd")
                )

            # Test the newly added device
            try:
                error_context.context("Check disk in guest", test.log.info)
                session.cmd(params.get("pci_test_cmd") % (pci_num + 1))
            except aexpect.ShellError as e:
                test.fail(
                    "Check for %s device failed" % pci_type
                    + "after PCI hotplug."
                    + "Output: %r" % e.output
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
        if cmd_type == "pci_add":
            slot_id = int(pci_info[pci_num][2].split(",")[2].split()[1])
            cmd = "pci_del pci_addr=%s" % hex(slot_id)
            vm.monitor.send_args_cmd(cmd, convert=False)
        elif cmd_type == "device_add":
            cmd = "device_del id=%s" % pci_info[pci_num][1]
            vm.monitor.send_args_cmd(cmd)

        if (
            not utils_misc.wait_for(_device_removed, test_timeout, 2, 3)
            and not ignore_failure
        ):
            test.fail(
                "Failed to hot remove PCI device: %s. "
                "Monitor command: %s" % (pci_info[pci_num][3], cmd)
            )

    nonlocal_vars = {"verify_device_flag": True}
    machine_type = params.get("machine_type")
    drive_format = params.get("drive_format")
    params = prepare_image_params(params)
    env_process.process_images(env_process.preprocess_image, test, params)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)

    test_timeout = int(params.get("hotplug_timeout", 360))
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
    # Probe qemu to verify what is the supported syntax for PCI hotplug
    if vm.monitor.protocol == "qmp":
        cmd_output = vm.monitor.info("commands")
    else:
        cmd_output = vm.monitor.human_monitor_cmd("help", debug=False)

    cmd_type = utils_misc.find_substring(str(cmd_output), "device_add", "pci_add")
    if not cmd_type:
        test.error(
            "Could find a suitable method for hotplugging"
            " device in this version of qemu"
        )

    # Determine syntax of drive hotplug
    # __com.redhat_drive_add == qemu-kvm-0.12 on RHEL 6
    # drive_add == qemu-kvm-0.13 onwards
    drive_cmd_type = utils_misc.find_substring(str(cmd_output), "blockdev-add")

    if not drive_cmd_type:
        drive_cmd_type = utils_misc.find_substring(
            str(cmd_output), "__com.redhat_drive_add", "drive_add"
        )
    if not drive_cmd_type:
        test.error("Unknown version of qemu")

    local_functions = locals()

    pci_num_range = int(params.get("pci_num"))
    rp_times = int(params.get("rp_times"))
    img_list = params.get("images").split()
    chk_cmd = params.get("guest_check_cmd")
    mark_cmd = params.get("mark_cmd")
    offset = params.get("offset")
    confirm_cmd = params.get("confirm_cmd")

    pci_info = []
    # Add block device into guest
    for pci_num in range(pci_num_range):
        error_context.context(
            "Prepare the %d removable pci device" % pci_num, test.log.info
        )
        add_device(pci_num)
        if pci_info[pci_num][4] is not None:
            partition = pci_info[pci_num][4]
            cmd = mark_cmd % (partition, partition, offset)
            session.cmd(cmd)
        else:
            test.error("Device not init in guest")

    for j in range(rp_times):
        # pci_info is a list of list.
        # each element 'i' has 4 members:
        # pci_info[i][0] == device drive id, only used for device_add
        # pci_info[i][1] == device id, only used for device_add
        # pci_info[i][2] == output of device add command
        # pci_info[i][3] == device module name.
        # pci_info[i][4] == partition id in guest
        pci_num = random.randint(0, len(pci_info) - 1)
        error_context.context(
            "start unplug device, repeat %d of %d-%d" % (j, rp_times, pci_num),
            test.log.info,
        )
        guest_devices = session.cmd_output(chk_cmd)
        pci_del(pci_num)
        device_del = find_del_device(chk_cmd, guest_devices)
        if device_del != pci_info[pci_num][4]:
            test.fail("Device is not deleted in guest.")

        # sleep to wait delete event
        time.sleep(5)
        error_context.context("Start plug pci device, repeat %d" % j, test.log.info)
        guest_devices = session.cmd_output(chk_cmd)
        add_device(pci_num, pci_id=pci_info[pci_num][0])
        device_del = find_new_device(chk_cmd, guest_devices)
        if device_del != pci_info[pci_num][4]:
            test.fail(
                "Device partition changed from %s to %s"
                % (pci_info[pci_num][4], device_del)
            )
        cmd = confirm_cmd % (pci_info[pci_num][4], offset)
        confirm_info = session.cmd_output(cmd)
        if device_del not in confirm_info:
            test.fail("Can not find partition tag in Guest: %s" % confirm_info)
