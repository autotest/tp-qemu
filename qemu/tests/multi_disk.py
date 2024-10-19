"""
multi_disk test for Autotest framework.

:copyright: 2011-2012 Red Hat Inc.
"""

import random
import re
import string

from avocado.utils import astring, process
from virttest import env_process, error_context, qemu_qtree, utils_disk, utils_misc

from provider.storage_benchmark import generate_instance

_RE_RANGE1 = re.compile(r"range\([ ]*([-]?\d+|n).*\)")
_RE_RANGE2 = re.compile(r",[ ]*([-]?\d+|n)")
_RE_BLANKS = re.compile(r"^([ ]*)")


@error_context.context_aware
def _range(buf, n=None):
    """
    Converts 'range(..)' string to range. It supports 1-4 args. It supports
    'n' as correct input, which is substituted to return the correct range.
    range1-3 ... ordinary python range()
    range4   ... multiplies the occurrence of each value
                (range(0,4,1,2) => [0,0,1,1,2,2,3,3])
    :raise ValueError: In case incorrect values are given.
    :return: List of int values. In case it can't substitute 'n'
             it returns the original string.
    """
    out = _RE_RANGE1.match(buf)
    if not out:
        return False
    out = [out.groups()[0]]
    out.extend(_RE_RANGE2.findall(buf))
    if "n" in out:
        if n is None:
            # Don't know what to substitute, return the original
            return buf
        else:
            # Doesn't cover all cases and also it works it's way...
            n = int(n)
            if out[0] == "n":
                out[0] = int(n)
            if len(out) > 1 and out[1] == "n":
                out[1] = int(out[0]) + n
            if len(out) > 2 and out[2] == "n":
                out[2] = (int(out[1]) - int(out[0])) / n
            if len(out) > 3 and out[3] == "n":
                _len = len(range(int(out[0]), int(out[1]), int(out[2])))
                out[3] = n / _len
                if n % _len:
                    out[3] += 1
    for i in range(len(out)):
        out[i] = int(out[i])
    if len(out) == 1:
        out = range(out[0])
    elif len(out) == 2:
        out = range(out[0], out[1])
    elif len(out) == 3:
        out = range(out[0], out[1], out[2])
    elif len(out) == 4:
        # arg4 * range
        _out = []
        for _ in range(out[0], out[1], out[2]):
            _out.extend([_] * out[3])
        out = _out
    else:
        raise ValueError("More than 4 parameters in _range()")
    return out


@error_context.context_aware
def run(test, params, env):
    """
    Test multi disk suport of guest, this case will:
    1) Create disks image in configuration file.
    2) Start the guest with those disks.
    3) Checks qtree vs. test params. (Optional)
    4) Create partition on those disks.
    5) Get disk dev filenames in guest.
    6) Format those disks in guest.
    7) Copy file into / out of those disks.
    8) Compare the original file and the copied file using md5 or fc comand.
    9) Repeat steps 3-5 if needed.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def _add_param(name, value):
        """Converts name+value to stg_params string"""
        if value:
            value = re.sub(" ", "\\ ", value)
            return " %s:%s " % (name, value)
        else:
            return ""

    def _do_post_cmd(session):
        cmd = params.get("post_cmd")
        if cmd:
            session.cmd_status_output(cmd)
        session.close()

    def _get_windows_disks_index(image_size):
        cmd_file = "disk_" + "".join(
            random.sample(string.ascii_letters + string.digits, 4)
        )
        disk_indexs = []
        list_disk_cmd = "echo list disk > " + cmd_file
        list_disk_cmd += " && echo exit >> " + cmd_file
        list_disk_cmd += " && diskpart /s " + cmd_file
        list_disk_cmd += " && del /f " + cmd_file
        all_disks = session.cmd_output(list_disk_cmd, 180)
        size_type = image_size[-1] + "B"
        if size_type == "MB":
            disk_size = image_size[:-1] + " MB"
        elif size_type == "GB" and int(image_size[:-1]) < 8:
            disk_size = str(int(image_size[:-1]) * 1024) + " MB"
        else:
            disk_size = image_size[:-1] + " GB"

        regex_str = r"Disk (\d+).*?%s" % disk_size

        for cmd_file in all_disks.splitlines():
            if cmd_file.startswith("  Disk"):
                o = re.findall(regex_str, cmd_file, re.I | re.M)
                if o:
                    disk_indexs.append(o[0])
        return disk_indexs

    def _get_data_disks():
        if ostype == "windows":
            error_context.context(
                "Get windows disk index that to " "be formatted", test.log.info
            )
            data_disks = _get_windows_disks_index(stg_image_size)
            if len(data_disks) < stg_image_num:
                test.fail(
                    "Fail to list all the volumes" ", %s" % err_msg % len(data_disks)
                )
            if len(data_disks) > drive_letters:
                black_list.extend(utils_misc.get_winutils_vol(session))
                data_disks = random.sample(data_disks, drive_letters - len(black_list))
            error_context.context(
                "Clear readonly for all disks and online " "them in windows guest.",
                test.log.info,
            )
            if not utils_disk.update_windows_disk_attributes(session, data_disks):
                test.fail("Failed to update windows disk attributes.")
        else:
            error_context.context(
                "Get linux disk that to be " "formatted", test.log.info
            )
            data_disks = []
            all_disks = utils_disk.get_linux_disks(session, True)
            for kname, attr in all_disks.items():
                if attr[1] == stg_image_size and attr[2] == "disk":
                    data_disks.append(kname)
            if len(data_disks) < stg_image_num:
                test.fail(
                    "Fail to list all the volumes" ", %s" % err_msg % len(data_disks)
                )
        return sorted(data_disks)

    error_context.context("Parsing test configuration", test.log.info)
    stg_image_num = 0
    stg_params = params.get("stg_params", "")
    # Compatibility
    stg_params += _add_param("image_size", params.get("stg_image_size"))
    stg_params += _add_param("image_format", params.get("stg_image_format"))
    stg_params += _add_param("image_boot", params.get("stg_image_boot", "no"))
    stg_params += _add_param("drive_format", params.get("stg_drive_format"))
    stg_params += _add_param("drive_cache", params.get("stg_drive_cache"))
    if params.get("stg_assign_index") != "no":
        # Assume 0 and 1 are already occupied (hd0 and cdrom)
        stg_params += _add_param("drive_index", "range(2,n)")
    param_matrix = {}

    stg_params = stg_params.split(" ")
    i = 0
    while i < len(stg_params) - 1:
        if not stg_params[i].strip():
            i += 1
            continue
        if stg_params[i][-1] == "\\":
            stg_params[i] = "%s %s" % (stg_params[i][:-1], stg_params.pop(i + 1))
        i += 1

    rerange = []
    has_name = False
    for i in range(len(stg_params)):
        if not stg_params[i].strip():
            continue
        (cmd, parm) = stg_params[i].split(":", 1)
        if cmd == "image_name":
            has_name = True
        if _RE_RANGE1.match(parm):
            parm = _range(parm)
            if parm is False:
                test.error(
                    "Incorrect cfg: stg_params %s looks "
                    "like range(..) but doesn't contain "
                    "numbers." % cmd
                )
            param_matrix[cmd] = parm
            if type(parm) is str:
                # When we know the stg_image_num, substitute it.
                rerange.append(cmd)
                continue
        else:
            # ',' separated list of values
            parm = parm.split(",")
            j = 0
            while j < len(parm) - 1:
                if parm[j][-1] == "\\":
                    parm[j] = "%s,%s" % (parm[j][:-1], parm.pop(j + 1))
                j += 1
            param_matrix[cmd] = parm
        stg_image_num = max(stg_image_num, len(parm))

    stg_image_num = int(params.get("stg_image_num", stg_image_num))
    for cmd in rerange:
        param_matrix[cmd] = _range(param_matrix[cmd], stg_image_num)
    # param_table* are for pretty print of param_matrix
    param_table = []
    param_table_header = ["name"]
    if not has_name:
        param_table_header.append("image_name")
    for _ in param_matrix:
        param_table_header.append(_)

    stg_image_name = params.get("stg_image_name", "images/%s")
    for i in range(stg_image_num):
        name = "stg%d" % i
        params["images"] += " %s" % name
        param_table.append([])
        param_table[-1].append(name)
        if not has_name:
            params["image_name_%s" % name] = stg_image_name % name
            param_table[-1].append(params.get("image_name_%s" % name))
        for parm in param_matrix.items():
            params["%s_%s" % (parm[0], name)] = str(parm[1][i % len(parm[1])])
            param_table[-1].append(params.get("%s_%s" % (parm[0], name)))

    if params.get("multi_disk_params_only") == "yes":
        # Only print the test param_matrix and finish
        test.log.info(
            "Newly added disks:\n%s",
            astring.tabular_output(param_table, param_table_header),
        )
        return

    disk_check_cmd = params.get("disk_check_cmd")
    indirect_image_blacklist = params.get("indirect_image_blacklist").split()
    get_new_disks_cmd = params.get("get_new_disks_cmd")

    if disk_check_cmd:
        new_images = process.run(
            get_new_disks_cmd, ignore_status=True, shell=True
        ).stdout_text
        for black_disk in indirect_image_blacklist[:]:
            if re.search(black_disk, new_images):
                indirect_image_blacklist.remove(black_disk)
        params["indirect_image_blacklist"] = " ".join(indirect_image_blacklist)

    # Always recreate VMs and disks
    error_context.context("Start the guest with new disks", test.log.info)
    for vm_name in params.objects("vms"):
        vm_params = params.object_params(vm_name)
        env_process.process_images(env_process.preprocess_image, test, vm_params)

    error_context.context("Start the guest with those disks", test.log.info)
    vm = env.get_vm(params["main_vm"])
    login_timeout = int(params.get("login_timeout", 360))
    create_timeout = int(params.get("create_timeout", 1800))
    vm.create(timeout=create_timeout, params=params)
    session = vm.wait_for_login(timeout=login_timeout)

    n_repeat = int(params.get("n_repeat", "1"))
    file_system = [_.strip() for _ in params["file_system"].split()]
    cmd_timeout = float(params.get("cmd_timeout", 360))
    black_list = params["black_list"].split()
    drive_letters = int(params.get("drive_letters", "26"))
    stg_image_size = params["stg_image_size"]
    dd_test = params.get("dd_test", "no")
    pre_command = params.get("pre_command", "")
    labeltype = params.get("labeltype", "gpt")
    iozone_target_num = int(params.get("iozone_target_num", "5"))
    iozone_options = params.get("iozone_options")
    iozone_timeout = float(params.get("iozone_timeout", "7200"))

    have_qtree = True
    out = vm.monitor.human_monitor_cmd("info qtree", debug=False)
    if "unknown command" in str(out):
        have_qtree = False

    if (params.get("check_guest_proc_scsi") == "yes") and have_qtree:
        error_context.context("Verifying qtree vs. test params")
        err = 0
        qtree = qemu_qtree.QtreeContainer()
        qtree.parse_info_qtree(vm.monitor.info("qtree"))
        disks = qemu_qtree.QtreeDisksContainer(qtree.get_nodes())
        (tmp1, tmp2) = disks.parse_info_block(vm.monitor.info_block())
        err += tmp1 + tmp2
        err += disks.generate_params()
        err += disks.check_disk_params(params)
        (tmp1, tmp2, _, _) = disks.check_guests_proc_scsi(
            session.cmd_output("cat /proc/scsi/scsi")
        )
        err += tmp1 + tmp2

        if err:
            test.fail("%s errors occurred while verifying qtree vs." " params" % err)
        if params.get("multi_disk_only_qtree") == "yes":
            return
    try:
        err_msg = "Set disks num: %d" % stg_image_num
        err_msg += ", Get disks num in guest: %d"
        ostype = params["os_type"]
        disks = _get_data_disks()
    except Exception:
        _do_post_cmd(session)
        raise
    if iozone_options:
        iozone = generate_instance(params, vm, "iozone")
        random.shuffle(disks)
    try:
        for i in range(n_repeat):
            test.log.info("iterations: %s", (i + 1))
            test.log.info("Get disks: %s", " ".join(disks))
            for n, disk in enumerate(disks):
                error_context.context(
                    "Format disk in guest: '%s'" % disk, test.log.info
                )
                # Random select one file system from file_system
                index = random.randint(0, (len(file_system) - 1))
                fstype = file_system[index].strip()
                partitions = utils_disk.configure_empty_disk(
                    session,
                    disk,
                    stg_image_size,
                    ostype,
                    fstype=fstype,
                    labeltype=labeltype,
                )
                if not partitions:
                    test.fail("Fail to format disks.")
                cmd_list = params["cmd_list"]
                for partition in partitions:
                    orig_partition = partition
                    if "/" not in partition:
                        partition += ":"
                    else:
                        partition = partition.split("/")[-1]
                    error_context.context(
                        "Copy file into / out of partition:" " %s..." % partition,
                        test.log.info,
                    )
                    for cmd_l in cmd_list.split():
                        cmd = params.get(cmd_l)
                        if cmd:
                            session.cmd(cmd % partition, timeout=cmd_timeout)
                    cmd = params["compare_command"]
                    key_word = params["check_result_key_word"]
                    output = session.cmd_output(cmd)
                    if iozone_options and n < iozone_target_num:
                        iozone.run(  # pylint: disable=E0606
                            iozone_options.format(orig_partition),
                            iozone_timeout,
                        )
                    if key_word not in output:
                        test.fail("Files on guest os root fs and disk differ")
                    if dd_test != "no":
                        error_context.context(
                            "dd test on partition: %s..." % partition, test.log.info
                        )
                        status, output = session.cmd_status_output(
                            dd_test % (partition, partition), timeout=cmd_timeout
                        )
                        if status != 0:
                            test.fail("dd test fail: %s" % output)
                    # When multiple SCSI disks are simulated by scsi_debug,
                    # they could be viewed as multiple paths to the same
                    # storage device. So need umount partition before operate
                    # next disk, in order to avoid corrupting the filesystem
                    # (xfs integrity checks error).
                    if ostype == "linux" and "scsi_debug add_host" in pre_command:
                        status, output = session.cmd_status_output(
                            "umount /dev/%s" % partition, timeout=cmd_timeout
                        )
                        if status != 0:
                            test.fail(
                                "Failed to umount partition '%s': %s"
                                % (partition, output)
                            )
            need_reboot = params.get("need_reboot", "no")
            need_shutdown = params.get("need_shutdown", "no")
            if need_reboot == "yes":
                error_context.context("Rebooting guest ...", test.log.info)
                session = vm.reboot(session=session, timeout=login_timeout)
            if need_shutdown == "yes":
                error_context.context("Shutting down guest ...", test.log.info)
                vm.graceful_shutdown(timeout=login_timeout)
                if vm.is_alive():
                    test.fail("Fail to shut down guest.")
                error_context.context("Start the guest again.", test.log.info)
                vm = env.get_vm(params["main_vm"])
                vm.create(timeout=create_timeout, params=params)
                session = vm.wait_for_login(timeout=login_timeout)

            disks = _get_data_disks()
            test.log.info("Get disks again: %s", " ".join(disks))
            error_context.context("Delete partitions in guest.", test.log.info)
            for disk in disks:
                utils_disk.clean_partition(session, disk, ostype)
    finally:
        if iozone_options:
            iozone.clean()
        _do_post_cmd(session)
