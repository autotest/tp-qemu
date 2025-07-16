import time

from virttest import error_context, utils_disk, utils_misc
from virttest.qemu_monitor import QMPCmdError


@error_context.context_aware
def run(test, params, env):
    """
    Hotplug a LUKS device with a detached header to a running VM (Linux or Windows),
    do IO, then unplug and verify.
    Steps:
      1. Boot the VM (images are assumed to be created by the framework)
      2. Hotplug the LUKS device with QMP (detached header)
      3. Do read/write IO in the guest
      4. Unplug and verify
      5. Clean up images
    """

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    login_timeout = int(params.get("login_timeout", 360))
    disk_op_cmd = params.get("disk_op_cmd")
    disk_op_timeout = int(params.get("disk_op_timeout", 360))
    luks_secret = params.get("image_secret_header", "redhat")
    luks_header = params.get("luks_header_img", "test-header.img")
    luks_payload = params.get("luks_payload_img", "test-payload.img")
    os_type = params.get("os_type", "linux").lower()
    windows = os_type == "windows"

    # 1. Boot VM
    session = vm.wait_for_login(timeout=login_timeout)
    if windows:
        disks_before = set(session.cmd("wmic diskdrive get index").split()[1:])
    else:
        disks_before = set(utils_misc.list_linux_guest_disks(session))
    session.close()

    # 2. QMP hotplug sequence
    try:
        # blockdev-add for payload
        vm.monitor.cmd(
            "blockdev-add",
            {
                "node-name": "libvirt-1-storage",
                "driver": "file",
                "filename": luks_payload,
            },
        )
        # blockdev-add for header
        vm.monitor.cmd(
            "blockdev-add",
            {
                "node-name": "libvirt-2-storage",
                "driver": "file",
                "filename": luks_header,
            },
        )
        # object-add secret
        vm.monitor.cmd(
            "object-add",
            {
                "qom-type": "secret",
                "id": "libvirt-2-storage-secret0",
                "data": luks_secret,
            },
        )
        # blockdev-add for raw
        vm.monitor.cmd(
            "blockdev-add",
            {
                "node-name": "libvirt-1-format",
                "driver": "raw",
                "file": "libvirt-1-storage",
            },
        )
        # blockdev-add for luks
        vm.monitor.cmd(
            "blockdev-add",
            {
                "node-name": "libvirt-2-format",
                "driver": "luks",
                "file": "libvirt-1-format",
                "header": "libvirt-2-storage",
                "key-secret": "libvirt-2-storage-secret0",
            },
        )
        # device_add
        vm.monitor.cmd(
            "device_add",
            {
                "num-queues": "1",
                "driver": "virtio-blk-pci",
                "drive": "libvirt-2-format",
                "id": "virtio-disk2",
            },
        )
    except QMPCmdError as e:
        test.fail("QMP hotplug failed: %s" % e)
    except Exception as e:
        test.fail("QMP hotplug failed: %s" % e)

    # 3. IO in guest
    session = vm.wait_for_login(timeout=login_timeout)
    time.sleep(5)  # Wait for device to appear
    if windows:
        disks_after = set(session.cmd("wmic diskdrive get index").split()[1:])
        new_disks = list(disks_after - disks_before)
        if not new_disks:
            test.fail("No new disk detected after hotplug!")
        new_disk = new_disks[0]
        error_context.context(
            "New disk detected (Windows index): %s" % new_disk, test.log.info
        )
        # Format the disk if needed and get drive letter
        disk_index = params.objects("disk_index")
        disk_letter = params.objects("disk_letter")
        drive_letters = []
        if disk_index and disk_letter:
            idx = 0
            utils_misc.format_windows_disk(session, disk_index[idx], disk_letter[idx])
            drive_letters.append(disk_letter[idx])
            drive_letter = drive_letters[0]
        else:
            # Try to auto format and get letter
            drive_letter = utils_disk.configure_empty_windows_disk(
                session, new_disk, params.get("luks_payload_size", "5G")
            )[0]
        test_cmd = disk_op_cmd % (drive_letter, drive_letter)
        test_cmd = utils_misc.set_winutils_letter(session, test_cmd)
    else:
        disks_after = set(utils_misc.list_linux_guest_disks(session))
        new_disks = list(disks_after - disks_before)
        if not new_disks:
            test.fail("No new disk detected after hotplug!")
        new_disk = new_disks[0]
        error_context.context("New disk detected: %s" % new_disk, test.log.info)
        test_cmd = disk_op_cmd % (new_disk, new_disk)
    try:
        session.cmd(test_cmd, timeout=disk_op_timeout)
    except Exception as e:
        test.fail(f"IO on hotplugged disk failed: {e}")
    session.close()

    # 4. Unplug
    try:
        vm.monitor.cmd("device_del", {"id": "virtio-disk2"})
        # Wait for disk to disappear
        session = vm.wait_for_login(timeout=login_timeout)

        def disk_gone():
            if windows:
                return (
                    new_disk not in session.cmd("wmic diskdrive get index").split()[1:]
                )
            else:
                return new_disk not in utils_misc.list_linux_guest_disks(session)

        utils_misc.wait_for(disk_gone, 60, step=2)
        session.close()
    except Exception as e:
        test.fail(f"Unplug failed: {e}")
