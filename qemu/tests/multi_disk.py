"""
multi_disk test for Avocado framework.

:copyright: 2011-2016 Red Hat Inc.
"""
import logging
import re
import random
import string

from avocado.core import exceptions
from autotest.client.shared import utils

from virttest import error_context
from virttest import qemu_qtree
from virttest import env_process
from virttest import utils_misc

_RE_RANGE1 = re.compile(r'range\([ ]*([-]?\d+|n).*\)')
_RE_RANGE2 = re.compile(r',[ ]*([-]?\d+|n)')
_RE_BLANKS = re.compile(r'^([ ]*)')


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
    if 'n' in out:
        if n is None:
            # Don't know what to substitute, return the original
            return buf
        else:
            # Doesn't cover all cases and also it works it's way...
            n = int(n)
            if out[0] == 'n':
                out[0] = int(n)
            if len(out) > 1 and out[1] == 'n':
                out[1] = int(out[0]) + n
            if len(out) > 2 and out[2] == 'n':
                out[2] = (int(out[1]) - int(out[0])) / n
            if len(out) > 3 and out[3] == 'n':
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
    Test multi disk support of guest, this case will:
    1) Create disks image in configuration file.
    2) Start the guest with those disks.
    3) Checks qtree vs. test params. (Optional)
    4) Format those disks in guest(including partition create/format/mount).
    5) Get disks dev filenames.
    6) Copy file into / out of those disks.
    7) Compare the original file and the copied file using md5 or fc comand.
    8) Umount those disks.
    9) Repeat steps 4-8 if needed.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    def _add_param(name, value):
        """ Converts name+value to stg_params string """
        if value:
            value = re.sub(' ', '\\ ', value)
            return " %s:%s " % (name, value)
        else:
            return ''

    def _do_post_cmd(session):
        cmd = params.get("post_cmd")
        if cmd:
            session.cmd_status_output(cmd)
        session.close()

    ostype = params.get("os_type")

    def _get_disk_index(session, image_size, black_list, re_str):
        """
        Get disks ID list in guest. For linux guest, it's disk
        kname; for windows guest, it's disk index which shows in
        'diskpart list disk'
        """
        list_disk_cmd = params.get("list_disk_cmd")
        disks = session.cmd_output(list_disk_cmd, timeout=480)

        # Preprocessing
        if ostype == "windows":
            size_type = image_size[-1] + "B"
            disk_size = ""
            if size_type == "MB":
                disk_size = image_size[:-1] + " MB"
            elif size_type == "GB" and int(image_size[:-1]) < 8:
                disk_size = str(int(image_size[:-1])*1024) + " MB"
            else:
                disk_size = image_size[:-1] + " GB"
        else:
            output = session.cmd("mount")
            re_str = params["re_str"]
            exist_mountpoints = re.findall(r"^/dev/(%s)\d*" % re_str, output,
                                           re.M)
            reg_str = "^%s\d+|^dm-\d+" % re_str
            exist_partitions = re.findall(reg_str, disks, re.M)
            black_list.extend(exist_mountpoints)
            black_list.extend(exist_partitions)

        disks_splitlines = list(disks.splitlines())
        disks_splitlines.pop(0)
        disk_indexs = []
        for disk in disks_splitlines:
            if ostype == "windows":
                regex_str = 'Disk (\d+).*?%s.*?%s' % (disk_size, disk_size)
                o = re.findall(regex_str, disk, re.I | re.M)
                if o:
                    disk_indexs.append(o[0])
            else:
                kname = disk.split()[0]
                if kname not in black_list:
                    disk_indexs.append(kname)

        return disk_indexs

    error_context.context("Parsing test configuration", logging.info)
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
        stg_params += _add_param("drive_index", 'range(2,n)')
    param_matrix = {}

    stg_params = stg_params.split(' ')
    i = 0
    while i < len(stg_params) - 1:
        if not stg_params[i].strip():
            i += 1
            continue
        if stg_params[i][-1] == '\\':
            stg_params[i] = '%s %s' % (stg_params[i][:-1],
                                       stg_params.pop(i + 1))
        i += 1

    rerange = []
    has_name = False
    for i in xrange(len(stg_params)):
        if not stg_params[i].strip():
            continue
        (cmd, parm) = stg_params[i].split(':', 1)
        if cmd == "image_name":
            has_name = True
        if _RE_RANGE1.match(parm):
            parm = _range(parm)
            if parm is False:
                raise exceptions.TestError("Incorrect cfg: stg_params %s looks "
                                           "like range(..) but doesn't contain "
                                           "numbers." % cmd)
            param_matrix[cmd] = parm
            if type(parm) is str:
                # When we know the stg_image_num, substitute it.
                rerange.append(cmd)
                continue
        else:
            # ',' separated list of values
            parm = parm.split(',')
            j = 0
            while j < len(parm) - 1:
                if parm[j][-1] == '\\':
                    parm[j] = '%s,%s' % (parm[j][:-1], parm.pop(j + 1))
                j += 1
            param_matrix[cmd] = parm
        stg_image_num = max(stg_image_num, len(parm))

    stg_image_num = int(params.get('stg_image_num', stg_image_num))
    for cmd in rerange:
        param_matrix[cmd] = _range(param_matrix[cmd], stg_image_num)
    # param_table* are for pretty print of param_matrix
    param_table = []
    param_table_header = ['name']
    if not has_name:
        param_table_header.append('image_name')
    for _ in param_matrix:
        param_table_header.append(_)

    stg_image_name = params.get('stg_image_name', 'images/%s')
    for i in xrange(stg_image_num):
        name = "stg%d" % i
        params['images'] += " %s" % name
        param_table.append([])
        param_table[-1].append(name)
        if not has_name:
            params["image_name_%s" % name] = stg_image_name % name
            param_table[-1].append(params.get("image_name_%s" % name))
        for parm in param_matrix.iteritems():
            params['%s_%s' % (parm[0], name)] = str(parm[1][i % len(parm[1])])
            param_table[-1].append(params.get('%s_%s' % (parm[0], name)))

    if params.get("multi_disk_params_only") == 'yes':
        # Only print the test param_matrix and finish
        logging.info('Newly added disks:\n%s',
                     utils.matrix_to_string(param_table, param_table_header))
        return

    # Always recreate VMs and disks
    error_context.context("Start the guest with new disks", logging.info)
    for vm_name in params.objects("vms"):
        vm_params = params.object_params(vm_name)
        env_process.process_images(env_process.preprocess_image, test,
                                   vm_params)

    error_context.context("Start the guest with those disks", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.create(timeout=max(10, stg_image_num), params=params)
    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))

    n_repeat = int(params.get("n_repeat", "1"))
    file_system = [_.strip() for _ in params.get("file_system").split()]
    cmd_timeout = float(params.get("cmd_timeout", 360))
    re_str = params["re_str"]
    stg_image_size = params.get("stg_image_size")

    have_qtree = True
    out = vm.monitor.human_monitor_cmd("info qtree", debug=False)
    if "unknown command" in str(out):
        have_qtree = False

    if (params.get("check_guest_proc_scsi") == "yes") and have_qtree:
        error_context.context("Verifying qtree vs. test params")
        err = 0
        qtree = qemu_qtree.QtreeContainer()
        qtree.parse_info_qtree(vm.monitor.info('qtree'))
        disks = qemu_qtree.QtreeDisksContainer(qtree.get_nodes())
        (tmp1, tmp2) = disks.parse_info_block(vm.monitor.info_block())
        err += tmp1 + tmp2
        err += disks.generate_params()
        err += disks.check_disk_params(params)
        (tmp1, tmp2, _, _) = disks.check_guests_proc_scsi(
            session.cmd_output('cat /proc/scsi/scsi'))
        err += tmp1 + tmp2

        if err:
            raise exceptions.TestFail("%s errors occurred while verifying"
                                      " qtree vs. params" % err)
        if params.get('multi_disk_only_qtree') == 'yes':
            return

    try:
        cmd = params.get("clean_cmd")
        if cmd:
            session.cmd_status_output(cmd)

        for i in range(n_repeat):
            logging.info("iterations: %s", (i + 1))
            error_context.context("Format those disks in guest", logging.info)
            black_list = []
            disk_indexs = _get_disk_index(session,
                                          stg_image_size, black_list, re_str)

            if len(disk_indexs) < stg_image_num:
                err_msg = "Set disks num: %d" % stg_image_num
                err_msg += ", Get disks num in guest: %d" % len(disk_indexs)
                raise exceptions.TestFail("Fail to list all the volumes, "
                                          "%s" % err_msg)

            # Random select one file system from file_system
            index = random.randint(0, (len(file_system) - 1))
            fs_type = file_system[index].strip()
            all_disks_did = {}
            if ostype == 'linux':
                all_disks_did = utils_misc.get_all_disks_did(session)
            for i in xrange(stg_image_num):
                utils_misc.format_guest_disk(session, disk_indexs[i],
                                             all_disks_did, ostype,
                                             fstype=fs_type)

            # Get disks dev filenames which can be used to get the mount
            # point in the guest
            error_context.context("Get disks dev filenames in guest",
                                  logging.info)
            cmd = params["list_volume_command"]
            s, output = session.cmd_status_output(cmd, timeout=cmd_timeout)
            if s != 0:
                raise exceptions.TestFail("List volume command failed "
                                          "with cmd '%s'.\n Output is: "
                                          "%s\n" % (cmd, output))
            disks = re.findall(re_str, output)
            disks = map(string.strip, disks)
            disks.sort()
            logging.debug("Volume list that meet regular expressions: %s",
                          " ".join(disks))

            images = params.get("images").split()
            if len(disks) < len(images):
                logging.debug("disks: %s , images: %s",
                              len(disks), len(images))
                raise exceptions.TestFail("Fail to list all the volumes!")

            if ostype == "windows":
                black_list = params["black_list"].split()
                # Volume E: should not be in black_list for the test
                black_list.remove("E:")
            disks = set(disks)
            black_list = set(black_list)
            logging.info("No need to check volume '%s'", (disks & black_list))
            disks = disks - black_list

            error_context.context("Cope file into / out of those disks",
                                  logging.info)
            for disk in disks:
                disk = disk.strip()
                error_context.context("Performing I/O on disk: %s..." % disk)
                cmd_list = params["cmd_list"].split()
                for cmd_l in cmd_list:
                    cmd = params.get(cmd_l)
                    if cmd:
                        session.cmd(cmd % disk, timeout=cmd_timeout)

                cmd = params["compare_command"]
                key_word = params["check_result_key_word"]
                output = session.cmd_output(cmd)
                if key_word not in output:
                    raise exceptions.TestFail("Files on guest os root "
                                              "fs and disk differ")

            error_context.context("Umount those disks", logging.info)
            if params.get("umount_command"):
                try:
                    for i in xrange(stg_image_num):
                        if ostype == "linux":
                            partname = disk_indexs[i] + "1"
                            devname = utils_misc.get_path("/dev",
                                                          disk_indexs[i])
                            error_context.context("Unmounting disk: %s..."
                                                  % partname)
                            umount_command = params.get(
                                "umount_command") % (partname, disk_indexs[i])
                            if params["rmpart_cmd"]:
                                rmpart_cmd = params.get("rmpart_cmd") % devname
                                cmd = umount_command + " && " + rmpart_cmd
                            else:
                                cmd = umount_command
                        else:
                            error_context.context("Unmounting disk: disk%s"
                                                  % disk_indexs[i])
                            cmd_header = params.get(
                                "cmd_header") % disk_indexs[i]
                            cmd_footer = params.get(
                                "cmd_footer")
                            umount_command = params.get("umount_command")
                            cmd = ' '.join([cmd_header, umount_command,
                                           cmd_footer])
                        session.cmd(cmd)
                except Exception, err:
                    raise exceptions.TestError("Get error when umounting "
                                               "the disks: %s" % err)

    finally:
        _do_post_cmd(session)
