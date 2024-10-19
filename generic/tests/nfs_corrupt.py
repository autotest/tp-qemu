import logging
import os
from functools import partial

from avocado.utils import process, service
from virttest import (
    error_context,
    qemu_monitor,
    utils_disk,
    utils_misc,
    utils_net,
    utils_numeric,
    virt_vm,
)
from virttest.qemu_storage import QemuImg

LOG_JOB = logging.getLogger("avocado.test")


class NFSCorruptError(Exception):
    def __init__(self, *args):
        Exception.__init__(self, *args)


class NFSCorruptConfig(object):
    """
    This class sets up nfs_corrupt test environment.
    """

    iptables_template = (
        "iptables -t filter -{{op}} OUTPUT -d {ip} -m state"
        " --state NEW,RELATED,ESTABLISHED -p tcp --dport 2049"
        " -j REJECT"
    )

    def __init__(self, test, params, ip="localhost"):
        self.nfs_dir = os.path.join(test.tmpdir, "nfs_dir")
        self.mnt_dir = os.path.join(test.tmpdir, "mnt_dir")
        self.chk_re = params.get("nfs_stat_chk_re", "running")
        self.nfs_ip = ip
        self.required_size = params.object_params("stg").get("image_size")
        self.iptables_template = self.iptables_template.format(ip=self.nfs_ip)

        self.service_manager = service.ServiceManager()
        for name in ["nfs", "nfs-server"]:
            if self.service_manager.status(name) is not None:
                self.service_name = name
                break
        else:
            msg = (
                "Fail to set up NFS for this host, service "
                "with name 'nfs' and 'nfs-server' not exist."
            )
            raise NFSCorruptError(msg)

        for attrname in ["start", "stop", "restart", "status"]:
            setattr(
                self,
                attrname,
                partial(getattr(self.service_manager, attrname), self.service_name),
            )

    @error_context.context_aware
    def setup(self, force_start=False):
        """
        Setup test NFS share.

        :param force_start: Whether to make NFS service start anyway.
        """
        error_context.context("Setting up test NFS share", LOG_JOB.info)

        for d in [self.nfs_dir, self.mnt_dir]:
            try:
                os.makedirs(d)
            except OSError:
                pass

        error_context.context("Checking available space to export", LOG_JOB.info)
        stat = os.statvfs(self.nfs_dir)
        free = stat.f_bsize * stat.f_bfree
        required = float(
            utils_misc.normalize_data_size(self.required_size, order_magnitude="B")
        )
        if free < required:
            msg = "Space available: %s, space needed: %s" % (
                utils_numeric.format_size_human_readable(free),
                self.required_size,
            )
            raise NFSCorruptError(msg)

        if force_start:
            self.start()
        else:
            if not self.status():
                self.start()

        process.run(
            "exportfs %s:%s -o rw,no_root_squash" % (self.nfs_ip, self.nfs_dir),
            shell=True,
        )
        process.run(
            "mount %s:%s %s -o rw,soft,timeo=30,retrans=1,vers=3"
            % (self.nfs_ip, self.nfs_dir, self.mnt_dir),
            shell=True,
        )

    @error_context.context_aware
    def cleanup(self, force_stop=False):
        error_context.context("Cleaning up test NFS share", LOG_JOB.info)
        process.run("umount -l -f %s" % self.mnt_dir, shell=True)
        process.run("exportfs -u %s:%s" % (self.nfs_ip, self.nfs_dir), shell=True)
        if force_stop:
            self.stop()

    def is_mounted(self):
        """
        Return True if nfs is mounted, otherwise False.
        """
        return utils_disk.is_mount(self.mnt_dir)

    def is_mounted_dir_acessible(self):
        """
        Check to see if mount directory is accessible.
        """
        if not self.is_mounted():
            return False
        try:
            os.stat(self.mnt_dir)
        except OSError:
            return False
        return True

    def iptables_rule_gen(self, op="A"):
        """
        Generate iptables rules to block/accept nfs connection.
        """
        return self.iptables_template.format(op=op)


@error_context.context_aware
def run(test, params, env):
    """
    Test if VM paused when image NFS shutdown, the drive option 'werror' should
    be stop, the drive option 'cache' should be none.

    1) Setup NFS service on host
    2) Boot up a VM using another disk on NFS server and write the disk by dd
    3) Check if VM status is 'running'
    4) Reject NFS connection on host
    5) Check if VM status is 'paused'
    6) Accept NFS connection on host and continue VM by monitor command
    7) Check if VM status is 'running'

    :param test: kvm test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def get_nfs_devname(params, session):
        """
        Get the possbile name of nfs storage dev name in guest.

        :param params: Test params dictionary.
        :param session: An SSH session object.
        """
        image1_type = params.object_params("image1").get("drive_format")
        stg_type = params.object_params("stg").get("drive_format")
        cmd = ""
        # Seems we can get correct 'stg' devname even if the 'stg' image
        # has a different type from main image (we call it 'image1' in
        # config file) with these 'if' sentences.
        if image1_type == stg_type:
            cmd = "ls /dev/[hsv]d[a-z]"
        elif stg_type == "virtio":
            cmd = "ls /dev/vd[a-z]"
        else:
            cmd = "ls /dev/[sh]d[a-z]"

        cmd += " | tail -n 1"
        return session.cmd_output(cmd).rstrip()

    def check_vm_status(vm, status):
        """
        Check if VM has the given status or not.

        :param vm: VM object.
        :param status: String with desired status.
        :return: True if VM status matches our desired status.
        :return: False if VM status does not match our desired status.
        """
        try:
            vm.verify_status(status)
        except (virt_vm.VMStatusError, qemu_monitor.MonitorLockError):
            return False
        else:
            return True

    error_context.context("Setup NFS Server on local host", test.log.info)
    host_ip = utils_net.get_host_ip_address(params)
    try:
        config = NFSCorruptConfig(test, params, host_ip)
        config.setup()
    except NFSCorruptError as e:
        test.error(str(e))

    image_stg_dir = config.mnt_dir
    stg_params = params.object_params("stg")
    stg_img = QemuImg(stg_params, image_stg_dir, "stg")
    stg_img.create(stg_params)

    error_context.context("Boot vm with image on NFS server", test.log.info)
    image_name = os.path.join(image_stg_dir, "nfs_corrupt")
    params["image_name_stg"] = image_name

    vm = env.get_vm(params["main_vm"])
    try:
        vm.create(params=params)
    except Exception:
        stg_img.remove()
        config.cleanup()
        test.error("failed to create VM")
    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))

    nfs_devname = utils_misc.get_linux_drive_path(session, stg_params["nfs_serial"])
    # Write disk on NFS server
    error_context.context("Write disk that image on NFS", test.log.info)
    write_disk_cmd = "dd if=/dev/zero of=%s oflag=direct" % nfs_devname
    test.log.info("dd with command: %s", write_disk_cmd)
    session.sendline(write_disk_cmd)
    try:
        # Read some command output, it will timeout
        session.read_up_to_prompt(timeout=30)
    except Exception:
        pass

    try:
        error_context.context("Make sure guest is running before test", test.log.info)
        vm.resume()
        vm.verify_status("running")

        try:
            error_context.context("Reject NFS connection on host", test.log.info)
            process.system(config.iptables_rule_gen("A"))

            error_context.context("Check if VM status is 'paused'", test.log.info)
            if not utils_misc.wait_for(
                lambda: check_vm_status(vm, "paused"),
                int(params.get("wait_paused_timeout", 240)),
            ):
                test.error("Guest is not paused after stop NFS")
        finally:
            error_context.context("Accept NFS connection on host", test.log.info)
            process.system(config.iptables_rule_gen("D"))

        error_context.context("Ensure nfs is resumed", test.log.info)
        nfs_resume_timeout = int(params.get("nfs_resume_timeout", 240))
        if not utils_misc.wait_for(config.is_mounted_dir_acessible, nfs_resume_timeout):
            test.error("NFS connection does not resume")

        error_context.context("Continue guest", test.log.info)
        vm.resume()

        error_context.context("Check if VM status is 'running'", test.log.info)
        if not utils_misc.wait_for(lambda: check_vm_status(vm, "running"), 20):
            test.error("Guest does not restore to 'running' status")

    finally:
        session.close()
        vm.destroy(gracefully=True)
        stg_img.check_image(params, image_stg_dir)
        stg_img.remove()
        config.cleanup()
