import re
import logging
import os
import six

from avocado.utils import process

from virttest import env_process
from virttest import error_context
from virttest import utils_misc
from virttest import data_dir


# This decorator makes the test function aware of context strings
@error_context.context_aware
def run(test, params, env):
    """
    qemu cdrom block size check test.

    1) Boot the guest with empty iso.
    2) Get the cdrom's size in guest.
    3) Attach a small cd iso file to the cdrom.
    4) mount the cdrom in guest and check its block size.
    5) umount and eject cdrom in guest.
    6) Change cdrom media to another file with different size.
    7) Get the cdrom's size in guest again.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

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
        return re.findall(filter_cdrom_re, output)

    def get_cdrom_mount_point(session, os_type="linux", drive_letter=None):
        """
        Get default cdrom mount point;
        """
        mount_point = "/mnt"
        if os_type == "windows":
            cmd = "wmic volume where DriveLetter='%s' " % drive_letter
            cmd += "get DeviceID | more +1"
            mount_point = session.cmd_output(cmd).strip()
        return mount_point

    def get_cdrom_device(vm):
        """
        Get cdrom device when cdrom is not insert.
        """
        device = None
        blocks = vm.monitor.info("block")
        if isinstance(blocks, six.string_types):
            for block in blocks.strip().split('\n'):
                if 'not inserted' in block:
                    device = block.split(':')[0]
        else:
            for block in blocks:
                if 'inserted' not in block.keys():
                    device = block['device']
        return device

    def create_iso_image(params, name, prepare=True, file_size=None):
        """
        Creates 'new' iso image with one file on it

        :param params: parameters for test
        :param name: name of new iso image file. It could be the full path
                     of cdrom.
        :param preapre: if True then it prepare cd images.
        :param file_size: Size of iso image in MB

        :return: path to new iso image file.
        """
        error_context.context("Creating test iso image '%s'" % name,
                              logging.info)
        if not os.path.isabs(name):
            cdrom_path = utils_misc.get_path(data_dir.get_data_dir(), name)
        else:
            cdrom_path = name
        if not cdrom_path.endswith(".iso"):
            cdrom_path = "%s.iso" % cdrom_path
        name = os.path.basename(cdrom_path)

        if file_size is None:
            file_size = 10

        if prepare:
            cmd = "dd if=/dev/urandom of=%s bs=1M count=%d"
            process.run(cmd % (name, file_size))
            process.run("mkisofs -o %s %s" % (cdrom_path, name))
            process.run("rm -rf %s" % (name))
        return cdrom_path

    def check_cdrom_size(session):
        error_context.context("Get the cdrom's size in guest.", logging.info)
        check_cdrom_size_cmd = params["check_cdrom_size_cmd"]
        output = session.cmd(check_cdrom_size_cmd, timeout=60)
        if not output:
            msg = "Unable to get the cdrom's size in guest."
            msg += " Command: %s\nOutput: %s" % (check_cdrom_size_cmd, output)
            test.error(msg)
        size = output.strip().splitlines()[-1]
        try:
            cdrom_size = int(size)
        except ValueError:
            cdrom_size = 0
        logging.info("Cdrom's size in guest %s", cdrom_size)
        return cdrom_size

    def mount_cdrom(session, guest_cdrom, mount_point,
                    show_mount_cmd, mount_cmd):
        txt = "Mount the cdrom in guest and check its block size."
        error_context.context(txt, logging.info)
        mounted = session.cmd(show_mount_cmd)
        if mount_point not in mounted:
            mount_cmd = params.get("mount_cdrom_cmd") % (guest_cdrom,
                                                         mount_point)
            status, output = session.cmd_status_output(mount_cmd, timeout=360)
            if status:
                msg = "Unable to mount cdrom. command: %s\n" % mount_cmd
                msg += " Output: %s" % output
                test.error(msg)

    cdroms = params["test_cdroms"]
    params["cdroms"] = cdroms
    params["start_vm"] = "yes"
    show_mount_cmd = params.get("show_mount_cmd")
    mount_cmd = params.get("mount_cdrom_cmd")
    umount_cmd = params.get("umount_cdrom_cmd")
    os_type = params["os_type"]
    error_context.context("Get the main VM", logging.info)
    main_vm = params["main_vm"]
    env_process.preprocess_vm(test, params, env, main_vm)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)

    guest_cdrom = list_guest_cdroms(session)[-1]
    mount_point = get_cdrom_mount_point(session, os_type, guest_cdrom)
    empty_size = check_cdrom_size(session)

    cdrom_name = params.get("orig_cdrom", "images/orig.iso")
    file_size = params.get("orig_cdrom_size", 100)
    orig_cdrom = create_iso_image(params, cdrom_name, prepare=True,
                                  file_size=file_size)

    cdrom_device = get_cdrom_device(vm)
    error_context.context("Attach a small cd iso file to the cdrom.",
                          logging.info)
    vm.change_media(cdrom_device, orig_cdrom)
    if mount_cmd:
        mount_cdrom(session, guest_cdrom, mount_point,
                    show_mount_cmd, mount_cmd)
    orig_size = utils_misc.wait_for(lambda: check_cdrom_size(session), 60, 5, 3)

    if orig_size == empty_size:
        err = "Get same block size '%s' after new cdrom attached" % orig_size
        test.fail(err)

    if umount_cmd:
        error_context.context("umount cdrom in guest.", logging.info)
        umount_cmd = umount_cmd % mount_point
        status, output = session.cmd_status_output(umount_cmd, timeout=360)
        if status:
            msg = "Unable to umount cdrom. command: %s\n" % umount_cmd
            msg += "Output: %s" % output
            test.error(msg)

    error_context.context("eject the cdrom from monitor.", logging.info)
    vm.eject_cdrom(cdrom_device)

    cdrom_name = params.get("final_cdrom", "images/final.iso")
    file_size = params.get("final_cdrom_size", 1000)
    final_cdrom = create_iso_image(params, cdrom_name, prepare=True,
                                   file_size=file_size)
    error_context.context("Attach a bigger cd iso file to the cdrom.",
                          logging.info)
    vm.change_media(cdrom_device, final_cdrom)
    if mount_cmd:
        mount_cdrom(session, guest_cdrom, mount_point,
                    show_mount_cmd, mount_cmd)
    final_size = utils_misc.wait_for(lambda: check_cdrom_size(session),
                                     60, 5, 3)

    if final_size == empty_size or final_size == orig_size:
        err = "Get same block size '%s' after new cdrom attached" % final_size
        test.fail(err)

    # Check guest's network.
    vm.wait_for_login(timeout=timeout)
