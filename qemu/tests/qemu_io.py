import logging
import os
import re
import time

import aexpect
from avocado.utils import process
from virttest import data_dir, error_context, utils_misc

LOG_JOB = logging.getLogger("avocado.test")


class QemuIOConfig(object):
    """
    Performs setup for the test qemu_io. This is a borg class, similar to a
    singleton. The idea is to keep state in memory for when we call cleanup()
    on postprocessing.
    """

    __shared_state = {}

    def __init__(self, test, params):
        self.__dict__ = self.__shared_state
        self.tmpdir = test.tmpdir
        self.qemu_img_binary = utils_misc.get_qemu_img_binary(params)
        self.raw_files = ["stg1.raw", "stg2.raw"]
        self.raw_files = list(
            map(lambda f: os.path.join(self.tmpdir, f), self.raw_files)
        )
        # Here we're trying to choose fairly explanatory names so it's less
        # likely that we run in conflict with other devices in the system
        self.vgtest_name = params.get("vgtest_name", "vg_kvm_test_qemu_io")
        self.lvtest_name = params.get("lvtest_name", "lv_kvm_test_qemu_io")
        self.lvtest_device = "/dev/%s/%s" % (self.vgtest_name, self.lvtest_name)
        try:
            getattr(self, "loopback")
        except AttributeError:
            self.loopback = []

    @error_context.context_aware
    def setup(self):
        error_context.context("performing setup", LOG_JOB.debug)
        utils_misc.display_attributes(self)
        # Double check if there aren't any leftovers
        self.cleanup()
        try:
            for f in self.raw_files:
                process.run("%s create -f raw %s 10G" % (self.qemu_img_binary, f))
                # Associate a loopback device with the raw file.
                # Subject to race conditions, that's why try here to associate
                # it with the raw file as quickly as possible
                l_result = process.run("losetup -f")
                process.run("losetup -f %s" % f)
                loopback = l_result.stdout.strip()
                self.loopback.append(loopback)
                # Add the loopback device configured to the list of pvs
                # recognized by LVM
                process.run("pvcreate %s" % loopback)
            loopbacks = " ".join(self.loopback)
            process.run("vgcreate %s %s" % (self.vgtest_name, loopbacks))
            # Create an lv inside the vg with starting size of 200M
            process.run(
                "lvcreate -L 19G -n %s %s" % (self.lvtest_name, self.vgtest_name)
            )
        except Exception:
            try:
                self.cleanup()
            except Exception as e:
                LOG_JOB.warning(e)
            raise

    @error_context.context_aware
    def cleanup(self):
        error_context.context("performing qemu_io cleanup", LOG_JOB.debug)
        if os.path.isfile(self.lvtest_device):
            process.run("fuser -k %s" % self.lvtest_device)
            time.sleep(2)
        l_result = process.run("lvdisplay")
        # Let's remove all volumes inside the volume group created
        if self.lvtest_name in l_result.stdout:
            process.run("lvremove -f %s" % self.lvtest_device)
        # Now, removing the volume group itself
        v_result = process.run("vgdisplay")
        if self.vgtest_name in v_result.stdout:
            process.run("vgremove -f %s" % self.vgtest_name)
        # Now, if we can, let's remove the physical volume from lvm list
        p_result = process.run("pvdisplay")
        l_result = process.run("losetup -a")
        for l in self.loopback:
            if l in p_result.stdout:
                process.run("pvremove -f %s" % l)
            if l in l_result.stdout:
                try:
                    process.run("losetup -d %s" % l)
                except process.CmdError as e:
                    LOG_JOB.error(
                        "Failed to liberate loopback %s, " "error msg: '%s'", l, e
                    )

        for f in self.raw_files:
            if os.path.isfile(f):
                os.remove(f)


def run(test, params, env):
    """
    Run qemu_iotests.sh script:
    1) Do some qemu_io operations(write & read etc.)
    2) Check whether qcow image file is corrupted

    :param test:   QEMU test object
    :param params: Dictionary with the test parameters
    :param env:    Dictionary with test environment.
    """

    test_type = params.get("test_type")
    qemu_io_config = None
    if test_type == "lvm":
        qemu_io_config = QemuIOConfig(test, params)
        qemu_io_config.setup()

    test_script = os.path.join(data_dir.get_shared_dir(), "scripts/qemu_iotests.sh")
    test_image = params.get("test_image", os.path.join(test.tmpdir, "test.qcow2"))
    test.log.info("Run script(%s) with image(%s)", test_script, test_image)
    s, test_result = aexpect.run_fg(
        "sh %s %s" % (test_script, test_image), test.log.debug, timeout=1800
    )

    err_string = {
        "err_nums": r"\d errors were found on the image.",
        "an_err": "An error occurred during the check",
        "unsupt_err": "This image format does not support checks",
        "mem_err": "Not enough memory",
        "open_err": "Could not open",
        "fmt_err": "Unknown file format",
        "commit_err": "Error while committing image",
        "bootable_err": "no bootable device",
    }

    try:
        for err_type in err_string.keys():
            msg = re.findall(err_string.get(err_type), test_result)
            if msg:
                test.fail(msg)
    finally:
        try:
            if qemu_io_config:
                qemu_io_config.cleanup()
        except Exception as e:
            test.log.warning(e)
