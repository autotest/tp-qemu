import logging
import os
import time

from avocado.utils import process
from virttest import data_dir, error_context, qemu_storage, utils_misc, virt_vm
from virttest.utils_misc import get_linux_drive_path

LOG_JOB = logging.getLogger("avocado.test")


class EnospcConfig(object):
    """
    Performs setup for the test enospc. This is a borg class, similar to a
    singleton. The idea is to keep state in memory for when we call cleanup()
    on postprocessing.
    """

    __shared_state = {}

    def __init__(self, test, params):
        self.__dict__ = self.__shared_state
        self.tmpdir = test.tmpdir
        self.qemu_img_binary = utils_misc.get_qemu_img_binary(params)
        self.raw_file_path = os.path.join(self.tmpdir, "enospc.raw")
        # Here we're trying to choose fairly explanatory names so it's less
        # likely that we run in conflict with other devices in the system
        self.vgtest_name = params["vgtest_name"]
        self.lvtest_name = params["lvtest_name"]
        self.lvtest_device = "/dev/%s/%s" % (self.vgtest_name, self.lvtest_name)
        image_dir = os.path.join(
            data_dir.get_data_dir(), os.path.dirname(params["image_name"])
        )
        self.qcow_file_path = os.path.join(image_dir, "enospc.qcow2")
        try:
            getattr(self, "loopback")
        except AttributeError:
            self.loopback = ""

    @error_context.context_aware
    def setup(self):
        LOG_JOB.debug("Starting enospc setup")
        error_context.context("performing enospc setup", LOG_JOB.info)
        utils_misc.display_attributes(self)
        # Double check if there aren't any leftovers
        self.cleanup()
        try:
            process.run(
                "%s create -f raw %s 10G" % (self.qemu_img_binary, self.raw_file_path)
            )
            # Associate a loopback device with the raw file.
            # Subject to race conditions, that's why try here to associate
            # it with the raw file as quickly as possible
            l_result = process.run("losetup -f")
            process.run("losetup -f %s" % self.raw_file_path)
            self.loopback = l_result.stdout.decode().strip()
            # Add the loopback device configured to the list of pvs
            # recognized by LVM
            process.run("pvcreate %s" % self.loopback)
            process.run("vgcreate %s %s" % (self.vgtest_name, self.loopback))
            # Create an lv inside the vg with starting size of 200M
            process.run(
                "lvcreate -L 200M -n %s %s" % (self.lvtest_name, self.vgtest_name)
            )
            # Create a 10GB qcow2 image in the logical volume
            process.run(
                "%s create -f qcow2 %s 10G" % (self.qemu_img_binary, self.lvtest_device)
            )
            # Let's symlink the logical volume with the image name that autotest
            # expects this device to have
            os.symlink(self.lvtest_device, self.qcow_file_path)
        except Exception:
            try:
                self.cleanup()
            except Exception as e:
                LOG_JOB.warning(e)
            raise

    @error_context.context_aware
    def cleanup(self):
        error_context.context("performing enospc cleanup", LOG_JOB.info)
        if os.path.islink(self.lvtest_device):
            process.run("fuser -k %s" % self.lvtest_device, ignore_status=True)
            time.sleep(2)
        l_result = process.run("lvdisplay")
        # Let's remove all volumes inside the volume group created
        if self.lvtest_name in l_result.stdout.decode():
            process.run("lvremove -f %s" % self.lvtest_device)
        # Now, removing the volume group itself
        v_result = process.run("vgdisplay")
        if self.vgtest_name in v_result.stdout.decode():
            process.run("vgremove -f %s" % self.vgtest_name)
        # Now, if we can, let's remove the physical volume from lvm list
        if self.loopback:
            p_result = process.run("pvdisplay")
            if self.loopback in p_result.stdout.decode():
                process.run("pvremove -f %s" % self.loopback)
        l_result = process.run("losetup -a")
        if self.loopback and (self.loopback in l_result.stdout.decode()):
            try:
                process.run("losetup -d %s" % self.loopback)
            except process.CmdError:
                LOG_JOB.error("Failed to liberate loopback %s", self.loopback)
        if os.path.islink(self.qcow_file_path):
            os.remove(self.qcow_file_path)
        if os.path.isfile(self.raw_file_path):
            os.remove(self.raw_file_path)


@error_context.context_aware
def run(test, params, env):
    """
    ENOSPC test

    1) Create a virtual disk on lvm
    2) Boot up guest with two disks
    3) Continually write data to second disk
    4) Check images and extend second disk when no space
    5) Continue paused guest
    6) Repeat step 3~5 several times

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    error_context.context("Create a virtual disk on lvm", test.log.info)
    enospc_config = EnospcConfig(test, params)
    enospc_config.setup()

    error_context.context("Boot up guest with two disks", test.log.info)
    vm = env.get_vm(params["main_vm"])
    vm.create()
    login_timeout = int(params.get("login_timeout", 360))
    session_serial = vm.wait_for_serial_login(timeout=login_timeout)

    vgtest_name = params["vgtest_name"]
    lvtest_name = params["lvtest_name"]
    logical_volume = "/dev/%s/%s" % (vgtest_name, lvtest_name)

    disk_serial = params["disk_serial"]
    devname = get_linux_drive_path(session_serial, disk_serial)
    cmd = params["background_cmd"]
    cmd %= devname

    error_context.context("Continually write data to second disk", test.log.info)
    test.log.info("Sending background cmd '%s'", cmd)
    session_serial.sendline(cmd)

    iterations = int(params.get("repeat_time", 40))
    i = 0
    pause_n = 0
    while i < iterations:
        if vm.monitor.verify_status("paused"):
            pause_n += 1
            error_context.context(
                "Checking all images in use by %s" % vm.name, test.log.info
            )
            for image_name in vm.params.objects("images"):
                image_params = vm.params.object_params(image_name)
                try:
                    image = qemu_storage.QemuImg(
                        image_params, data_dir.get_data_dir(), image_name
                    )
                    image.check_image(
                        image_params, data_dir.get_data_dir(), force_share=True
                    )
                except virt_vm.VMError as e:
                    test.log.error(e)
            error_context.context(
                "Guest paused, extending Logical Volume size", test.log.info
            )
            try:
                process.run("lvextend -L +200M %s" % logical_volume)
            except process.CmdError as e:
                test.log.debug(e.result.stdout.decode())
            error_context.context("Continue paused guest", test.log.info)
            vm.resume()
        elif not vm.monitor.verify_status("running"):
            status = str(vm.monitor.info("status"))
            test.error("Unexpected guest status: %s" % status)
        time.sleep(10)
        i += 1

    test.log.info("Final %s", str(vm.monitor.info("status")))
    # Shutdown guest before remove the image on LVM.
    vm.destroy(gracefully=vm.monitor.verify_status("running"))
    try:
        enospc_config.cleanup()
    except Exception as e:
        test.log.warning(e)

    if pause_n == 0:
        test.fail("Guest didn't pause during loop")
    else:
        test.log.info("Guest paused %s times from %s iterations", pause_n, iterations)
