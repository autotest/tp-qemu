import os
import time
import re
import logging
import commands
import shutil
import tempfile

from autotest.client.shared import error
from autotest.client.shared import utils

from virttest import utils_misc
from virttest import env_process
from virttest import storage
from virttest import data_dir
from virttest import gluster


@error.context_aware
def run(test, params, env):
    """
    'qemu-img' functions test:
    1) Judge what subcommand is going to be tested
    2) Run subcommand test

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    qemu_img_binary = utils_misc.get_qemu_img_binary(params)
    cmd = qemu_img_binary
    if not os.path.exists(cmd):
        raise error.TestError("Binary of 'qemu-img' not found")
    image_format = params["image_format"]
    image_size = params.get("image_size", "10G")
    enable_gluster = params.get("enable_gluster", "no") == "yes"
    image_name = storage.get_image_filename(params, data_dir.get_data_dir())

    def remove(path):
        try:
            os.remove(path)
        except OSError:
            pass

    def _get_image_filename(img_name, enable_gluster=False, img_fmt=None):
        """
        Generate an image path.

        :param image_name: Force name of image.
        :param enable_gluster: Enable gluster or not.
        :param image_format: Format for image.
        """
        if enable_gluster:
            gluster_uri = gluster.create_gluster_uri(params)
            image_filename = "%s%s" % (gluster_uri, img_name)
            if img_fmt:
                image_filename += ".%s" % img_fmt
        else:
            if img_fmt:
                img_name = "%s.%s" % (img_name, img_fmt)
            image_filename = utils_misc.get_path(data_dir.get_data_dir(),
                                                 img_name)
        return image_filename

    def _check(cmd, img):
        """
        Simple 'qemu-img check' function implementation.

        :param cmd: qemu-img base command.
        :param img: image to be checked
        """
        cmd += " check %s" % img
        error.context("Checking image '%s' by command '%s'" % (img, cmd),
                      logging.info)
        try:
            output = utils.system_output(cmd, verbose=False)
        except error.CmdError, err:
            if "does not support checks" in str(err):
                return (True, "")
            else:
                return (False, str(err))
        return (True, output)

    def check_test(cmd):
        """
        Subcommand 'qemu-img check' test.

        This tests will 'dd' to create a specified size file, and check it.
        Then convert it to supported image_format in each loop and check again.

        :param cmd: qemu-img base command.
        """
        test_image = _get_image_filename(params["image_name_dd"],
                                         enable_gluster)
        create_image_cmd = params["create_image_cmd"]
        create_image_cmd = create_image_cmd % test_image
        msg = " Create image %s by command %s" % (test_image, create_image_cmd)
        error.context(msg, logging.info)
        utils.system(create_image_cmd, verbose=False)
        status, output = _check(cmd, test_image)
        if not status:
            raise error.TestFail("Check image '%s' failed with error: %s" %
                                 (test_image, output))
        for fmt in params["supported_image_formats"].split():
            output_image = test_image + ".%s" % fmt
            _convert(cmd, fmt, test_image, output_image)
            status, output = _check(cmd, output_image)
            if not status:
                raise error.TestFail("Check image '%s' got error: %s" %
                                     (output_image, output))
            remove(output_image)
        remove(test_image)

    def _create(cmd, img_name, fmt, img_size=None, base_img=None,
                base_img_fmt=None, encrypted="no",
                preallocated="off", cluster_size=None):
        """
        Simple wrapper of 'qemu-img create'

        :param cmd: qemu-img base command.
        :param img_name: name of the image file
        :param fmt: image format
        :param img_size:  image size
        :param base_img: base image if create a snapshot image
        :param base_img_fmt: base image format if create a snapshot image
        :param encrypted: indicates whether the created image is encrypted
        :param preallocated: if preallocation when create image,
                             allowed values: off, metadata. Default is "off"
        :param cluster_size: the cluster size for the image
        """
        cmd += " create"

        if encrypted == "yes":
            cmd += " -e"
        if base_img:
            cmd += " -b %s" % base_img
            if base_img_fmt:
                cmd += " -F %s" % base_img_fmt

        cmd += " -f %s" % fmt

        options = []
        if preallocated != "off":
            options.append("preallocation=%s" % preallocated)
        if cluster_size is not None:
            options.append("cluster_size=%s" % cluster_size)
        if options:
            cmd += " -o %s" % ",".join(options)

        cmd += " %s" % img_name
        if img_size:
            cmd += " %s" % img_size

        msg = "Creating image %s by command %s" % (img_name, cmd)
        error.context(msg, logging.info)
        utils.system(cmd, verbose=False)
        status, out = _check(qemu_img_binary, img_name)
        if not status:
            raise error.TestFail("Check image '%s' got error: %s" %
                                 (img_name, out))

    def create_test(cmd):
        """
        Subcommand 'qemu-img create' test.

        :param cmd: qemu-img base command.
        """
        image_large = params["image_name_large"]
        device = params.get("device")
        if not device:
            img = _get_image_filename(image_large, enable_gluster,
                                      image_format)
        else:
            img = device
        _create(cmd, img_name=img, fmt=image_format,
                img_size=params["image_size_large"],
                preallocated=params.get("preallocated", "off"),
                cluster_size=params.get("image_cluster_size"))
        remove(img)

    def send_signal(timeout=360):
        """
        send signal "SIGUSR1" to qemu-img without the option -p
        to report progress
        """
        logging.info("Send signal to qemu-img")
        end_time = time.time() + timeout
        while time.time() < end_time:
            time.sleep(1)
            status = utils.system("kill -SIGUSR1 `pidof qemu-img`",
                                  ignore_status=True)
            if status == 0:
                return None
        logging.info("Fail to get pid of qemu-img")

    def check_command_output(CmdResult):
        """
        Check standard error or standard output of command
        : param CmdResult: a list of CmdResult objects
        """
        logging.info("Check result of command")
        check_output = params.get("check_output", "exit_status")
        if not hasattr(CmdResult, check_output):
            raise error.TestError("Unknown check output '%s'" % check_output)
        output = getattr(CmdResult, check_output)
        if check_output == "exit_status" and output == 0:
            return None
        if check_output == "exit_status" and output != 0:
            err_msg = "Get nonzero exit status(%d) '%s'"
            raise error.TestFail(err_msg % (output, CmdResult.command))
        pattern = params.get("command_result_pattern")
        if not re.findall(pattern, output):
            err_msg = "Fail to get expected result!"
            err_msg += "Output: %s, expected pattern: %s" % (output, pattern)
            raise error.TestFail(err_msg)

    def _convert(cmd, output_fmt, img_name, output_filename,
                 fmt=None, compressed="no", encrypted="no"):
        """
        Simple wrapper of 'qemu-img convert' function.

        :param cmd: qemu-img base command.
        :param output_fmt: the output format of converted image
        :param img_name: image name that to be converted
        :param output_filename: output image name that converted
        :param fmt: output image format
        :param compressed: whether output image is compressed
        :param encrypted: whether output image is encrypted
        """
        cmd += " convert"
        if compressed == "yes":
            cmd += " -c"
        if encrypted == "yes":
            cmd += " -e"
        show_progress = params.get("show_progress", "")
        if show_progress == "on":
            cmd += " -p"
        if fmt:
            cmd += " -f %s" % fmt
        cmd += " -O %s" % output_fmt
        options = params.get("qemu_img_options")
        if options:
            options = options.split()
            cmd += " -o "
            for option in options:
                value = params.get(option)
                cmd += "%s=%s," % (option, value)
            cmd = cmd.rstrip(",")
        cmd += " %s %s" % (img_name, output_filename)
        msg = "Converting '%s' from format '%s'" % (img_name, fmt)
        msg += " to '%s'" % output_fmt
        error.context(msg, logging.info)
        if show_progress == "off":
            bg = utils.InterruptedThread(send_signal)
            bg.start()
        check_command_output(utils.run(cmd, ignore_status=True))

    def convert_test(cmd):
        """
        Subcommand 'qemu-img convert' test.

        :param cmd: qemu-img base command.
        """
        dest_img_fmt = params["dest_image_format"]
        output_filename = "%s.converted_%s.%s" % (image_name,
                                                  dest_img_fmt, dest_img_fmt)

        _convert(cmd, dest_img_fmt, image_name, output_filename,
                 image_format, params["compressed"], params["encrypted"])
        orig_img_name = params.get("image_name")
        img_name = "%s.%s.converted_%s" % (orig_img_name,
                                           image_format, dest_img_fmt)
        _boot(img_name, dest_img_fmt)

        if dest_img_fmt == "qcow2":
            status, output = _check(cmd, output_filename)
            if status:
                remove(output_filename)
            else:
                raise error.TestFail("Check image '%s' failed with error: %s" %
                                     (output_filename, output))
        else:
            remove(output_filename)

    def _info(cmd, img, sub_info=None, fmt=None):
        """
        Simple wrapper of 'qemu-img info'.

        :param cmd: qemu-img base command.
        :param img: image file
        :param sub_info: sub info, say 'backing file'
        :param fmt: image format
        """
        cmd += " info"
        if fmt:
            cmd += " -f %s" % fmt
        cmd += " %s" % img

        try:
            output = utils.system_output(cmd)
        except error.CmdError, err:
            logging.error("Get info of image '%s' failed: %s", img, str(err))
            return None

        if not sub_info:
            return output

        sub_info += ": (.*)"
        matches = re.findall(sub_info, output)
        if "virtual size" in sub_info:
            p = re.compile(r'\.0*(G|K)$')
            return p.sub(r'\1', matches[0].split()[0])
        if matches:
            return matches[0]
        return None

    def info_test(cmd):
        """
        Subcommand 'qemu-img info' test.

        :param cmd: qemu-img base command.
        """
        img_info = _info(cmd, image_name)
        logging.info("Info of image '%s':\n%s", image_name, img_info)
        if image_format not in img_info:
            raise error.TestFail("Got unexpected format of image '%s'"
                                 " in info test" % image_name)
        if image_size not in img_info:
            raise error.TestFail("Got unexpected size of image '%s'"
                                 " in info test" % image_name)

    def snapshot_test(cmd):
        """
        Subcommand 'qemu-img snapshot' test.

        :param cmd: qemu-img base command.
        """
        cmd += " snapshot"
        for i in range(2):
            crtcmd = cmd
            sn_name = "snapshot%d" % i
            crtcmd += " -c %s %s" % (sn_name, image_name)
            msg = "Created snapshot '%s' in '%s' by command %s" % (sn_name,
                                                                   image_name,
                                                                   crtcmd)
            error.context(msg, logging.info)
            status, output = commands.getstatusoutput(crtcmd)
            if status != 0:
                raise error.TestFail("Create snapshot failed via command: %s;"
                                     "Output is: %s" % (crtcmd, output))
        listcmd = cmd
        listcmd += " -l %s" % image_name
        status, out = commands.getstatusoutput(listcmd)
        if not ("snapshot0" in out and "snapshot1" in out and status == 0):
            raise error.TestFail("Snapshot created failed or missed;"
                                 "snapshot list is: \n%s" % out)
        for i in range(2):
            sn_name = "snapshot%d" % i
            applycmd = cmd
            applycmd += " -a %s %s" % (sn_name, image_name)
            msg = "Apply snapshot '%s' by command %s" % (sn_name, applycmd)
            error.context(msg, logging.info)
            status, output = commands.getstatusoutput(applycmd)
            if status != 0:
                raise error.TestFail("Apply snapshot '%s' failed: %s" %
                                     (sn_name, output))
        for i in range(2):
            sn_name = "snapshot%d" % i
            delcmd = cmd
            delcmd += " -d %s %s" % (sn_name, image_name)
            msg = "Delete snapshot '%s' by command %s" % (sn_name, delcmd)
            error.context(msg, logging.info)
            status, output = commands.getstatusoutput(delcmd)
            if status != 0:
                raise error.TestFail("Delete snapshot '%s' failed: %s" %
                                     (sn_name, output))

    def commit_test(cmd):
        """
        Subcommand 'qemu-img commit' test.
        1) Create a overlay file of the qemu harddisk specified by image_name.
        2) Start a VM using the overlay file as its harddisk.
        3) Touch a file "commit_testfile" in the overlay file, and shutdown the
           VM.
        4) Commit the change to the backing harddisk by executing
           "qemu-img commit" command.
        5) Start the VM using the backing harddisk.
        6) Check if the file "commit_testfile" exists.

        :param cmd: qemu-img base command.
        """

        logging.info("Commit testing started!")
        image_name = storage.get_image_filename(params,
                                                data_dir.get_data_dir())
        pre_name = '.'.join(image_name.split('.')[:-1])
        image_format = params.get("image_format", "qcow2")
        overlay_file_name = "%s_overlay.%s" % (pre_name, image_format)
        file_create_cmd = params.get("file_create_cmd",
                                     "touch /commit_testfile")
        file_info_cmd = params.get("file_info_cmd",
                                   "ls / | grep commit_testfile")
        file_exist_chk_cmd = params.get("file_exist_chk_cmd",
                                        "[ -e /commit_testfile ] && echo $?")
        file_del_cmd = params.get("file_del_cmd",
                                  "rm -f /commit_testfile")
        try:
            # Remove the existing overlay file
            if os.path.isfile(overlay_file_name):
                remove(overlay_file_name)

            # Create the new overlay file
            create_cmd = "%s create -b %s -f %s %s" % (cmd, image_name,
                                                       image_format,
                                                       overlay_file_name)
            msg = "Create overlay file by command: %s" % create_cmd
            error.context(msg, logging.info)
            try:
                utils.system(create_cmd, verbose=False)
            except error.CmdError:
                raise error.TestFail("Could not create a overlay file!")
            logging.info("overlay file (%s) created!" % overlay_file_name)

            # Set the qemu harddisk to the overlay file
            logging.info(
                "Original image_name is: %s", params.get('image_name'))
            params['image_name'] = '.'.join(overlay_file_name.split('.')[:-1])
            logging.info("Param image_name changed to: %s",
                         params.get('image_name'))

            msg = "Start a new VM, using overlay file as its harddisk"
            error.context(msg, logging.info)
            vm_name = params['main_vm']
            env_process.preprocess_vm(test, params, env, vm_name)
            vm = env.get_vm(vm_name)
            vm.verify_alive()
            timeout = int(params.get("login_timeout", 360))
            session = vm.wait_for_login(timeout=timeout)

            # Do some changes to the overlay_file harddisk
            try:
                output = session.cmd(file_create_cmd)
                logging.info("Output of %s: %s", file_create_cmd, output)
                output = session.cmd(file_info_cmd)
                logging.info("Output of %s: %s", file_info_cmd, output)
            except Exception, err:
                raise error.TestFail("Could not create commit_testfile in the "
                                     "overlay file %s" % err)
            vm.destroy()

            # Execute the commit command
            cmitcmd = "%s commit -f %s %s" % (cmd, image_format,
                                              overlay_file_name)
            error.context("Committing image by command %s" % cmitcmd,
                          logging.info)
            try:
                utils.system(cmitcmd, verbose=False)
            except error.CmdError:
                raise error.TestFail("Could not commit the overlay file")
            logging.info("overlay file (%s) committed!" % overlay_file_name)

            msg = "Start a new VM, using image_name as its harddisk"
            error.context(msg, logging.info)
            params['image_name'] = pre_name
            vm_name = params['main_vm']
            env_process.preprocess_vm(test, params, env, vm_name)
            vm = env.get_vm(vm_name)
            vm.verify_alive()
            timeout = int(params.get("login_timeout", 360))
            session = vm.wait_for_login(timeout=timeout)
            try:
                output = session.cmd(file_exist_chk_cmd)
                logging.info("Output of %s: %s", file_exist_chk_cmd, output)
                session.cmd(file_del_cmd)
            except Exception:
                raise error.TestFail("Could not find commit_testfile after a "
                                     "commit")
            vm.destroy()

        finally:
            # Remove the overlay file
            if os.path.isfile(overlay_file_name):
                remove(overlay_file_name)

    def _rebase(cmd, img_name, base_img, backing_fmt, mode="unsafe"):
        """
        Simple wrapper of 'qemu-img rebase'.

        :param cmd: qemu-img base command.
        :param img_name: image name to be rebased
        :param base_img: indicates the base image
        :param backing_fmt: the format of base image
        :param mode: rebase mode: safe mode, unsafe mode
        """
        cmd += " rebase"
        show_progress = params.get("show_progress", "")
        if mode == "unsafe":
            cmd += " -u"
        if show_progress == "on":
            cmd += " -p"
        cmd += " -b %s -F %s %s" % (base_img, backing_fmt, img_name)
        msg = "Trying to rebase '%s' to '%s' by command %s" % (img_name,
                                                               base_img, cmd)
        error.context(msg, logging.info)
        if show_progress == "off":
            bg = utils.InterruptedThread(send_signal)
            bg.start()
        check_command_output(utils.run(cmd))

    def rebase_test(cmd):
        """
        Subcommand 'qemu-img rebase' test

        Change the backing file of a snapshot image in "unsafe mode":
        Assume the previous backing file had missed and we just have to change
        reference of snapshot to new one. After change the backing file of a
        snapshot image in unsafe mode, the snapshot should work still.

        :param cmd: qemu-img base command.
        """
        if 'rebase' not in utils.system_output(cmd + ' --help',
                                               ignore_status=True):
            raise error.TestNAError("Current kvm user space version does not"
                                    " support 'rebase' subcommand")
        sn_fmt = params.get("snapshot_format", "qcow2")
        sn1 = params["image_name_snapshot1"]
        sn1 = _get_image_filename(sn1, enable_gluster, sn_fmt)
        base_img = storage.get_image_filename(params, data_dir.get_data_dir())
        _create(cmd, sn1, sn_fmt, base_img=base_img, base_img_fmt=image_format)

        # Create snapshot2 based on snapshot1
        sn2 = params["image_name_snapshot2"]
        sn2 = _get_image_filename(sn2, enable_gluster, sn_fmt)
        _create(cmd, sn2, sn_fmt, base_img=sn1, base_img_fmt=sn_fmt)

        rebase_mode = params.get("rebase_mode", "safe")
        if rebase_mode == "unsafe":
            remove(sn1)

        _rebase(cmd, sn2, base_img, image_format, mode=rebase_mode)
        # Boot snapshot image after rebase
        img_format = sn2.split('.')[-1]
        img_name = ".".join(sn2.split('.')[:-1])
        _boot(img_name, img_format)

        # Check sn2's format and backing_file
        actual_base_img = _info(cmd, sn2, "backing file")
        base_img_name = os.path.basename(base_img)
        if base_img_name not in actual_base_img:
            raise error.TestFail("After rebase the backing_file of 'sn2' is "
                                 "'%s' which is not expected as '%s'"
                                 % (actual_base_img, base_img_name))
        status, output = _check(cmd, sn2)
        if not status:
            raise error.TestFail("Check image '%s' failed after rebase;"
                                 "got error: %s" % (sn2, output))
        remove(sn2)
        remove(sn1)

    def _amend(cmd, img_name, img_fmt, options):
        """
        Simple wrapper of 'qemu-img amend'.

        :param cmd: qemu-img base command
        :param img_name: image name that should be amended
        :param img_fmt: image format
        :param options: a comma separated list of format specific options
        """

        msg = "Amend '%s' with options '%s'" % (img_name, options)
        cmd += " amend"
        if img_fmt:
            cmd += " -f %s" % img_fmt
        cache = params.get("cache_mode", '')
        if cache:
            cmd += " -t %s" % cache
        if options:
            cmd += " -o "
            for option in options:
                cmd += "%s=%s," % (option, params.get(option))
            cmd = cmd.rstrip(',')
        cmd += " %s" % img_name
        error.context(msg, logging.info)
        check_command_output(utils.run(cmd, ignore_status=True))

    def amend_test(cmd):
        """
        Subcommand 'qemu-img amend' test
        Amend the image format specific options for the image file

        :param cmd: qemu-img base command.
        """
        img_name = params.get("image_name_stg")
        img_fmt = params.get("image_format_stg", "qcow2")
        options = params.get("qemu_img_options", "").split()
        check_output = params.get("check_output", "exit_status")
        img = _get_image_filename(img_name, img_fmt=img_fmt)
        _amend(cmd, img, img_fmt, options)
        if check_output == "exit_status":
            for option in options:
                expect = params.get(option)
                if option == "size":
                    option = "virtual size"
                actual = _info(cmd, img, option)
                if actual is not None and actual != expect:
                    msg = "Get wrong %s from image %s!" % (option, img_name)
                    msg += "Expect: %s, actual: %s" % (expect, actual)
                    raise error.TestFail(msg)
        status, output = _check(cmd, img)
        if not status:
            raise error.TestFail("Check image '%s' failed after rebase;"
                                 "got error: %s" % (img, output))

    def _boot(img_name, img_fmt):
        """
        Boot test:
        1) Login guest
        2) Run dd in rhel guest
        3) Shutdown guest

        :param img_name: image name
        :param img_fmt: image format
        """
        params['image_name'] = img_name
        params['image_format'] = img_fmt
        image_name = "%s.%s" % (img_name, img_fmt)
        msg = "Try to boot vm with image %s" % image_name
        error.context(msg, logging.info)
        vm_name = params.get("main_vm")
        dd_timeout = int(params.get("dd_timeout", 60))
        params['vms'] = vm_name
        env_process.preprocess_vm(test, params, env, vm_name)
        vm = env.get_vm(params.get("main_vm"))
        vm.verify_alive()
        login_timeout = int(params.get("login_timeout", 360))
        session = vm.wait_for_login(timeout=login_timeout)

        # Run dd in linux guest
        if params.get("os_type") == 'linux':
            cmd = "dd if=/dev/zero of=/mnt/test bs=1000 count=1000"
            status = session.get_command_status(cmd, timeout=dd_timeout)
            if status != 0:
                raise error.TestError("dd failed")

        error.context("Shutdown guest", logging.info)
        try:
            vm.graceful_shutdown(timeout=login_timeout)
        except Exception:
            image_filename = _get_image_filename(img_name,
                                                 enable_gluster,
                                                 img_fmt)
            backup_img_chain(image_filename)
            raise
        finally:
            vm.destroy(gracefully=True)
            utils.system("sync")

    def backup_img_chain(image_file):
        """
        Backup whole image in a image chain;
        """
        mount_point = tempfile.mkdtemp(dir=test.resultsdir)
        qemu_img = utils_misc.get_qemu_img_binary(params)
        if enable_gluster:
            g_uri = gluster.create_gluster_uri(params)
            gluster.glusterfs_mount(g_uri, mount_point)
            image_name = os.path.basename(image_file)
            image_file = os.path.join(mount_point, image_name)
        logging.warn("backup %s to %s" % (image_file, test.resultsdir))
        shutil.copy(image_file, test.resultsdir)
        backing_file = _info(qemu_img, image_file, "backing file", None)
        if backing_file:
            backup_img_chain(backing_file)
        elif enable_gluster:
            utils_misc.umount(g_uri, mount_point,
                              "glusterfs", False,
                              "fuse.glusterfs")
            shutil.rmtree(mount_point)
        return None

    # Here starts test
    subcommand = params["subcommand"]
    error.context("Running %s_test(cmd)" % subcommand, logging.info)
    eval("%s_test(cmd)" % subcommand)
