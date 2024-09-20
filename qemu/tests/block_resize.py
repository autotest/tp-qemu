import json
import re

from avocado.utils import process, wait
from virttest import (
    data_dir,
    error_context,
    storage,
    utils_disk,
    utils_misc,
    utils_numeric,
    utils_test,
)
from virttest.qemu_capabilities import Flags
from virttest.qemu_storage import QemuImg
from virttest.utils_windows import drive

from provider.storage_benchmark import generate_instance


@error_context.context_aware
def run(test, params, env):
    """
    KVM block resize test:

    1) Start guest with data disk or system disk.
    2) Do format disk in guest if needed.
    3) Record md5 of test file on the data disk.
       Enlarge the data disk image from qemu monitor.
    4) Extend data disk partition/file-system in guest.
    5) Verify the data disk size match expected size.
    6) Reboot the guest.
    7) Do iozone test, compare the md5 of test file.
    8) Shrink data disk partition/file-system in guest.
    9) Shrink data disk image from qemu monitor.
    10) Verify the data disk size match expected size.
    11) Reboot the guest.
    12) Do iozone test, compare the md5 of test file.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def verify_disk_size(session, os_type, disk):
        """
        Verify the current block size match with the expected size.
        """
        global current_size
        current_size = utils_disk.get_disk_size(session, os_type, disk)
        accept_ratio = float(params.get("accept_ratio", 0))
        if current_size <= block_size and current_size >= block_size * (
            1 - accept_ratio
        ):
            test.log.info(
                "Block Resizing Finished !!! \n"
                "Current size %s is same as the expected %s",
                current_size,
                block_size,
            )
            return True

    def create_md5_file(filename):
        """
        Create the file to verify md5 value.
        """
        test.log.debug("create md5 file %s", filename)
        if os_type == "windows":
            vm.copy_files_to(params["tmp_md5_file"], filename)
        else:
            session.cmd(params["dd_cmd"] % filename)

    def get_md5_of_file(filename):
        """
        Get the md5 value of filename.
        """
        ex_args = (mpoint, filename) if os_type == "windows" else filename
        return session.cmd(md5_cmd % ex_args).split()[0]

    def check_shrink_completion(vol_id, size):
        """
        Check the disk extend or shrink finished in windows guest.
        :param vol_id: Drive letter.
        :param size: shrink size.
        """

        def _check_event_cmd(cmd):
            status, output = session.cmd_status_output(cmd)
            test.log.debug("Get event: %s", output)
            test.log.debug("Expect contain msg: %s", msg)  # pylint: disable=E0606
            return status == 0 and regexp.search(output)  # pylint: disable=E0606

        drive.shrink_volume(session, mpoint, size)
        check_event = params.get("check_258_event")
        if check_event:
            msg = params.get("event_msg") % vol_id
            regexp = re.compile(msg)
            defrag_event_received = utils_misc.wait_for(
                lambda: _check_event_cmd(check_event), 180
            )

            if not defrag_event_received:
                test.fail(
                    "Did not receive the defrag finished event, "
                    "disk shrink failed in guest."
                )

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = float(params.get("login_timeout", 240))
    driver_name = params.get("driver_name")
    os_type = params["os_type"]
    fstype = params.get("fstype")
    labeltype = params.get("labeltype", "msdos")
    img_size = params.get("image_size_stg", "10G")
    mpoint = params.get("disk_letter", "C")
    disk = params.get("disk_index", 0)
    md5_cmd = params.get("md5_cmd", "md5sum %s")
    md5_file = params.get("md5_file", "md5.dat")
    data_image = params.get("images").split()[-1]
    data_image_params = params.object_params(data_image)
    data_image_filename = storage.get_image_filename(
        data_image_params, data_dir.get_data_dir()
    )
    data_image_dev = vm.get_block({"file": data_image_filename})
    img = QemuImg(data_image_params, data_dir.get_data_dir(), data_image)
    block_virtual_size = json.loads(img.info(force_share=True, output="json"))[
        "virtual-size"
    ]

    session = vm.wait_for_login(timeout=timeout)

    try:
        if os_type == "windows" and driver_name:
            session = utils_test.qemu.windrv_check_running_verifier(
                session, vm, test, driver_name, timeout
            )

        if params.get("format_disk") == "yes":
            if os_type == "linux":
                disk_dict = utils_disk.get_linux_disks(session)
                disk = sorted(disk_dict.keys())[0]
                disk_serial = disk_dict[disk][3]
            else:
                disk = utils_disk.get_windows_disks_index(session, img_size)[0]
                utils_disk.update_windows_disk_attributes(session, disk)
            error_context.context("Formatting disk", test.log.info)
            mpoint = utils_disk.configure_empty_disk(
                session, disk, img_size, os_type, fstype=fstype, labeltype=labeltype
            )[0]
            partition = mpoint.replace("mnt", "dev") if "mnt" in mpoint else None

        for ratio in params.objects("disk_change_ratio"):
            block_size = int(int(block_virtual_size) * float(ratio))
            # The new size must be a multiple of 512 for windows
            if params.get("os_type") == "windows" and block_size % 512 != 0:
                block_size = int(block_size / 512) * 512

            # Record md5
            if params.get("md5_test") == "yes":
                junction = ":\\" if os_type == "windows" else "/"
                md5_filename = mpoint + junction + md5_file
                create_md5_file(md5_filename)
                md5 = get_md5_of_file(md5_filename)
                test.log.debug("Got md5 %s ratio:%s on %s", md5, ratio, disk)

            # We need shrink the disk in guest first, then in monitor
            if float(ratio) < 1.0:
                error_context.context(
                    "Shrink disk size to %s in guest" % block_size, test.log.info
                )
                if os_type == "windows":
                    shr_size = utils_numeric.normalize_data_size(
                        str(
                            utils_disk.get_disk_size(session, os_type, disk)
                            - block_size
                        ),
                        "M",
                    ).split(".")[0]
                    check_shrink_completion(mpoint, shr_size)
                else:
                    utils_disk.resize_filesystem_linux(
                        session, partition, str(block_size)
                    )
                    utils_disk.resize_partition_linux(
                        session, partition, str(block_size)
                    )

            error_context.context(
                "Change disk size to %s in monitor" % block_size, test.log.info
            )
            if vm.check_capability(Flags.BLOCKDEV):
                args = (None, block_size, data_image_dev)
            else:
                args = (data_image_dev, block_size)
            vm.monitor.block_resize(*args)

            if params.get("guest_prepare_cmd", ""):
                session.cmd(params.get("guest_prepare_cmd") % disk)
            # Update GPT due to size changed
            if os_type == "linux" and labeltype == "gpt":
                cmd = params.get("guest_part_cmd")
                if cmd:
                    session.cmd(cmd % disk, timeout=360)
            if params.get("need_reboot") == "yes":
                session = vm.reboot(session=session)
            if params.get("need_rescan") == "yes":
                drive.rescan_disks(session)

            # We need extend disk in monitor first then extend it in guest
            if float(ratio) > 1.0:
                error_context.context(
                    "Extend disk to %s in guest" % block_size, test.log.info
                )
                if os_type == "windows":
                    max_block_size = int(params["max_block_size"])
                    if int(block_size) >= max_block_size:
                        test.cancel(
                            "Cancel the test for more than maximum %dB disk."
                            % max_block_size
                        )
                    drive.extend_volume(session, mpoint)
                else:
                    utils_disk.resize_partition_linux(
                        session, partition, str(block_size)
                    )
                    utils_disk.resize_filesystem_linux(
                        session, partition, utils_disk.SIZE_AVAILABLE
                    )
            global current_size
            current_size = 0
            steps = params.get_numeric("verify_disk_size_steps", 1)
            if not wait.wait_for(
                lambda: verify_disk_size(session, os_type, disk),
                20,
                0,
                steps,
                "Block Resizing",
            ):
                test.fail(
                    "Block size get from guest is not same as expected.\n"
                    "Reported: %s\nExpect: %s\n" % (current_size, block_size)
                )
            session = vm.reboot(session=session)

            if os_type == "linux":
                # After guest reboot, reget the disk letter, if it changed, replace
                # variables, i.e 'mpoint', 'partition', 'disk' and 'md5_filename'
                new_disk = utils_misc.get_linux_drive_path(session, disk_serial)
                new_disk = re.search(r"([svh]d\w+)", new_disk, re.M).group(0)
                if new_disk != disk:
                    mpoint = mpoint.replace(disk, new_disk)
                    partition = partition.replace(disk, new_disk)
                    disk = new_disk
                    if params.get("md5_test") == "yes":
                        md5_filename = mpoint + junction + md5_file
                    session.cmd("mkdir -p %s" % mpoint)

                if not utils_disk.is_mount(
                    partition, dst=mpoint, fstype=fstype, session=session
                ):
                    res = utils_disk.mount(
                        partition, mpoint, fstype=fstype, session=session
                    )
                    if not res:
                        test.fail("Mounting data disk was failed! ")

            if params.get("iozone_test") == "yes":
                iozone_timeout = params.get_numeric("iozone_timeout", 1800, float)
                iozone_cmd_options = params.get("iozone_option") % mpoint
                io_test = generate_instance(params, vm, "iozone")
                try:
                    io_test.run(iozone_cmd_options, iozone_timeout)
                finally:
                    io_test.clean()

            # Verify md5
            if params.get("md5_test") == "yes":
                new_md5 = get_md5_of_file(md5_filename)
                test.assertTrue(new_md5 == md5, "Unmatched md5: %s" % new_md5)

        session.close()
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
