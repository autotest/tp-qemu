"""
multi_disk_random_hotplug test for Autotest framework.

:copyright: 2013 Red Hat Inc.
"""

import random
import re
import time

from avocado.utils import process
from virttest import (
    data_dir,
    env_process,
    error_context,
    funcatexit,
    qemu_qtree,
    utils_disk,
    utils_test,
)
from virttest.qemu_monitor import Monitor
from virttest.remote import LoginTimeoutError

from provider.block_devices_plug import BlockDevicesPlug
from provider.storage_benchmark import generate_instance


def stop_stresser(vm, stop_cmd):
    """
    Wrapper which connects to vm and sends the stop_cmd
    :param vm: Virtual Machine
    :type vm: virttest.virt_vm.BaseVM
    :param stop_cmd: Command to stop the stresser
    :type stop_cmd: string
    """
    try:
        session = vm.wait_for_login(timeout=10)
        session.cmd(stop_cmd)
        session.close()
    except LoginTimeoutError:
        vm.destroy(gracefully=False)


# TODO: Remove this silly function when qdev vs. qtree comparison is available
def convert_params(params, args):
    """
    Updates params according to images_define_by_params arguments.
    :note: This is only temporarily solution until qtree vs. qdev verification
           is available.
    :param params: Dictionary with the test parameters
    :type params: virttest.utils_params.Params
    :param args: Dictionary of images_define_by_params arguments
    :type args: dictionary
    :return: Updated dictionary with the test parameters
    :rtype: virttest.utils_params.Params
    """
    convert = {
        "fmt": "drive_format",
        "cache": "drive_cache",
        "werror": "drive_werror",
        "rerror": "drive_rerror",
        "serial": "drive_serial",
        "snapshot": "image_snapshot",
        "bus": "drive_bus",
        "unit": "drive_unit",
        "port": "drive_port",
        "readonly": "image_readonly",
        "scsiid": "drive_scsiid",
        "lun": "drive_lun",
        "aio": "image_aio",
        "imgfmt": "image_format",
        "pci_addr": "drive_pci_addr",
        "x_data_plane": "x-data-plane",
        "scsi": "virtio-blk-pci_scsi",
    }
    name = args.pop("name")
    params["images"] += " %s" % name
    params["image_name_%s" % name] = args.pop("filename")
    params["image_size_%s" % name] = params["stg_image_size"]
    params["remove_image_%s" % name] = "yes"
    params["boot_drive_%s" % name] = "no"
    if params.get("image_format_%s" % name):
        params["image_format_%s" % name] = params.get("image_format_%s" % name)
    else:
        params["image_format_%s" % name] = params.get("image_format")
    if params.get("image_iothread_%s" % name):
        params["image_iothread_%s" % name] = params.get("image_iothread_%s" % name)
    else:
        params["image_iothread_%s" % name] = params.get("image_iothread")
    for key, value in args.items():
        params["%s_%s" % (convert.get(key, key), name)] = value
    return params


@error_context.context_aware
def run(test, params, env):
    """
    This tests the disk hotplug/unplug functionality.
    1) prepares multiple disks to be hotplugged
    2) hotplugs them
    3) verifies that they are in qtree/guest system/...
    4) stop I/O stress_cmd
    5) unplugs them
    6) continue I/O stress_cmd
    7) verifies they are not in qtree/guest system/...
    8) repeats $repeat_times

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def verify_qtree(params, info_qtree, info_block, qdev):
        """
        Verifies that params, info qtree, info block and /proc/scsi/ matches
        :param params: Dictionary with the test parameters
        :type params: virttest.utils_params.Params
        :param info_qtree: Output of "info qtree" monitor command
        :type info_qtree: string
        :param info_block: Output of "info block" monitor command
        :type info_block: dict of dicts
        :param qdev: qcontainer representation
        :type qdev: virttest.qemu_devices.qcontainer.DevContainer
        """
        err = 0
        qtree = qemu_qtree.QtreeContainer()
        qtree.parse_info_qtree(info_qtree)
        disks = qemu_qtree.QtreeDisksContainer(qtree.get_nodes())
        (tmp1, tmp2) = disks.parse_info_block(info_block)
        err += tmp1 + tmp2
        err += disks.generate_params()
        err += disks.check_disk_params(params)
        if err:
            test.log.error("info qtree:\n%s", info_qtree)
            test.log.error("info block:\n%s", info_block)
            test.log.error(qdev.str_bus_long())
            test.fail("%s errors occurred while verifying" " qtree vs. params" % err)

    def _create_params_matrix():
        matrix = {}
        stg_image_name = params["stg_image_name"]
        if not stg_image_name[0] == "/":
            stg_image_name = "%s/%s" % (data_dir.get_data_dir(), stg_image_name)
        matrix["stg_image_name"] = stg_image_name
        stg_params = params.get("stg_params", "").split(" ")
        for i in range(len(stg_params)):
            if not stg_params[i].strip():
                continue
            if stg_params[i][-1] == "\\":
                stg_params[i] = "%s %s" % (stg_params[i][:-1], stg_params.pop(i + 1))
            if not stg_params[i].strip():
                continue
            (cmd, parm) = stg_params[i].split(":", 1)
            # ',' separated list of values
            parm = parm.split(",")
            for j in range(len(parm)):
                if parm[j][-1] == "\\":
                    parm[j] = "%s,%s" % (parm[j][:-1], parm.pop(j + 1))
            matrix[cmd] = parm
        return matrix

    def configure_images_params(params):
        params_matrix = _create_params_matrix()
        _formats = params_matrix.pop("fmt", [params.get("drive_format")])
        formats = _formats[:]
        usb_port_occupied = 0
        usb_max_port = params.get("usb_max_port", 6)
        set_drive_bus = params.get("set_drive_bus", "no") == "yes"
        no_disks = int(params["stg_image_num"])
        i = 0
        while i < no_disks:
            # Set the format
            if len(formats) < 1:
                if i == 0:
                    test.error("Fail to add any disks, probably bad" " configuration.")
                test.log.warning(
                    "Can't create desired number '%s' of disk types "
                    "'%s'. Using '%d' no disks.",
                    no_disks,
                    _formats,
                    i,
                )
                break
            name = "stg%d" % i
            args = {"name": name, "filename": params_matrix["stg_image_name"] % i}
            fmt = random.choice(formats)
            drive_bus = None
            if set_drive_bus and fmt != "virtio":
                drive_bus = str(i)
            if fmt == "virtio_scsi":
                args["fmt"] = "scsi-hd"
                args["scsi_hba"] = "virtio-scsi-pci"
            elif fmt == "lsi_scsi":
                args["fmt"] = "scsi-hd"
                args["scsi_hba"] = "lsi53c895a"
            elif fmt == "spapr_vscsi":
                args["fmt"] = "scsi-hd"
                args["scsi_hba"] = "spapr-vscsi"
            elif fmt == "usb2" or fmt == "usb3":
                usb_port_occupied += 1
                if usb_port_occupied > int(usb_max_port):
                    continue
                args["fmt"] = fmt
            else:
                args["fmt"] = fmt
            args["drive_bus"] = drive_bus
            # Other params
            for key, value in params_matrix.items():
                args[key] = random.choice(value)
            env_process.preprocess_image(
                test, convert_params(params, args).object_params(name), name
            )
            i += 1

    def _postprocess_images():
        # remove and check the images
        _disks = []
        for disk in params["images"].split(" "):
            if disk.startswith("stg"):
                env_process.postprocess_image(test, params.object_params(disk), disk)
            else:
                _disks.append(disk)
            params["images"] = " ".join(_disks)

    def verify_qtree_unsupported(params, info_qtree, info_block, qdev):
        return test.log.warning(
            "info qtree not supported. Can't verify qtree vs. " "guest disks."
        )

    def enable_driver_verifier(driver, timeout=300):
        return utils_test.qemu.windrv_check_running_verifier(
            session, vm, test, driver, timeout
        )

    def _initial_win_drives():
        size = params["stg_image_size"]
        disks = utils_disk.get_windows_disks_index(session, size)
        if not utils_disk.update_windows_disk_attributes(session, disks):
            test.fail("Failed to update windows disk attributes.")
        for disk in disks[1:24]:
            yield utils_disk.configure_empty_windows_disk(session, disk, size)[0]

    def run_stress_iozone():
        error_context.context("Run iozone stress after hotplug", test.log.info)
        iozone = generate_instance(params, vm, "iozone")
        try:
            iozone_cmd_option = params["iozone_cmd_option"]
            iozone_timeout = float(params["iozone_timeout"])
            for letter in _initial_win_drives():
                iozone.run(iozone_cmd_option.format(letter), iozone_timeout)
        finally:
            iozone.clean()

    def run_stress_dd():
        error_context.context("Run dd stress after hotplug", test.log.info)
        output = session.cmd_output(params.get("get_dev_cmd", "ls /dev/[svh]d*"))
        system_dev = re.findall(r"/dev/[svh]d\w+(?=\d+)", output)[0]
        for dev in re.split(r"\s+", output):
            if not dev:
                continue
            if not re.findall(system_dev, dev):
                session.cmd(params["dd_cmd"].format(dev), int(params["dd_timeout"]))

    Monitor.CONNECT_TIMEOUT = params.get_numeric("connect_timeout", 60)
    BlockDevicesPlug.ACQUIRE_LOCK_TIMEOUT = params.get_numeric(
        "acquire_lock_timeout", 20
    )
    BlockDevicesPlug.VERIFY_UNPLUG_TIMEOUT = params.get_numeric(
        "verify_unplug_timeout", 60
    )

    configure_images_params(params)
    params["start_vm"] = "yes"
    env_process.preprocess_vm(test, params, env, params["main_vm"])
    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))
    is_windows = params["os_type"] == "windows"

    try:
        if is_windows:
            session = enable_driver_verifier(params["driver_name"])
        out = vm.monitor.human_monitor_cmd("info qtree", debug=False)
        if "unknown command" in str(out):
            verify_qtree = verify_qtree_unsupported

        # Modprobe the module if specified in config file
        module = params.get("modprobe_module")
        if module:
            session.cmd("modprobe %s" % module)

        stress_cmd = params.get("stress_cmd")
        if stress_cmd:
            funcatexit.register(
                env,
                params.get("type"),
                stop_stresser,
                vm,
                params.get("stress_kill_cmd"),
            )
            stress_session = vm.wait_for_login(timeout=10)
            for _ in range(int(params.get("no_stress_cmds", 1))):
                stress_session.sendline(stress_cmd)

        rp_times = int(params.get("repeat_times", 1))
        queues = params.get("multi_disk_type") == "parallel"
        timeout = params.get_numeric("plug_timeout", 300)
        interval_time_unplug = params.get_numeric("interval_time_unplug", 0)
        if queues:  # parallel
            hotplug, unplug = "hotplug_devs_threaded", "unplug_devs_threaded"
        else:  # serial
            hotplug, unplug = "hotplug_devs_serial", "unplug_devs_serial"

        context_msg = "Running sub test '%s' %s"
        plug = BlockDevicesPlug(vm)
        for iteration in range(rp_times):
            error_context.context(
                "Hotplugging/unplugging devices, iteration %d" % iteration,
                test.log.info,
            )
            sub_type = params.get("sub_type_before_plug")
            if sub_type:
                error_context.context(
                    context_msg % (sub_type, "before hotplug"), test.log.info
                )
                utils_test.run_virt_sub_test(test, params, env, sub_type)

            error_context.context("Hotplug the devices", test.log.debug)
            getattr(plug, hotplug)(timeout=timeout)
            time.sleep(float(params.get("wait_after_hotplug", 0)))

            error_context.context("Verify disks after hotplug", test.log.debug)
            info_qtree = vm.monitor.info("qtree", False)
            info_block = vm.monitor.info_block(False)
            vm.verify_alive()
            verify_qtree(params, info_qtree, info_block, vm.devices)

            sub_type = params.get("sub_type_after_plug")
            if sub_type:
                error_context.context(
                    context_msg % (sub_type, "after hotplug"), test.log.info
                )
                utils_test.run_virt_sub_test(test, params, env, sub_type)
            run_stress_iozone() if is_windows else run_stress_dd()
            sub_type = params.get("sub_type_before_unplug")
            if sub_type:
                error_context.context(
                    context_msg % (sub_type, "before hotunplug"), test.log.info
                )
                utils_test.run_virt_sub_test(test, params, env, sub_type)

            error_context.context("Unplug and remove the devices", test.log.debug)
            if stress_cmd:
                session.cmd(params["stress_stop_cmd"])
            getattr(plug, unplug)(timeout=timeout, interval=interval_time_unplug)
            if stress_cmd:
                session.cmd(params["stress_cont_cmd"])
            _postprocess_images()

            error_context.context("Verify disks after unplug", test.log.debug)
            time.sleep(params.get_numeric("wait_after_unplug", 0, float))
            info_qtree = vm.monitor.info("qtree", False)
            info_block = vm.monitor.info_block(False)
            vm.verify_alive()
            verify_qtree(params, info_qtree, info_block, vm.devices)

            sub_type = params.get("sub_type_after_unplug")
            if sub_type:
                error_context.context(
                    context_msg % (sub_type, "after hotunplug"), test.log.info
                )
                utils_test.run_virt_sub_test(test, params, env, sub_type)
            configure_images_params(params)

        # Check for various KVM failures
        error_context.context(
            "Validating VM after all disk hotplug/unplugs", test.log.debug
        )
        vm.verify_alive()
        out = session.cmd_output("dmesg")
        if "I/O error" in out:
            test.log.warning(out)
            test.error(
                "I/O error messages occured in dmesg, " "check the log for details."
            )
    except Exception as e:
        pid = vm.get_pid()
        test.log.debug("Find %s Exception:'%s'.", pid, str(e))
        if pid:
            logdir = test.logdir
            process.getoutput("gstack %s > %s/gstack.log" % (pid, logdir))
            process.getoutput(
                "timeout 20 strace -tt -T -v -f -s 32 -p %s -o %s/strace.log"
                % (pid, logdir)
            )
        else:
            test.log.debug("VM dead...")
        raise e
