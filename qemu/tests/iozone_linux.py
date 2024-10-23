import re

from virttest import error_context, utils_disk, utils_misc

from provider.storage_benchmark import generate_instance


@error_context.context_aware
def run(test, params, env):
    """
    Run IOzone for linux on a linux guest:
    1) Log into a guest.
    2) Execute the IOzone test.
    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def _get_data_disks():
        """Get the data disks by serial or wwn options."""
        disks = {}
        for data_image in params["images"].split()[1:]:
            extra_params = params.get("blk_extra_params_%s" % data_image, "")
            match = re.search(r"(serial|wwn)=(\w+)", extra_params, re.M)
            if match:
                drive_id = match.group(2)
            else:
                continue
            drive_path = utils_misc.get_linux_drive_path(session, drive_id)
            if not drive_path:
                test.error("Failed to get '%s' drive path" % data_image)
            disks[drive_path[5:]] = data_image
        return disks

    def _get_mounted_points(did, disks, mount_info):
        """Get the mounted points."""
        points = []
        for id in re.finditer(r"(%s\d+)" % did, " ".join(disks)):
            s = re.search(r"/dev/%s\s+(\S+)\s+" % id.group(1), mount_info, re.M)
            if s:
                points.append(s.group(1))
        return points

    def _wait_for_procs_done(timeout=1800):
        """Wait all the processes are done."""
        if not utils_misc.wait_for(
            lambda: "iozone" not in session.cmd_output("pgrep -xl iozone"),
            timeout,
            step=3.0,
        ):
            test.error("Not all iozone processes done in %s sec." % timeout)

    iozone_test_dir = params.get("iozone_test_dir", "/home")
    iozone_cmd_options = params["iozone_cmd_options"]
    iozone_timeout = float(params.get("iozone_timeout", 1800))
    n_partitions = params.get("partitions_num", 1)
    fstype = params.get("fstype", "xfs")
    labeltype = params.get("labeltype", utils_disk.PARTITION_TABLE_TYPE_GPT)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=float(params.get("login_timeout", 360)))
    _wait_for_procs_done()
    error_context.context("Running IOzone command on guest.")
    iozone = generate_instance(params, vm, "iozone")
    try:
        dids = _get_data_disks()
        if dids:
            mount_info = session.cmd_output_safe("cat /proc/mounts | grep '/dev/'")
            disks = utils_disk.get_linux_disks(session, True)
            for did, image_name in dids.items():
                size = params.get("image_size_%s" % image_name)
                start = params.get("image_start_%s" % image_name, "0M")
                mounted_points = _get_mounted_points(did, disks, mount_info)
                if not mounted_points:
                    mounted_points = utils_disk.configure_empty_linux_disk(
                        session, did, size, start, n_partitions, fstype, labeltype
                    )
                for mounted_point in mounted_points:
                    iozone.run(iozone_cmd_options % mounted_point, iozone_timeout)
                utils_disk.clean_partition_linux(session, did)
        else:
            iozone.run(iozone_cmd_options % iozone_test_dir, iozone_timeout)
    finally:
        if params.get("sub_test_shutdown_vm", "no") == "no":
            iozone.clean()
        session.close()
