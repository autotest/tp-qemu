"""
KVM cdrom test
:author: Amos Kong <akong@redhat.com>
:author: Lucas Meneghel Rodrigues <lmr@redhat.com>
:author: Lukas Doktor <ldoktor@redhat.com>
:author: Jiri Zupka <jzupka@redhat.com>
:copyright: 2011 Red Hat, Inc.
"""

import os
import random
import re
import sys
import tempfile
import time

import aexpect
import six
from avocado.utils import process
from virttest import (
    data_dir,
    env_process,
    error_context,
    gluster,
    qemu_migration,
    utils_misc,
    utils_test,
)
from virttest.qemu_capabilities import Flags
from virttest.utils_test.qemu import migration


@error_context.context_aware
def run(test, params, env):
    """
    KVM cdrom test:

    1) Boot up a VM, with one iso image (optional).
    2) Check if VM identifies correctly the iso file.
    3) Verifies that device is unlocked <300s after boot (optional, if
       cdrom_test_autounlock is set).
    4) Eject cdrom using monitor.
    5) Change cdrom image with another iso several times.
    5) Test tray reporting function (optional, if cdrom_test_tray_status is set)
    6) Try to format cdrom and check the return string.
    7) Mount cdrom device.
    8) Copy file from cdrom and compare files.
    9) Umount and mount cdrom in guest for several times.
    10) Check if the cdrom lock works well when iso file is not inserted.
    11) Reboot vm after vm resume from s3/s4.
        Note: This case requires a qemu cli without setting file property
        for -drive option, and will be separated to a different cfg item.

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.

    :param cfg: workaround_eject_time - Some versions of qemu are unable to
                                        eject CDROM directly after insert
    :param cfg: cdrom_test_autounlock - Test whether guest OS unlocks cdrom
                                        after boot (<300s after VM is booted)
    :param cfg: cdrom_test_tray_status - Test tray reporting (eject and insert
                                         CD couple of times in guest).
    :param cfg: cdrom_test_locked -     Test whether cdrom tray lock function
                                        work well in guest.
    :param cfg: cdrom_test_eject -      Test whether cdrom works well after
                                        several times of eject action.
    :param cfg: cdrom_test_file_operation - Test file operation for cdrom,
                                            such as mount/umount, reading files
                                            on cdrom.

    @warning: Check dmesg for block device failures
    """
    # Some versions of qemu are unable to eject CDROM directly after insert
    workaround_eject_time = float(params.get("workaround_eject_time", 0))

    login_timeout = int(params.get("login_timeout", 360))
    cdrom_prepare_timeout = int(params.get("cdrom_preapre_timeout", 360))

    def generate_serial_num():
        length = int(params.get("length", "10"))
        id_leng = random.randint(6, length)
        ignore_str = ",!\"#$%&'()*+./:;<=>?@[\\]^`{|}~"
        return utils_misc.generate_random_string(id_leng, ignore_str)

    def list_guest_cdroms(session):
        """
        Get cdrom lists from guest os;

        :param session: ShellSession object;
        :param params: test params dict;
        :return: list of cdroms;
        :rtype: list
        """
        list_cdrom_cmd = "wmic cdrom get Drive"
        filter_cdrom_re = r"\w:"
        if params["os_type"] != "windows":
            list_cdrom_cmd = "ls /dev/cdrom*"
            filter_cdrom_re = r"/dev/cdrom-\w+|/dev/cdrom\d*"
        output = session.cmd_output(list_cdrom_cmd)
        cdroms = re.findall(filter_cdrom_re, output)
        cdroms.sort()
        return cdroms

    def get_cdrom_mount_point(session, drive_letter, params):
        """
        Get default cdrom mount point;
        """
        mount_point = "/mnt"
        if params["os_type"] == "windows":
            cmd = "wmic volume where DriveLetter='%s' " % drive_letter
            cmd += "get DeviceID | more +1"
            mount_point = session.cmd_output(cmd).strip()
        return mount_point

    @error_context.context_aware
    def create_iso_image(params, name, prepare=True, file_size=None):
        """
        Creates 'new' iso image with one file on it

        :param params: parameters for test
        :param name: name of new iso image file
        :param preapre: if True then it prepare cd images.
        :param file_size: Size of iso image in MB

        :return: path to new iso image file.
        """
        error_context.context("Creating test iso image '%s'" % name, test.log.info)
        cdrom_cd = params["target_cdrom"]
        cdrom_cd = params[cdrom_cd]
        if not os.path.isabs(cdrom_cd):
            cdrom_cd = utils_misc.get_path(data_dir.get_data_dir(), cdrom_cd)
        iso_image_dir = os.path.dirname(cdrom_cd)
        if file_size is None:
            file_size = 10
        g_mount_point = tempfile.mkdtemp("gluster")
        image_params = params.object_params(name)
        if image_params.get("enable_gluster") == "yes":
            if params.get("gluster_server"):
                gluster_server = params.get("gluster_server")
            else:
                gluster_server = "localhost"
            volume_name = params["gluster_volume_name"]
            g_mount_link = "%s:/%s" % (gluster_server, volume_name)
            mount_cmd = "mount -t glusterfs %s %s" % (g_mount_link, g_mount_point)
            process.system(mount_cmd, timeout=60)
            file_name = os.path.join(g_mount_point, "%s.iso" % name)
        else:
            file_name = utils_misc.get_path(iso_image_dir, "%s.iso" % name)
        if prepare:
            cmd = "dd if=/dev/urandom of=%s bs=1M count=%d"
            process.run(cmd % (name, file_size))
            process.run("mkisofs -o %s %s" % (file_name, name))
            process.run("rm -rf %s" % (name))
        if image_params.get("enable_gluster") == "yes":
            gluster_uri = gluster.create_gluster_uri(image_params)
            file_name = "%s%s.iso" % (gluster_uri, name)
            try:
                umount_cmd = "umount %s" % g_mount_point
                process.system(umount_cmd, timeout=60)
                os.rmdir(g_mount_point)
            except Exception as err:
                msg = "Fail to clean up %s" % g_mount_point
                msg += "Error message %s" % err
                test.log.warning(msg)
        return file_name

    def cleanup_cdrom(path):
        """Removes created iso image"""
        if path:
            error_context.context(
                "Cleaning up temp iso image '%s'" % path, test.log.info
            )
            if "gluster" in path:
                g_mount_point = tempfile.mkdtemp("gluster")
                g_server, v_name, f_name = path.split("/")[-3:]
                if ":" in g_server:
                    g_server = g_server.split(":")[0]
                g_mount_link = "%s:/%s" % (g_server, v_name)
                mount_cmd = "mount -t glusterfs %s %s" % (g_mount_link, g_mount_point)
                process.system(mount_cmd, timeout=60)
                path = os.path.join(g_mount_point, f_name)
            try:
                test.log.debug("Remove the file with os.remove().")
                os.remove("%s" % path)
            except OSError:
                test.log.warning("Fail to delete %s", path)
            if "gluster" in path:
                try:
                    umount_cmd = "umount %s" % g_mount_point
                    process.system(umount_cmd, timeout=60)
                    os.rmdir(g_mount_point)
                except Exception as err:
                    msg = "Fail to clean up %s" % g_mount_point
                    msg += "Error message %s" % err
                    test.log.warning(msg)

    def get_cdrom_file(vm, qemu_cdrom_device):
        """
        :param vm: VM object
        :param qemu_cdrom_device: qemu monitor device
        :return: file associated with $qemu_cdrom_device device
        """
        blocks = vm.monitor.info("block")
        enable_blockdev = vm.check_capability(Flags.BLOCKDEV)
        cdfile = None
        if isinstance(blocks, six.string_types):
            tmp_re_str = r"%s: .*file=(\S*) " % qemu_cdrom_device
            file_list = re.findall(tmp_re_str, blocks)
            if file_list:
                cdfile = file_list[0]
            else:
                # try to deal with new qemu
                tmp_re_str = r"%s: (\S*) \(.*\)" % qemu_cdrom_device
                file_list = re.findall(tmp_re_str, blocks)
                if file_list:
                    cdfile = file_list[0]
        else:
            for block in blocks:
                if (
                    enable_blockdev
                    and block["qdev"] == vm.devices.get_qdev_by_drive(qemu_cdrom_device)
                    or (not enable_blockdev and block["device"] == qemu_cdrom_device)
                ):
                    try:
                        cdfile = block["inserted"]["file"]
                        break
                    except KeyError:
                        continue
        return cdfile

    def _get_tray_stat_via_monitor(vm, qemu_cdrom_device):
        """
        Get the cdrom tray status via qemu monitor
        """
        is_open, checked = (None, False)
        enable_blockdev = vm.check_capability(Flags.BLOCKDEV)

        blocks = vm.monitor.info("block")
        if isinstance(blocks, six.string_types):
            for block in blocks.splitlines():
                if qemu_cdrom_device in block:
                    if "tray-open=1" in block:
                        is_open, checked = (True, True)
                    elif "tray-open=0" in block:
                        is_open, checked = (False, True)
            # fallback to new qemu
            tmp_block = ""
            for block_new in blocks.splitlines():
                if tmp_block and "Removable device" in block_new:
                    if "tray open" in block_new:
                        is_open, checked = (True, True)
                    elif "tray closed" in block_new:
                        is_open, checked = (False, True)
                if qemu_cdrom_device in block_new:
                    tmp_block = block_new
                else:
                    tmp_block = ""
        else:
            for block in blocks:
                if (
                    enable_blockdev
                    and block["qdev"] == vm.devices.get_qdev_by_drive(qemu_cdrom_device)
                    or (not enable_blockdev and block["device"] == qemu_cdrom_device)
                ):
                    key = list(
                        filter(lambda x: re.match(r"tray.*open", x), block.keys())
                    )
                    # compatible rhel6 and rhel7 diff qmp output
                    if not key:
                        break
                    is_open, checked = (block[key[0]], True)
        return (is_open, checked)

    def is_tray_opened(vm, qemu_cdrom_device, mode="monitor", dev_name="/dev/sr0"):
        """
        Checks whether the tray is opend

        :param vm: VM object
        :param qemu_cdrom_device: cdrom image file name.
        :param mode: tray status checking mode, now support:
                     "monitor": get tray status from monitor.
                     "session": get tray status from guest os.
                     "mixed": get tray status first, if failed, try to
                              get the status in guest os again.
        :param dev_name: cdrom device name in guest os.

        :return: True if cdrom tray is open, otherwise False.
                 None if failed to get the tray status.
        """
        is_open, checked = (None, False)

        if mode in ["monitor", "mixed"]:
            is_open, checked = _get_tray_stat_via_monitor(vm, qemu_cdrom_device)

        if (mode in ["session", "mixed"]) and not checked:
            session = vm.wait_for_login(timeout=login_timeout)
            tray_cmd = params["tray_check_cmd"] % dev_name
            o = session.cmd_output(tray_cmd)
            if "cdrom is open" in o:
                is_open, checked = (True, True)
            else:
                is_open, checked = (False, True)
        if checked:
            return is_open
        return None

    @error_context.context_aware
    def check_cdrom_lock(vm, cdrom):
        """
        Checks whether the cdrom is locked

        :param vm: VM object
        :param cdrom: cdrom object

        :return: Cdrom state if locked return True
        """
        error_context.context("Check cdrom state of locing.")
        blocks = vm.monitor.info("block")
        if isinstance(blocks, six.string_types):
            for block in blocks.splitlines():
                if cdrom in block:
                    if "locked=1" in block:
                        return True
                    elif "locked=0" in block:
                        return False
            # deal with new qemu
            lock_str_new = "locked"
            no_lock_str = "not locked"
            tmp_block = ""
            for block_new in blocks.splitlines():
                if tmp_block and "Removable device" in block_new:
                    if no_lock_str in block_new:
                        return False
                    elif lock_str_new in block_new:
                        return True
                if cdrom in block_new:
                    tmp_block = block_new
                else:
                    tmp_block = ""
        else:
            for block in blocks:
                if block["device"] == cdrom and "locked" in block.keys():
                    return block["locked"]
        return None

    @error_context.context_aware
    def get_device(vm, dev_file_path):
        """
        Get vm device class from device path.

        :param vm: VM object.
        :param dev_file_path: Device file path.
        :return: device object
        """
        error_context.context("Get cdrom device object")
        device = vm.get_block({"file": dev_file_path})
        if not device:
            device = vm.get_block({"backing_file": dev_file_path})
            if not device:
                test.fail("Could not find a valid cdrom device")
        return device

    def get_match_cdrom(vm, session, serial_num):
        """
        Find the cdrom in guest which is corresponding with the CML
        according to the serial number.

        :param session: VM session.
        :param serial num: serial number of the cdrom.
        :return match_cdrom: the cdrom in guest which is corresponding
                             with the CML according to the serial number.
        """
        error_context.context("Get matching cdrom in guest", test.log.info)
        show_serial_num = "ls -l /dev/disk/by-id"
        serial_num_output = session.cmd_output(show_serial_num)
        if serial_num_output:
            serial_cdrom = ""
            for line in serial_num_output.splitlines():
                if serial_num in line:
                    serial_cdrom = line.split(" ")[-1].split("/")[-1]
                    break
            if not serial_cdrom:
                qtree_info = vm.monitor.info("qtree")
                test.fail(
                    "Could not find the device whose "
                    "serial number %s is same in Qemu"
                    " CML.\n Qtree info: %s" % (serial_num, qtree_info)
                )

        show_cdrom_cmd = "ls -l /dev/cdrom*"
        dev_cdrom_output = session.cmd_output(show_cdrom_cmd)
        if dev_cdrom_output:
            for line in dev_cdrom_output.splitlines():
                if utils_misc.find_substring(str(line), str(serial_cdrom)):
                    match_cdrom = line.split(" ")[-3]
                    return match_cdrom
            test.fail(
                "Could not find the corresponding cdrom"
                "in guest which is same in Qemu CML."
            )

    def get_testing_cdrom_device(vm, session, cdrom_dev_list, serial_num=None):
        """
        Get the testing cdrom used for eject
        :param session: VM session
        :param cdrom_dev_list: cdrom_dev_list
        """
        try:
            if params["os_type"] == "windows":
                winutil_drive = utils_misc.get_winutils_vol(session)
                winutil_drive = "%s:" % winutil_drive
                cdrom_dev_list.remove(winutil_drive)
                testing_cdrom_device = cdrom_dev_list[-1]
            else:
                testing_cdrom_device = get_match_cdrom(vm, session, serial_num)
        except IndexError:
            test.fail("Could not find the testing cdrom device")

        return testing_cdrom_device

    def disk_copy(vm, src_path, dst_path, copy_timeout=None, dsize=None):
        """
        Start disk load. Cyclic copy from src_path to dst_path.

        :param vm: VM where to find a disk.
        :param src_path: Source of data
        :param dst_path: Path to destination
        :param copy_timeout: Timeout for copy
        :param dsize: Size of data block which is periodical copied.
        """
        if copy_timeout is None:
            copy_timeout = 120
        session = vm.wait_for_login(timeout=login_timeout)
        copy_file_cmd = "nohup cp %s %s 2> /dev/null &" % (src_path, dst_path)
        get_pid_cmd = "echo $!"
        if params["os_type"] == "windows":
            copy_file_cmd = "start cmd /c copy /y %s %s" % (src_path, dst_path)
            get_pid_cmd = "wmic process where name='cmd.exe' get ProcessID"
        session.cmd(copy_file_cmd, timeout=copy_timeout)
        pid = re.findall(r"\d+", session.cmd_output(get_pid_cmd))[-1]
        return pid

    def get_empty_cdrom_device(vm):
        """
        Get cdrom device when cdrom is not insert.
        """
        device = None
        blocks = vm.monitor.info("block")
        if isinstance(blocks, six.string_types):
            for block in blocks.strip().split("\n"):
                if "not inserted" in block:
                    device = block.split(":")[0]
        else:
            for block in blocks:
                if vm.check_capability(Flags.BLOCKDEV):
                    if "inserted" in block.keys():
                        if block["inserted"]["file"] == "null-co://":
                            device = block["inserted"]["node-name"]
                else:
                    if "inserted" not in block.keys():
                        device = block["device"]
        return device

    def eject_test_via_monitor(
        vm,
        qemu_cdrom_device,
        guest_cdrom_device,
        iso_image_orig,
        iso_image_new,
        max_times,
    ):
        """
        Test cdrom eject function via qemu monitor.
        """
        error_context.context(
            "Eject the iso image in monitor %s times" % max_times, test.log.info
        )
        session = vm.wait_for_login(timeout=login_timeout)
        iso_image = iso_image_orig
        for i in range(1, max_times):
            session.cmd(params["eject_cdrom_cmd"] % guest_cdrom_device)
            vm.eject_cdrom(qemu_cdrom_device)
            time.sleep(2)
            if get_cdrom_file(vm, qemu_cdrom_device) is not None:
                test.fail("Device %s was not ejected" " (round %s)" % (iso_image, i))

            iso_image = iso_image_new
            # On even attempts, try to change the iso image
            if i % 2 == 0:
                iso_image = iso_image_orig
            vm.change_media(qemu_cdrom_device, iso_image)
            if get_cdrom_file(vm, qemu_cdrom_device) != iso_image:
                test.fail(
                    "Could not change iso image %s" " (round %s)" % (iso_image, i)
                )
            time.sleep(workaround_eject_time)

    def check_tray_status_test(
        vm, qemu_cdrom_device, guest_cdrom_device, max_times, iso_image_new
    ):
        """
        Test cdrom tray status reporting function.
        """
        error_context.context("Change cdrom media via monitor", test.log.info)
        iso_image_orig = get_cdrom_file(vm, qemu_cdrom_device)
        if not iso_image_orig:
            test.error("no media in cdrom")
        vm.change_media(qemu_cdrom_device, iso_image_new)
        is_opened = is_tray_opened(vm, qemu_cdrom_device)
        if is_opened:
            test.fail("cdrom tray not opened after change media")
        try:
            error_context.context("Copy test script to guest")
            tray_check_src = params.get("tray_check_src")
            if tray_check_src:
                tray_check_src = os.path.join(
                    data_dir.get_deps_dir(), "cdrom", tray_check_src
                )
                vm.copy_files_to(tray_check_src, params["tmp_dir"])

            if is_tray_opened(vm, qemu_cdrom_device) is None:
                test.log.warning("Tray status reporting is not supported by qemu!")
                test.log.warning("cdrom_test_tray_status test is skipped...")
                return

            error_context.context(
                "Eject the cdrom in guest %s times" % max_times, test.log.info
            )
            session = vm.wait_for_login(timeout=login_timeout)
            for i in range(1, max_times):
                session.cmd(params["eject_cdrom_cmd"] % guest_cdrom_device)
                if not is_tray_opened(vm, qemu_cdrom_device):
                    test.fail(
                        "Monitor reports tray closed" " when ejecting (round %s)" % i
                    )

                cmd = params["close_cdrom_cmd"] % guest_cdrom_device
                session.cmd(cmd)
                if is_tray_opened(vm, qemu_cdrom_device):
                    test.fail(
                        "Monitor reports tray opened when close"
                        " cdrom in guest (round %s)" % i
                    )
                time.sleep(workaround_eject_time)
        finally:
            vm.change_media(qemu_cdrom_device, iso_image_orig)

    def check_tray_locked_test(vm, qemu_cdrom_device, guest_cdrom_device):
        """
        Test cdrom tray locked function.
        """
        error_context.context(
            "Check cdrom tray status after cdrom is locked", test.log.info
        )
        session = vm.wait_for_login(timeout=login_timeout)
        tmp_is_trap_open = is_tray_opened(
            vm, qemu_cdrom_device, mode="mixed", dev_name=guest_cdrom_device
        )
        if tmp_is_trap_open is None:
            test.log.warning("Tray status reporting is not supported by qemu!")
            test.log.warning("cdrom_test_locked test is skipped...")
            return

        eject_failed = False
        eject_failed_msg = "Tray should be closed even in locked status"
        session.cmd(params["eject_cdrom_cmd"] % guest_cdrom_device)
        tmp_is_trap_open = is_tray_opened(
            vm, qemu_cdrom_device, mode="mixed", dev_name=guest_cdrom_device
        )
        if not tmp_is_trap_open:
            test.fail("Tray should not in closed status")
        session.cmd(params["lock_cdrom_cmd"] % guest_cdrom_device)
        try:
            session.cmd(params["close_cdrom_cmd"] % guest_cdrom_device)
        except aexpect.ShellCmdError as e:
            eject_failed = True
            eject_failed_msg += ", eject command failed: %s" % str(e)

        tmp_is_trap_open = is_tray_opened(
            vm, qemu_cdrom_device, mode="mixed", dev_name=guest_cdrom_device
        )
        if eject_failed or tmp_is_trap_open:
            test.fail(eject_failed_msg)
        session.cmd(params["unlock_cdrom_cmd"] % guest_cdrom_device)
        session.cmd(params["close_cdrom_cmd"] % guest_cdrom_device)

    def file_operation_test(session, guest_cdrom_device, max_times):
        """
        Cdrom file operation test.
        """
        filename = "new"
        mount_point = get_cdrom_mount_point(session, guest_cdrom_device, params)
        mount_cmd = params["mount_cdrom_cmd"] % (guest_cdrom_device, mount_point)
        umount_cmd = params["umount_cdrom_cmd"] % guest_cdrom_device
        src_file = params["src_file"] % (mount_point, filename)
        dst_file = params["dst_file"] % filename
        copy_file_cmd = params["copy_file_cmd"] % (mount_point, filename)
        remove_file_cmd = params["remove_file_cmd"] % filename
        show_mount_cmd = params["show_mount_cmd"]
        md5sum_cmd = params["md5sum_cmd"]

        if params["os_type"] != "windows":
            error_context.context(
                "Mounting the cdrom under %s" % mount_point, test.log.info
            )
            session.cmd(mount_cmd, timeout=30)
        error_context.context("File copying test", test.log.info)
        session.cmd(copy_file_cmd)
        f1_hash = session.cmd(md5sum_cmd % dst_file).split()[0].strip()
        f2_hash = session.cmd(md5sum_cmd % src_file).split()[0].strip()
        if f1_hash != f2_hash:
            test.fail("On disk and on cdrom files are different, " "md5 mismatch")
        session.cmd(remove_file_cmd)
        error_context.context(
            "Mount/Unmount cdrom for %s times" % max_times, test.log.info
        )
        for _ in range(1, max_times):
            try:
                session.cmd(umount_cmd)
                session.cmd(mount_cmd)
            except aexpect.ShellError as detail:
                test.log.error("Mount/Unmount fail, detail: '%s'", detail)
                test.log.debug(session.cmd(show_mount_cmd))
                raise
        if params["os_type"] != "windows":
            session.cmd("umount %s" % guest_cdrom_device)

    # Test main body start.
    class MiniSubtest(object):
        def __new__(cls, *args, **kargs):
            self = super(MiniSubtest, cls).__new__(cls)
            ret = None
            exc_info = None
            if args is None:
                args = []
            try:
                try:
                    ret = self.test(*args, **kargs)
                except Exception:
                    exc_info = sys.exc_info()
            finally:
                if hasattr(self, "clean"):
                    try:
                        self.clean()
                    except Exception:
                        if exc_info is None:
                            raise
                    if exc_info:
                        six.reraise(exc_info[0], exc_info[1], exc_info[2])
            return ret

    class test_singlehost(MiniSubtest):
        def test(self):
            self.iso_image_orig = create_iso_image(params, "orig")
            self.iso_image_new = create_iso_image(params, "new")
            self.cdrom_dir = os.path.dirname(self.iso_image_new)
            if params.get("not_insert_at_start") == "yes":
                target_cdrom = params["target_cdrom"]
                params[target_cdrom] = ""
            params["start_vm"] = "yes"
            serial_num = generate_serial_num()
            cdrom = params.get("cdroms", "").split()[-1]
            params["drive_serial_%s" % cdrom] = serial_num
            env_process.preprocess_vm(test, params, env, params["main_vm"])
            vm = env.get_vm(params["main_vm"])

            self.session = vm.wait_for_login(timeout=login_timeout)
            pre_cmd = params.get("pre_cmd")
            if pre_cmd:
                self.session.cmd(pre_cmd, timeout=120)
                self.session = vm.reboot()
            iso_image = self.iso_image_orig
            if params["os_type"] != "windows" and params.get("unlock_cdrom_cmd"):
                test.log.debug("Unlock cdrom first")
                unlock_cdrom_cmd = params.get("unlock_cdrom_cmd") % ""
                self.session.cmd(unlock_cdrom_cmd, timeout=120)
            error_context.context("Query cdrom devices in guest")
            cdrom_dev_list = list_guest_cdroms(self.session)
            test.log.debug("cdrom_dev_list: '%s'", cdrom_dev_list)

            if params.get("not_insert_at_start") == "yes":
                error_context.context("Locked without media present", test.log.info)
                # XXX: The device got from monitor might not match with the guest
                # defice if there are multiple cdrom devices.
                qemu_cdrom_device = get_empty_cdrom_device(vm)
                guest_cdrom_device = get_testing_cdrom_device(
                    vm, self.session, cdrom_dev_list, serial_num
                )
                if vm.check_block_locked(qemu_cdrom_device):
                    test.fail("Device should not be locked just" " after booting up")
                cmd = params["lock_cdrom_cmd"] % guest_cdrom_device
                self.session.cmd(cmd)
                if not vm.check_block_locked(qemu_cdrom_device):
                    test.fail("Device is not locked as expect.")
                return

            error_context.context(
                "Detecting the existence of a cdrom " "(guest OS side)", test.log.info
            )
            cdrom_dev_list = list_guest_cdroms(self.session)
            guest_cdrom_device = get_testing_cdrom_device(
                vm, self.session, cdrom_dev_list, serial_num
            )
            error_context.context(
                "Detecting the existence of a cdrom " "(qemu side)", test.log.info
            )
            qemu_cdrom_device = get_device(vm, iso_image)
            if params["os_type"] != "windows":
                self.session.cmd_output("umount %s" % guest_cdrom_device)
            if params.get("cdrom_test_autounlock") == "yes":
                error_context.context("Trying to unlock the cdrom", test.log.info)
                if not utils_misc.wait_for(
                    lambda: not vm.check_block_locked(qemu_cdrom_device), 300
                ):
                    test.fail(
                        "Device %s could not be" " unlocked" % (qemu_cdrom_device)
                    )

            max_test_times = int(params.get("cdrom_max_test_times", 100))
            if params.get("cdrom_test_eject") == "yes":
                eject_test_via_monitor(
                    vm,
                    qemu_cdrom_device,
                    guest_cdrom_device,
                    self.iso_image_orig,
                    self.iso_image_new,
                    max_test_times,
                )

            if params.get("cdrom_test_tray_status") == "yes":
                check_tray_status_test(
                    vm,
                    qemu_cdrom_device,
                    guest_cdrom_device,
                    max_test_times,
                    self.iso_image_new,
                )

            if params.get("cdrom_test_locked") == "yes":
                check_tray_locked_test(vm, qemu_cdrom_device, guest_cdrom_device)

            error_context.context("Check whether the cdrom is read-only", test.log.info)
            cmd = params["readonly_test_cmd"] % guest_cdrom_device
            try:
                self.session.cmd(cmd)
                test.fail("Attempt to format cdrom %s succeeded" % (guest_cdrom_device))
            except aexpect.ShellError:
                pass

            sub_test = params.get("sub_test")
            if sub_test:
                error_context.context(
                    "Run sub test '%s' before doing file" " operation" % sub_test,
                    test.log.info,
                )
                utils_test.run_virt_sub_test(test, params, env, sub_test)

            if params.get("cdrom_test_file_operation") == "yes":
                file_operation_test(self.session, guest_cdrom_device, max_test_times)

            error_context.context("Cleanup")
            # Return the self.iso_image_orig
            cdfile = get_cdrom_file(vm, qemu_cdrom_device)
            if cdfile != self.iso_image_orig:
                time.sleep(workaround_eject_time)
                self.session.cmd(params["eject_cdrom_cmd"] % guest_cdrom_device)
                vm.eject_cdrom(qemu_cdrom_device)
                if get_cdrom_file(vm, qemu_cdrom_device) is not None:
                    test.fail(
                        "Device %s was not ejected"
                        " in clearup stage" % qemu_cdrom_device
                    )

                vm.change_media(qemu_cdrom_device, self.iso_image_orig)
                if get_cdrom_file(vm, qemu_cdrom_device) != self.iso_image_orig:
                    test.fail("It wasn't possible to change" " cdrom %s" % iso_image)
            post_cmd = params.get("post_cmd")
            if post_cmd:
                self.session.cmd(post_cmd)
            if params.get("guest_suspend_type"):
                self.session = vm.reboot()

        def clean(self):
            self.session.close()
            cleanup_cdrom(self.iso_image_orig)
            cleanup_cdrom(self.iso_image_new)

    class Multihost(MiniSubtest):
        def test(self):
            error_context.context("Preparing migration env and cdroms.", test.log.info)
            mig_protocol = params.get("mig_protocol", "tcp")
            self.mig_type = migration.MultihostMigration
            if mig_protocol == "fd":
                self.mig_type = migration.MultihostMigrationFd
            if mig_protocol == "exec":
                self.mig_type = migration.MultihostMigrationExec
            if "rdma" in mig_protocol:
                self.mig_type = migration.MultihostMigrationRdma

            self.vms = params.get("vms").split(" ")
            self.srchost = params.get("hosts")[0]
            self.dsthost = params.get("hosts")[1]
            self.is_src = params.get("hostid") == self.srchost
            self.mig = self.mig_type(
                test,
                params,
                env,
                False,
            )
            self.cdrom_size = int(params.get("cdrom_size", 10))
            cdrom = params.objects("cdroms")[-1]
            self.serial_num = params.get("drive_serial_%s" % cdrom)

            if self.is_src:
                self.cdrom_orig = create_iso_image(
                    params, "orig", file_size=self.cdrom_size
                )
                self.cdrom_dir = os.path.dirname(self.cdrom_orig)
                vm = env.get_vm(self.vms[0])
                vm.destroy()
                params["start_vm"] = "yes"
                env_process.process(
                    test,
                    params,
                    env,
                    env_process.preprocess_image,
                    env_process.preprocess_vm,
                )
                vm = env.get_vm(self.vms[0])
                vm.wait_for_login(timeout=login_timeout)
            else:
                self.cdrom_orig = create_iso_image(params, "orig", False)
                self.cdrom_dir = os.path.dirname(self.cdrom_orig)

        def clean(self):
            self.mig.cleanup()
            if self.is_src:
                cleanup_cdrom(self.cdrom_orig)

    class test_multihost_locking(Multihost):
        def test(self):
            super(test_multihost_locking, self).test()

            error_context.context("Lock cdrom in VM.", test.log.info)
            # Starts in source
            if self.is_src:
                vm = env.get_vm(params["main_vm"])
                session = vm.wait_for_login(timeout=login_timeout)
                cdrom_dev_list = list_guest_cdroms(session)
                guest_cdrom_device = get_testing_cdrom_device(
                    vm, session, cdrom_dev_list, self.serial_num
                )
                test.log.debug("cdrom_dev_list: %s", cdrom_dev_list)
                device = get_device(vm, self.cdrom_orig)

                session.cmd(params["lock_cdrom_cmd"] % guest_cdrom_device)
                locked = check_cdrom_lock(vm, device)
                if locked:
                    test.log.debug("Cdrom device is successfully locked in VM.")
                else:
                    test.fail("Cdrom device should be locked in VM.")

            self.mig._hosts_barrier(
                self.mig.hosts, self.mig.hosts, "cdrom_dev", cdrom_prepare_timeout
            )

            self.mig.migrate_wait([self.vms[0]], self.srchost, self.dsthost)

            # Starts in dest
            if not self.is_src:
                vm = env.get_vm(params["main_vm"])
                session = vm.wait_for_login(timeout=login_timeout)
                cdrom_dev_list = list_guest_cdroms(session)
                test.log.debug("cdrom_dev_list: %s", cdrom_dev_list)
                device = get_device(vm, self.cdrom_orig)

                locked = check_cdrom_lock(vm, device)
                if locked:
                    test.log.debug(
                        "Cdrom device stayed locked after " "migration in VM."
                    )
                else:
                    test.fail(
                        "Cdrom device should stayed locked" " after migration in VM."
                    )

                error_context.context("Unlock cdrom from VM.", test.log.info)
                cdrom_dev_list = list_guest_cdroms(session)
                guest_cdrom_device = get_testing_cdrom_device(
                    vm, session, cdrom_dev_list, self.serial_num
                )
                session.cmd(params["unlock_cdrom_cmd"] % guest_cdrom_device)
                locked = check_cdrom_lock(vm, device)
                if not locked:
                    test.log.debug("Cdrom device is successfully unlocked" " from VM.")
                else:
                    test.fail("Cdrom device should be unlocked in VM.")

            self.mig.migrate_wait([self.vms[0]], self.dsthost, self.srchost)

            if self.is_src:
                vm = env.get_vm(params["main_vm"])
                locked = check_cdrom_lock(vm, device)
                if not locked:
                    test.log.debug(
                        "Cdrom device stayed unlocked after " "migration in VM."
                    )
                else:
                    test.fail(
                        "Cdrom device should stayed unlocked" " after migration in VM."
                    )

            self.mig._hosts_barrier(
                self.mig.hosts, self.mig.hosts, "Finish_cdrom_test", login_timeout
            )

        def clean(self):
            super(test_multihost_locking, self).clean()

    class test_multihost_ejecting(Multihost):
        def test(self):
            super(test_multihost_ejecting, self).test()

            self.cdrom_new = create_iso_image(params, "new")

            if not self.is_src:
                self.cdrom_new = create_iso_image(params, "new", False)
                self.cdrom_dir = os.path.dirname(self.cdrom_new)
                params["cdrom_cd1"] = params.get("cdrom_cd1_host2")

            if self.is_src:
                vm = env.get_vm(self.vms[0])
                session = vm.wait_for_login(timeout=login_timeout)
                cdrom_dev_list = list_guest_cdroms(session)
                test.log.debug("cdrom_dev_list: %s", cdrom_dev_list)
                device = get_device(vm, self.cdrom_orig)
                cdrom = get_testing_cdrom_device(
                    vm, session, cdrom_dev_list, self.serial_num
                )

                error_context.context("Eject cdrom.", test.log.info)
                session.cmd(params["eject_cdrom_cmd"] % cdrom)
                vm.eject_cdrom(device)
                time.sleep(2)
                if get_cdrom_file(vm, device) is not None:
                    test.fail("Device %s was not ejected" % (cdrom))

                cdrom = self.cdrom_new

                error_context.context("Change cdrom.", test.log.info)
                vm.change_media(device, cdrom)
                if get_cdrom_file(vm, device) != cdrom:
                    test.fail("It wasn't possible to change " "cdrom %s" % (cdrom))
                time.sleep(workaround_eject_time)

            self.mig._hosts_barrier(
                self.mig.hosts, self.mig.hosts, "cdrom_dev", cdrom_prepare_timeout
            )

            self.mig.migrate_wait([self.vms[0]], self.srchost, self.dsthost)

            if not self.is_src:
                vm = env.get_vm(self.vms[0])
                vm.reboot()

        def clean(self):
            if self.is_src:
                cleanup_cdrom(self.cdrom_new)
            super(test_multihost_ejecting, self).clean()

    class test_multihost_copy(Multihost):
        def test(self):
            from autotest.client.shared.syncdata import SyncData

            super(test_multihost_copy, self).test()
            copy_timeout = int(params.get("copy_timeout", 480))
            checksum_timeout = int(params.get("checksum_timeout", 180))

            pid = None
            sync_id = {"src": self.srchost, "dst": self.dsthost, "type": "file_trasfer"}
            filename = "orig"
            remove_file_cmd = params["remove_file_cmd"] % filename
            dst_file = params["dst_file"] % filename

            if self.is_src:  # Starts in source
                vm = env.get_vm(self.vms[0])
                qemu_migration.set_speed(vm, "1G")
                session = vm.wait_for_login(timeout=login_timeout)
                cdrom_dev_list = list_guest_cdroms(session)
                test.log.debug("cdrom_dev_list: %s", cdrom_dev_list)
                cdrom = get_testing_cdrom_device(
                    vm, session, cdrom_dev_list, self.serial_num
                )
                mount_point = get_cdrom_mount_point(session, cdrom, params)
                mount_cmd = params["mount_cdrom_cmd"] % (cdrom, mount_point)
                src_file = params["src_file"] % (mount_point, filename)
                copy_file_cmd = params["copy_file_cmd"] % (mount_point, filename)
                if params["os_type"] != "windows":
                    error_context.context("Mount and copy data", test.log.info)
                    session.cmd(mount_cmd, timeout=30)

                error_context.context("File copying test", test.log.info)
                session.cmd(remove_file_cmd)
                session.cmd(copy_file_cmd)

                pid = disk_copy(vm, src_file, dst_file, copy_timeout)

            sync = SyncData(
                self.mig.master_id(),
                self.mig.hostid,
                self.mig.hosts,
                sync_id,
                self.mig.sync_server,
            )

            pid = sync.sync(pid, timeout=cdrom_prepare_timeout)[self.srchost]

            self.mig.migrate_wait([self.vms[0]], self.srchost, self.dsthost)

            if not self.is_src:  # Starts in source
                vm = env.get_vm(self.vms[0])
                session = vm.wait_for_login(timeout=login_timeout)
                error_context.context("Wait for copy finishing.", test.log.info)
                cdrom_dev_list = list_guest_cdroms(session)
                cdrom = get_testing_cdrom_device(
                    vm, session, cdrom_dev_list, self.serial_num
                )
                mount_point = get_cdrom_mount_point(session, cdrom, params)
                mount_cmd = params["mount_cdrom_cmd"] % (cdrom, mount_point)
                src_file = params["src_file"] % (mount_point, filename)
                md5sum_cmd = params["md5sum_cmd"]

                def is_copy_done():
                    if params["os_type"] == "windows":
                        cmd = 'tasklist /FI "PID eq %s"' % pid
                    else:
                        cmd = "ps -p %s" % pid
                    return session.cmd_status(cmd) != 0

                if not utils_misc.wait_for(is_copy_done, timeout=copy_timeout):
                    test.fail("Wait for file copy finish timeout")

                error_context.context(
                    "Compare file on disk and on cdrom", test.log.info
                )
                f1_hash = session.cmd(
                    md5sum_cmd % dst_file, timeout=checksum_timeout
                ).split()[0]
                f2_hash = session.cmd(
                    md5sum_cmd % src_file, timeout=checksum_timeout
                ).split()[0]
                if f1_hash.strip() != f2_hash.strip():
                    test.fail(
                        "On disk and on cdrom files are" " different, md5 mismatch"
                    )
                session.cmd(remove_file_cmd)

            self.mig._hosts_barrier(
                self.mig.hosts, self.mig.hosts, "Finish_cdrom_test", login_timeout
            )

        def clean(self):
            super(test_multihost_copy, self).clean()

    test_type = params.get("test_type", "test_singlehost")
    if test_type in locals():
        tests_group = locals()[test_type]
        tests_group()
    else:
        test.fail(
            "Test group '%s' is not defined in"
            " migration_with_dst_problem test" % test_type
        )
