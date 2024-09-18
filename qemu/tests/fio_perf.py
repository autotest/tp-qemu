import logging
import os
import re
import threading
import time

import six
from avocado.utils import process
from virttest import (
    data_dir,
    error_context,
    utils_disk,
    utils_misc,
    utils_numeric,
    utils_test,
)

from provider.storage_benchmark import generate_instance

LOG_JOB = logging.getLogger("avocado.test")


def format_result(result, base="12", fbase="2"):
    """
    Format the result to a fixed length string.

    :param result: result need to convert
    :param base: the length of converted string
    :param fbase: the decimal digit for float
    """
    if isinstance(result, six.string_types):
        value = "%" + base + "s"
    elif isinstance(result, int):
        value = "%" + base + "d"
    elif isinstance(result, float):
        value = "%" + base + "." + fbase + "f"
    else:
        raise TypeError(f"unexpected result type: {type(result).__name__}")
    return value % result


def check_disk_status(session, timeout, num):
    """
    Output disk info including disk status

    :param session: VM session
    :param timeout: Timeout in seconds
    :param num: The number of data disks
    """

    disk_status_cmd = "echo list disk > cmd && echo exit >>"
    disk_status_cmd += " cmd && diskpart /s cmd"
    disks = []
    end_time = time.time() + timeout
    while time.time() < end_time:
        disks_str = session.cmd_output_safe(disk_status_cmd)
        LOG_JOB.info("disks_str is %s", disks_str)
        disks = re.findall("Disk %s.*\n" % num, disks_str)
        if not disks:
            continue
        return disks


def get_version(
    session,
    result_file,
    kvm_ver_chk_cmd,
    guest_ver_cmd,
    type,
    driver_format,
    vfsd_ver_chk_cmd,
    timeout,
):
    """
    collect qemu, kernel, virtiofsd version if needed and driver version info
    and write them info results file

    :param session: VM session
    :param results_file: save fio results, host info and other info
    :param guest_ver_cmd: command of getting guest kernel or virtio_win driver version
    :param type: guest type
    :param driver_format: driver format
    :param timeout: Timeout in seconds
    """

    kvm_ver = process.system_output(kvm_ver_chk_cmd, shell=True).decode()
    host_ver = os.uname()[2]

    result_file.write("### kvm-userspace-ver : %s\n" % kvm_ver)
    result_file.write("### kvm_version : %s\n" % host_ver)

    if driver_format != "ide":
        result = session.cmd_output(guest_ver_cmd, timeout)
        if type == "windows":
            guest_ver = re.findall(r".*?(\d{2}\.\d{2}\.\d{3}\.\d{4}).*?", result)
            result_file.write(
                "### guest-kernel-ver :Microsoft Windows [Version %s]\n" % guest_ver[0]
            )
        else:
            result_file.write("### guest-kernel-ver :%s" % result)
    else:
        result_file.write(
            "### guest-kernel-ver : Microsoft Windows " "[Version ide driver format]\n"
        )

    if vfsd_ver_chk_cmd:
        LOG_JOB.info("Check virtiofsd version on host.")
        virtiofsd_ver = process.system_output(vfsd_ver_chk_cmd, shell=True).decode()
        result_file.write("### virtiofsd_version : %s\n" % virtiofsd_ver)


@error_context.context_aware
def run(test, params, env):
    """
    Block performance test with fio
    Steps:
    1) boot up guest with one data disk on specified backend and pin qemu-kvm
       process to the last numa node on host
    2) pin guest vcpu and vhost threads to cpus of last numa node repectively
    3) format data disk and run fio in guest
    4) collect fio results and host info

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    def fio_thread():
        """
        run fio command in guest
        """
        # generate instance with fio
        fio = generate_instance(params, vm, "fio")
        try:
            fio.run(run_fio_options)
        finally:
            fio.clean()

    def clean_tmp_files(session, os_type, guest_result_file, timeout):
        """
        Clean temporary test result file inside guest

        :param session: VM session
        :param os_type: guest typet
        :param guest_result_file: fio result file in guest
        :param timeout: Timeout in seconds
        """
        if os_type == "linux":
            session.cmd("rm -rf %s" % guest_result_file, timeout)
        elif os_type == "windows":
            session.cmd("del /f/s/q %s" % guest_result_file, timeout)

    def _pin_vm_threads(node):
        """
        pin guest vcpu and vhost threads to cpus of a numa node repectively

        :param node: which numa node to pin
        """
        if node:
            if not isinstance(node, utils_misc.NumaNode):
                node = utils_misc.NumaNode(int(node))
            utils_test.qemu.pin_vm_threads(vm, node)

    # login virtual machine
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    login_timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=login_timeout)
    process.system_output("numactl --hardware")
    process.system_output("numactl --show")
    _pin_vm_threads(params.get("numa_node"))

    # get parameter from dictionary
    fio_options = params["fio_options"]
    rw = params["rw"]
    block_size = params["block_size"]
    iodepth = params["iodepth"]
    threads = params["threads"]
    cmd_timeout = int(params.get("cmd_timeout", 1200))
    order_list = params["order_list"]
    driver_format = params.get("drive_format")
    kvm_ver_chk_cmd = params.get("kvm_ver_chk_cmd")
    guest_ver_cmd = params["guest_ver_cmd"]
    pattern = params["pattern"]
    pre_cmd = params["pre_cmd"]
    guest_result_file = params["guest_result_file"]
    format = params.get("format")
    os_type = params.get("os_type", "linux")
    drop_cache = params.get("drop_cache")
    num_disk = params.get("num_disk")
    driver_verifier_query = params.get("driver_verifier_query")
    verifier_clear_cmd = params.get("verifier_clear_cmd")
    vfsd_ver_chk_cmd = params.get("vfsd_ver_chk_cmd")
    delete_test_file = params.get("delete_test_file", "no")

    result_path = utils_misc.get_path(test.resultsdir, "fio_result.RHS")
    result_file = open(result_path, "w")

    # scratch host and windows guest version info
    get_version(
        session,
        result_file,
        kvm_ver_chk_cmd,
        guest_ver_cmd,
        os_type,
        driver_format,
        vfsd_ver_chk_cmd,
        cmd_timeout,
    )

    if os_type == "windows":
        # turn off driver verifier
        o = session.cmd_status_output(driver_verifier_query)
        logging.info(o)
        if ".sys" in o:
            output = session.cmd_status_output(verifier_clear_cmd)
            logging.info(output)
            if ".sys" in output:
                msg = "% does not work correctly" % verifier_clear_cmd
                test.error(msg)
        # online disk
        for num in range(1, int(num_disk) + 1):
            disks = check_disk_status(session, cmd_timeout, num)
            diskstatus = re.findall(r"Disk\s+\d+\s+(\w+).*?\s+\d+", disks[0])[0]
            if diskstatus == "Offline":
                online_disk_cmd = params.get("online_disk_cmd")
                online_disk_run = online_disk_cmd % num
                (s, o) = session.cmd_status_output(online_disk_run, timeout=cmd_timeout)
                if s:
                    test.fail("Failed to online disk: %s" % o)
    for fs in params.objects("filesystems"):
        fs_params = params.object_params(fs)
        fs_target = fs_params.get("fs_target")
        fs_dest = fs_params.get("fs_dest")
        fs_params.get("fs_source_dir")
        error_context.context(
            "Create a destination directory %s " "inside guest." % fs_dest,
            test.log.info,
        )
        utils_misc.make_dirs(fs_dest, session)
        error_context.context(
            "Mount virtiofs target %s to %s inside" " guest." % (fs_target, fs_dest),
            test.log.info,
        )
        if not utils_disk.mount(fs_target, fs_dest, "virtiofs", session=session):
            test.fail("Mount virtiofs target failed.")
    # format disk
    if format == "True":
        session.cmd(pre_cmd, cmd_timeout)

    # get order_list
    order_line = ""
    for order in order_list.split():
        order_line += "%s|" % format_result(order)

    # get result tested by each scenario
    for io_pattern in rw.split():
        result_file.write("Category:%s\n" % io_pattern)
        result_file.write("%s\n" % order_line.rstrip("|"))
        for bs in block_size.split():
            for io_depth in iodepth.split():
                for numjobs in threads.split():
                    line = ""
                    line += "%s|" % format_result(bs[:-1])
                    line += "%s|" % format_result(io_depth)
                    line += "%s|" % format_result(numjobs)
                    file_name = None
                    if format == "True" or params.objects("filesystems"):
                        file_name = io_pattern + "_" + bs + "_" + io_depth
                        run_fio_options = fio_options % (
                            io_pattern,
                            bs,
                            io_depth,
                            file_name,
                            numjobs,
                        )
                    else:
                        run_fio_options = fio_options % (
                            io_pattern,
                            bs,
                            io_depth,
                            numjobs,
                        )

                    test.log.info("run_fio_options are: %s", run_fio_options)
                    if os_type == "linux":
                        (s, o) = session.cmd_status_output(
                            drop_cache, timeout=cmd_timeout
                        )
                        if s:
                            test.fail("Failed to free memory: %s" % o)
                    cpu_file = os.path.join(data_dir.get_tmp_dir(), "cpus")
                    io_exits_b = int(
                        process.system_output("cat /sys/kernel/debug/kvm/exits")
                    )
                    fio_t = threading.Thread(target=fio_thread)
                    fio_t.start()
                    process.system_output("mpstat 1 60 > %s" % cpu_file, shell=True)
                    fio_t.join()
                    if file_name and delete_test_file == "yes":
                        test.log.info("Ready delete: %s", file_name)
                        session.cmd("rm -rf /mnt/%s" % file_name)

                    io_exits_a = int(
                        process.system_output("cat /sys/kernel/debug/kvm/exits")
                    )
                    vm.copy_files_from(guest_result_file, data_dir.get_tmp_dir())
                    fio_result_file = os.path.join(data_dir.get_tmp_dir(), "fio_result")
                    o = process.system_output(
                        "egrep '(read|write)' %s" % fio_result_file
                    ).decode()
                    results = re.findall(pattern, o)
                    o = process.system_output(
                        "egrep 'lat' %s" % fio_result_file
                    ).decode()
                    laten = re.findall(
                        r"\s{5}lat\s\((\wsec)\).*?avg=[\s]?(\d+(?:[\.][\d]+)?).*?", o
                    )
                    bw = float(utils_numeric.normalize_data_size(results[0][1]))
                    iops = float(
                        utils_numeric.normalize_data_size(
                            results[0][0], order_magnitude="B", factor=1000
                        )
                    )
                    if os_type == "linux" and not params.objects("filesystems"):
                        o = process.system_output(
                            "egrep 'util' %s" % fio_result_file
                        ).decode()
                        util = float(re.findall(r".*?util=(\d+(?:[\.][\d]+))%", o)[0])

                    lat = (
                        float(laten[0][1]) / 1000
                        if laten[0][0] == "usec"
                        else float(laten[0][1])
                    )
                    if re.findall("rw", io_pattern):
                        bw = bw + float(
                            utils_numeric.normalize_data_size(results[1][1])
                        )
                        iops = iops + float(
                            utils_numeric.normalize_data_size(
                                results[1][0], order_magnitude="B", factor=1000
                            )
                        )
                        lat1 = (
                            float(laten[1][1]) / 1000
                            if laten[1][0] == "usec"
                            else float(laten[1][1])
                        )
                        lat = lat + lat1

                    ret = process.system_output("tail -n 1 %s" % cpu_file)
                    idle = float(ret.split()[-1])
                    iowait = float(ret.split()[5])
                    cpu = 100 - idle - iowait
                    normal = bw / cpu
                    io_exits = io_exits_a - io_exits_b
                    for result in bw, iops, lat, cpu, normal:
                        line += "%s|" % format_result(result)
                    if os_type == "windows":
                        line += "%s" % format_result(io_exits)
                    if os_type == "linux":
                        if not params.objects("filesystems"):
                            line += "%s|" % format_result(io_exits)
                            line += "%s" % format_result(util)  # pylint: disable=E0606
                        else:
                            line += "%s" % format_result(io_exits)
                    result_file.write("%s\n" % line)

    # del temporary files in guest os
    clean_tmp_files(session, os_type, guest_result_file, cmd_timeout)

    result_file.close()
    for fs in params.objects("filesystems"):
        fs_params = params.object_params(fs)
        fs_target = fs_params.get("fs_target")
        fs_dest = fs_params.get("fs_dest")
        utils_disk.umount(fs_target, fs_dest, "virtiofs", session=session)
        utils_misc.safe_rmdir(fs_dest, session=session)
    session.close()
