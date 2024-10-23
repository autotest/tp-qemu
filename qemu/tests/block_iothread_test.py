"""Block device iothread relevant test"""

import re

from aexpect import ShellCmdError
from virttest import env_process, error_context, utils_disk, utils_misc, virt_vm
from virttest.utils_misc import get_linux_drive_path
from virttest.utils_windows.drive import get_disk_props_by_serial_number

from provider.block_devices_plug import BlockDevicesPlug


# This decorator makes the test function aware of context strings
@error_context.context_aware
def run(test, params, env):
    """
    Block device iothread relevant test
    The test include boot positive and negative
    Positive:
    1) Boot Vm data disk enable iothread.
    2) Check disk iothread set.
    3) unplug and hotplug disk.
    4) Simple IO on disk.
    5) Check disk iothread set.
    Negative:
    1) Boot Vm data disk with wrong configration.
    2) Catch exception to check the message whether is expected ?
    """

    def _get_window_disk_index_by_serial(serial):
        idx_info = get_disk_props_by_serial_number(session, serial, ["Index"])
        if idx_info:
            return idx_info["Index"]
        test.fail("Not find expected disk %s" % serial)

    def _check_disk_in_guest(img):
        os_type = params["os_type"]
        logger.debug("Check disk %s in guest", img)
        if os_type == "windows":
            img_size = params.get("image_size_%s" % img)
            cmd = utils_misc.set_winutils_letter(session, guest_cmd)
            disk = _get_window_disk_index_by_serial(img)
            utils_disk.update_windows_disk_attributes(session, disk)
            logger.info("Clean disk:%s", disk)
            utils_disk.clean_partition_windows(session, disk)
            logger.info("Formatting disk:%s", disk)
            driver = utils_disk.configure_empty_disk(session, disk, img_size, os_type)[
                0
            ]
            output_path = driver + ":\\test.dat"
            cmd = cmd.format(output_path)
        else:
            output_path = get_linux_drive_path(session, img)
            cmd = guest_cmd.format(output_path)

        logger.debug(cmd)
        session.cmd(cmd)

    def check_image_iothread():
        images = params.get_list("check_iothread_images")
        iothread_type = params.get("check_iothread_type", "iothread")
        for img in images:
            attr = img.split(":")
            name = attr[0]
            num = int(attr[1]) if attr[1] else 0
            expect_iothreads = set(attr[2].split(",") if attr[2] else [])
            logger.debug("Expected %s iothread :%s %s", name, num, expect_iothreads)
            parent_bus = vm.monitor.qom_get(name, "parent_bus")
            parent_bus_type = vm.monitor.qom_get(parent_bus, "type")
            check_name = name
            if parent_bus_type == "SCSI":
                check_name = parent_bus.split("/")[3]
                logger.debug("Ready to check SCSI %s iothread", check_name)

            cmd_out = vm.monitor.qom_get(check_name, iothread_type)
            logger.debug("Get %s %s out:%s", check_name, iothread_type, cmd_out)
            if iothread_type == "iothread":
                cmd_out = cmd_out.replace("/objects/", "").split()
            else:
                # iothread-vq-mapping
                cmd_out = [i["iothread"] for i in cmd_out]

            real_iothreads = set(cmd_out)
            logger.debug("Real iothread %s :%s", name, real_iothreads)

            if expect_iothreads:
                if real_iothreads != expect_iothreads:
                    test.fail(
                        "Get unexpeced %s iothread list:%s %s"
                        % (name, expect_iothreads, real_iothreads)
                    )
            else:
                if len(real_iothreads) != num:
                    test.fail(
                        "Get unexpeced %s iothread len:%s %s"
                        % (name, num, len(real_iothreads))
                    )

    def hotplug_disks_test():
        plug = BlockDevicesPlug(vm)
        for img in test_images:
            plug.unplug_devs_serial(img)
            plug.hotplug_devs_serial(img)
            _check_disk_in_guest(img)

        check_image_iothread()

    logger = test.log

    vm = None
    session = None
    expect_to_fail = params.get("expect_to_fail", "no")
    err_msg = params.get("err_msg", "undefined unknown error")
    start_vm = params.get("start_vm")
    try:
        timeout = params.get_numeric("login_timeout", 180)
        test_images = params.get_list("test_images")
        host_cmd = params.get("host_cmd")
        guest_cmd = params.get("guest_cmd")
        guest_operation = params.get("guest_operation")

        if params.get("not_preprocess", "no") == "yes":
            logger.debug("Ready boot VM : %s", params["images"])
            env_process.process(
                test,
                params,
                env,
                env_process.preprocess_image,
                env_process.preprocess_vm,
            )

        error_context.context("Get the main VM", test.log.info)
        vm = env.get_vm(params["main_vm"])
        vm.verify_alive()

        session = vm.wait_for_login(timeout=timeout)
        check_image_iothread()
        locals_var = locals()
        if guest_operation:
            logger.debug("Execute guest operation %s", guest_operation)
            locals_var[guest_operation]()

        logger.debug("Destroy VM...")
        session.close()
        vm.destroy()
        vm = None
    except (virt_vm.VMCreateError, virt_vm.VMStartError, ShellCmdError) as e:
        logger.debug("Find exception %s", e)
        match = re.search(err_msg, e.output)
        if expect_to_fail == "yes" and match:
            logger.info("%s is expected ", err_msg)
            # reset expect_to_fail
            expect_to_fail = "no"
        else:
            raise e
    finally:
        if vm:
            vm.destroy()

        if expect_to_fail != "no":
            test.fail("Expected '%s' not happened" % err_msg)
