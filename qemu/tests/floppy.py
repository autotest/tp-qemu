import logging
import time
import os
import sys
import re
import six

import aexpect

from avocado.utils import process

from virttest import data_dir
from virttest import env_process
from virttest import error_context
from virttest.utils_test.qemu import migration


@error_context.context_aware
def run(test, params, env):
    """
    Test virtual floppy of guest:

    1) Create a floppy disk image on host
    2) Start the guest with this floppy image.
    3) Make a file system on guest virtual floppy.
    4) Calculate md5sum value of a file and copy it into floppy.
    5) Verify whether the md5sum does match.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    source_file = params["source_file"]
    dest_file = params["dest_file"]
    login_timeout = int(params.get("login_timeout", 360))
    floppy_prepare_timeout = int(params.get("floppy_prepare_timeout", 360))
    guest_floppy_path = params["guest_floppy_path"]

    def create_floppy(params, prepare=True):
        """
        Creates 'new' floppy with one file on it

        :param params: parameters for test
        :param preapre: if True then it prepare cd images.

        :return: path to new floppy file.
        """
        error_context.context("creating test floppy", logging.info)
        floppy = params["floppy_name"]
        if not os.path.isabs(floppy):
            floppy = os.path.join(data_dir.get_data_dir(), floppy)
        if prepare:
            process.run("dd if=/dev/zero of=%s bs=512 count=2880" % floppy)
        return floppy

    def cleanup_floppy(path):
        """ Removes created floppy """
        error_context.context("cleaning up temp floppy images", logging.info)
        os.remove("%s" % path)

    def lazy_copy(vm, dst_path, check_path, copy_timeout=None, dsize=None):
        """
        Start disk load. Cyclic copy from src_path to dst_path.

        :param vm: VM where to find a disk.
        :param src_path: Source of data
        :param copy_timeout: Timeout for copy
        :param dsize: Size of data block which is periodically copied.
        """
        if copy_timeout is None:
            copy_timeout = 120
        session = vm.wait_for_login(timeout=login_timeout)
        cmd = ('nohup bash -c "while [ true ]; do echo \"1\" | '
               'tee -a %s >> %s; sleep 0.1; done" 2> /dev/null &' %
               (check_path, dst_path))
        pid = re.search(r"\[.+\] (.+)",
                        session.cmd_output(cmd, timeout=copy_timeout))
        return pid.group(1)

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
            create_floppy(params)
            params["start_vm"] = "yes"
            vm_name = params.get("main_vm", "vm1")
            env_process.preprocess_vm(test, params, env, vm_name)
            vm = env.get_vm(vm_name)
            vm.verify_alive()
            self.session = vm.wait_for_login(timeout=login_timeout)

            self.dest_dir = params.get("mount_dir")
            # If mount_dir specified, treat guest as a Linux OS
            # Some Linux distribution does not load floppy at boot and Windows
            # needs time to load and init floppy driver
            if self.dest_dir:
                lsmod = self.session.cmd("lsmod")
                if 'floppy' not in lsmod:
                    self.session.cmd("modprobe floppy")
            else:
                time.sleep(20)

            error_context.context("Formating floppy disk before using it")
            format_cmd = params["format_floppy_cmd"]
            self.session.cmd(format_cmd, timeout=120)
            logging.info("Floppy disk formatted successfully")

            if self.dest_dir:
                error_context.context("Mounting floppy")
                self.session.cmd("mount %s %s" % (guest_floppy_path,
                                                  self.dest_dir))
            error_context.context("Testing floppy")
            self.session.cmd(params["test_floppy_cmd"])

            error_context.context("Copying file to the floppy")
            md5_cmd = params.get("md5_cmd")
            if md5_cmd:
                md5_source = self.session.cmd("%s %s" % (md5_cmd, source_file))
                try:
                    md5_source = md5_source.split(" ")[0]
                except IndexError:
                    test.error("Failed to get md5 from source file,"
                               " output: '%s'" % md5_source)
            else:
                md5_source = None

            self.session.cmd("%s %s %s" % (params["copy_cmd"], source_file,
                                           dest_file))
            logging.info("Succeed to copy file '%s' into floppy disk" %
                         source_file)

            error_context.context("Checking if the file is unchanged "
                                  "after copy")
            if md5_cmd:
                md5_dest = self.session.cmd("%s %s" % (md5_cmd, dest_file))
                try:
                    md5_dest = md5_dest.split(" ")[0]
                except IndexError:
                    test.error("Failed to get md5 from dest file,"
                               " output: '%s'" % md5_dest)
                if md5_source != md5_dest:
                    test.fail("File changed after copy to floppy")
            else:
                md5_dest = None
                self.session.cmd("%s %s %s" % (params["diff_file_cmd"],
                                               source_file, dest_file))

        def clean(self):
            clean_cmd = "%s %s" % (params["clean_cmd"], dest_file)
            self.session.cmd(clean_cmd)
            if self.dest_dir:
                self.session.cmd("umount %s" % self.dest_dir)
            self.session.close()

    class Multihost(MiniSubtest):

        def test(self):
            error_context.context("Preparing migration env and floppies.",
                                  logging.info)
            mig_protocol = params.get("mig_protocol", "tcp")
            self.mig_type = migration.MultihostMigration
            if mig_protocol == "fd":
                self.mig_type = migration.MultihostMigrationFd
            if mig_protocol == "exec":
                self.mig_type = migration.MultihostMigrationExec
            if "rdma" in mig_protocol:
                self.mig_type = migration.MultihostMigrationRdma

            self.vms = params.get("vms").split(" ")
            self.srchost = params["hosts"][0]
            self.dsthost = params["hosts"][1]
            self.is_src = params["hostid"] == self.srchost
            self.mig = self.mig_type(test, params, env, False, )

            if self.is_src:
                vm = env.get_vm(self.vms[0])
                vm.destroy()
                self.floppy = create_floppy(params)
                self.floppy_dir = os.path.dirname(self.floppy)
                params["start_vm"] = "yes"
                env_process.process(test, params, env,
                                    env_process.preprocess_image,
                                    env_process.preprocess_vm)
                vm = env.get_vm(self.vms[0])
                vm.wait_for_login(timeout=login_timeout)
            else:
                self.floppy = create_floppy(params, False)
                self.floppy_dir = os.path.dirname(self.floppy)

        def clean(self):
            self.mig.cleanup()
            if self.is_src:
                cleanup_floppy(self.floppy)

    class test_multihost_write(Multihost):

        def test(self):
            from autotest.client.shared.syncdata import SyncData

            super(test_multihost_write, self).test()

            copy_timeout = int(params.get("copy_timeout", 480))
            self.mount_dir = params["mount_dir"]
            format_floppy_cmd = params["format_floppy_cmd"]
            check_copy_path = params["check_copy_path"]

            pid = None
            sync_id = {'src': self.srchost,
                       'dst': self.dsthost,
                       "type": "file_trasfer"}
            filename = "orig"
            src_file = os.path.join(self.mount_dir, filename)

            if self.is_src:  # Starts in source
                vm = env.get_vm(self.vms[0])
                session = vm.wait_for_login(timeout=login_timeout)

                if self.mount_dir:
                    session.cmd("rm -f %s" % (src_file))
                    session.cmd("rm -f %s" % (check_copy_path))
                # If mount_dir specified, treat guest as a Linux OS
                # Some Linux distribution does not load floppy at boot
                # and Windows needs time to load and init floppy driver
                error_context.context("Prepare floppy for writing.",
                                      logging.info)
                if self.mount_dir:
                    lsmod = session.cmd("lsmod")
                    if 'floppy' not in lsmod:
                        session.cmd("modprobe floppy")
                else:
                    time.sleep(20)

                session.cmd(format_floppy_cmd)

                error_context.context("Mount and copy data.", logging.info)
                if self.mount_dir:
                    session.cmd("mount %s %s" % (guest_floppy_path,
                                                 self.mount_dir),
                                timeout=30)

                error_context.context("File copying test.", logging.info)

                pid = lazy_copy(vm, src_file, check_copy_path, copy_timeout)

            sync = SyncData(self.mig.master_id(), self.mig.hostid,
                            self.mig.hosts, sync_id, self.mig.sync_server)

            pid = sync.sync(pid, timeout=floppy_prepare_timeout)[self.srchost]

            self.mig.migrate_wait([self.vms[0]], self.srchost, self.dsthost)

            if not self.is_src:  # Starts in destination
                vm = env.get_vm(self.vms[0])
                session = vm.wait_for_login(timeout=login_timeout)
                error_context.context("Wait for copy finishing.", logging.info)
                status = session.cmd_status("kill %s" % pid,
                                            timeout=copy_timeout)
                if status != 0:
                    test.fail("Copy process was terminatted with"
                              " error code %s" % (status))

                session.cmd_status("kill -s SIGINT %s" % (pid),
                                   timeout=copy_timeout)

                error_context.context("Check floppy file checksum.",
                                      logging.info)
                md5_cmd = params.get("md5_cmd", "md5sum")
                if md5_cmd:
                    md5_floppy = session.cmd("%s %s" % (md5_cmd, src_file))
                    try:
                        md5_floppy = md5_floppy.split(" ")[0]
                    except IndexError:
                        test.error("Failed to get md5 from source file,"
                                   " output: '%s'" % md5_floppy)
                    md5_check = session.cmd("%s %s" % (md5_cmd, check_copy_path))
                    try:
                        md5_check = md5_check.split(" ")[0]
                    except IndexError:
                        test.error("Failed to get md5 from dst file,"
                                   " output: '%s'" % md5_floppy)
                    if md5_check != md5_floppy:
                        test.fail("There is mistake in copying, "
                                  "it is possible to check file on vm.")

                session.cmd("rm -f %s" % (src_file))
                session.cmd("rm -f %s" % (check_copy_path))

            self.mig._hosts_barrier(self.mig.hosts, self.mig.hosts,
                                    'finish_floppy_test', login_timeout)

        def clean(self):
            super(test_multihost_write, self).clean()

    class test_multihost_eject(Multihost):

        def test(self):
            from autotest.client.shared.syncdata import SyncData

            super(test_multihost_eject, self).test()

            self.mount_dir = params.get("mount_dir", None)
            format_floppy_cmd = params["format_floppy_cmd"]
            floppy = params["floppy_name"]
            second_floppy = params["second_floppy_name"]
            if not os.path.isabs(floppy):
                floppy = os.path.join(data_dir.get_data_dir(), floppy)
            if not os.path.isabs(second_floppy):
                second_floppy = os.path.join(data_dir.get_data_dir(),
                                             second_floppy)
            if not self.is_src:
                self.floppy = create_floppy(params)

            pid = None
            sync_id = {'src': self.srchost,
                       'dst': self.dsthost,
                       "type": "file_trasfer"}
            filename = "orig"
            src_file = os.path.join(self.mount_dir, filename)

            if self.is_src:  # Starts in source
                vm = env.get_vm(self.vms[0])
                session = vm.wait_for_login(timeout=login_timeout)

                if self.mount_dir:   # If linux
                    session.cmd("rm -f %s" % (src_file))
                # If mount_dir specified, treat guest as a Linux OS
                # Some Linux distribution does not load floppy at boot
                # and Windows needs time to load and init floppy driver
                error_context.context("Prepare floppy for writing.",
                                      logging.info)
                if self.mount_dir:   # If linux
                    lsmod = session.cmd("lsmod")
                    if 'floppy' not in lsmod:
                        session.cmd("modprobe floppy")
                else:
                    time.sleep(20)

                if floppy not in vm.monitor.info("block"):
                    test.fail("Wrong floppy image is placed in vm.")

                try:
                    session.cmd(format_floppy_cmd)
                except aexpect.ShellCmdError as e:
                    if e.status == 1:
                        logging.error("First access to floppy failed, "
                                      " Trying a second time as a workaround")
                        session.cmd(format_floppy_cmd)

                error_context.context("Check floppy")
                if self.mount_dir:   # If linux
                    session.cmd("mount %s %s" % (guest_floppy_path,
                                                 self.mount_dir), timeout=30)
                    session.cmd("umount %s" % (self.mount_dir), timeout=30)

                written = None
                if self.mount_dir:
                    filepath = os.path.join(self.mount_dir, "test.txt")
                    session.cmd("echo 'test' > %s" % (filepath))
                    output = session.cmd("cat %s" % (filepath))
                    written = "test\n"
                else:   # Windows version.
                    filepath = "A:\\test.txt"
                    session.cmd("echo test > %s" % (filepath))
                    output = session.cmd("type %s" % (filepath))
                    written = "test \n\n"
                if output != written:
                    test.fail("Data read from the floppy differs"
                              "from the data written to it."
                              " EXPECTED: %s GOT: %s" %
                              (repr(written), repr(output)))

                error_context.context("Change floppy.")
                vm.monitor.cmd("eject floppy0")
                vm.monitor.cmd("change floppy %s" % (second_floppy))
                session.cmd(format_floppy_cmd)

                error_context.context("Mount and copy data")
                if self.mount_dir:   # If linux
                    session.cmd("mount %s %s" % (guest_floppy_path,
                                                 self.mount_dir), timeout=30)

                if second_floppy not in vm.monitor.info("block"):
                    test.fail("Wrong floppy image is placed in vm.")

            sync = SyncData(self.mig.master_id(), self.mig.hostid,
                            self.mig.hosts, sync_id, self.mig.sync_server)

            pid = sync.sync(pid, timeout=floppy_prepare_timeout)[self.srchost]

            self.mig.migrate_wait([self.vms[0]], self.srchost, self.dsthost)

            if not self.is_src:  # Starts in destination
                vm = env.get_vm(self.vms[0])
                session = vm.wait_for_login(timeout=login_timeout)
                written = None
                if self.mount_dir:
                    filepath = os.path.join(self.mount_dir, "test.txt")
                    session.cmd("echo 'test' > %s" % (filepath))
                    output = session.cmd("cat %s" % (filepath))
                    written = "test\n"
                else:   # Windows version.
                    filepath = "A:\\test.txt"
                    session.cmd("echo test > %s" % (filepath))
                    output = session.cmd("type %s" % (filepath))
                    written = "test \n\n"
                if output != written:
                    test.fail("Data read from the floppy differs"
                              "from the data written to it."
                              " EXPECTED: %s GOT: %s" %
                              (repr(written), repr(output)))

            self.mig._hosts_barrier(self.mig.hosts, self.mig.hosts,
                                    'finish_floppy_test', login_timeout)

        def clean(self):
            super(test_multihost_eject, self).clean()

    test_type = params.get("test_type", "test_singlehost")
    if (test_type in locals()):
        tests_group = locals()[test_type]
        tests_group()
    else:
        test.fail("Test group '%s' is not defined in"
                  " migration_with_dst_problem test" % test_type)
