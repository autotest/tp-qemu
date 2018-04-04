import os
import re
import logging

from avocado.utils import process
from avocado.utils import path as utils_path
from virttest import utils_misc
from virttest import utils_net
from virttest import env_process
from virttest import error_context


class NFSCorruptError(Exception):

    def __init__(self, *args):
        Exception.__init__(self, *args)


class NFSCorruptConfig(object):

    """
    This class sets up nfs_corrupt test environment.
    """

    def __init__(self, test, params, ip="localhost"):
        self.nfs_dir = os.path.join(test.tmpdir, "nfs_dir")
        self.mnt_dir = os.path.join(test.tmpdir, "mnt_dir")
        self.chk_re = params.get("nfs_stat_chk_re", "running")
        self.nfs_ip = ip
        self.required_size = params.object_params("stg").get("image_size")

        cmd_list = self._get_service_cmds()
        self.start_cmd = cmd_list[0]
        self.stop_cmd = cmd_list[1]
        self.restart_cmd = cmd_list[2]
        self.status_cmd = cmd_list[3]

    @error_context.context_aware
    def _get_service_cmds(self):
        """
        Figure out the commands used to control the NFS service.
        """
        error_context.context("Finding out commands to handle NFS service",
                              logging.info)
        service = utils_path.find_command("service")
        try:
            systemctl = utils_path.find_command("systemctl")
        except ValueError:
            systemctl = None

        if systemctl is not None:
            init_script = "/etc/init.d/nfs"
            service_file = "/lib/systemd/system/nfs-server.service"
            if os.path.isfile(init_script):
                service_name = "nfs"
            elif os.path.isfile(service_file):
                service_name = "nfs-server"
            else:
                raise NFSCorruptError("Files %s and %s absent, don't know "
                                      "how to set up NFS for this host" %
                                      (init_script, service_file))
            start_cmd = "%s start %s.service" % (systemctl, service_name)
            stop_cmd = "%s stop %s.service" % (systemctl, service_name)
            restart_cmd = "%s restart %s.service" % (systemctl, service_name)
            status_cmd = "%s status %s.service" % (systemctl, service_name)
        else:
            start_cmd = "%s nfs start" % service
            stop_cmd = "%s nfs stop" % service
            restart_cmd = "%s nfs restart" % service
            status_cmd = "%s nfs status" % service

        return [start_cmd, stop_cmd, restart_cmd, status_cmd]

    @error_context.context_aware
    def setup(self, force_start=False):
        """
        Setup test NFS share.

        :param force_start: Whether to make NFS service start anyway.
        """
        error_context.context("Setting up test NFS share", logging.info)

        for d in [self.nfs_dir, self.mnt_dir]:
            try:
                os.makedirs(d)
            except OSError:
                pass

        error_context.context("Checking available space to export",
                              logging.info)
        stat = os.statvfs(self.nfs_dir)
        free = str(stat.f_bsize * stat.f_bfree) + 'B'
        available_size = float(utils_misc.normalize_data_size(free,
                                                              order_magnitude="M"))
        required_size = float(utils_misc.normalize_data_size(self.required_size,
                                                             order_magnitude="M"))
        if available_size < required_size:
            raise NFSCorruptError("Space available: %fM, space needed: %fM"
                                  % (available_size, required_size))

        if force_start:
            self.start_service()
        else:
            if not self.is_service_active():
                self.start_service()

        process.run("exportfs %s:%s -o rw,no_root_squash" %
                    (self.nfs_ip, self.nfs_dir))
        process.run("mount %s:%s %s -o rw,soft,timeo=30,retrans=1,vers=3" %
                    (self.nfs_ip, self.nfs_dir, self.mnt_dir))

    @error_context.context_aware
    def cleanup(self, force_stop=False):
        error_context.context("Cleaning up test NFS share", logging.info)
        process.run("umount %s" % self.mnt_dir)
        process.run("exportfs -u %s:%s" % (self.nfs_ip, self.nfs_dir))
        if force_stop:
            self.stop_service()

    def start_service(self):
        """
        Starts the NFS server.
        """
        process.run(self.start_cmd)

    def stop_service(self):
        """
        Stops the NFS server.
        """
        process.run(self.stop_cmd)

    def restart_service(self):
        """
        Restarts the NFS server.
        """
        process.run(self.restart_cmd)

    def is_service_active(self):
        """
        Verifies whether the NFS server is running or not.

        :param chk_re: Regular expression that tells whether NFS is running
                or not.
        """
        status = process.system_output(self.status_cmd, ignore_status=True)
        if re.findall(self.chk_re, status):
            return True
        else:
            return False


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
        return session.cmd_output(cmd)

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
        except:
            return False
        else:
            return True

    error_context.context("Setup NFS Server on local host", logging.info)
    host_ip = utils_net.get_host_ip_address(params)
    try:
        config = NFSCorruptConfig(test, params, host_ip)
        config.setup()
    except NFSCorruptError as e:
        test.error(str(e))
    image_name = os.path.join(config.mnt_dir, "nfs_corrupt")
    params["image_name_stg"] = image_name
    params["force_create_image_stg"] = "yes"
    params["create_image_stg"] = "yes"
    stg_params = params.object_params("stg")

    error_context.context("Boot vm with image on NFS server", logging.info)
    env_process.preprocess_image(test, stg_params, image_name)

    vm = env.get_vm(params["main_vm"])
    vm.create(params=params)
    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))

    nfs_devname = get_nfs_devname(params, session)

    # Write disk on NFS server
    error_context.context("Write disk that image on NFS", logging.info)
    write_disk_cmd = "dd if=/dev/urandom of=%s" % nfs_devname
    session.sendline(write_disk_cmd)
    try:
        # Read some command output, it will timeout
        session.read_up_to_prompt(timeout=30)
    except:
        pass

    try:
        error_context.context("Make sure guest is running before test",
                              logging.info)
        vm.resume()
        vm.verify_status("running")

        try:
            cmd = "iptables"
            cmd += " -t filter"
            cmd += " -A INPUT"
            cmd += " -d %s" % host_ip
            cmd += " -m state"
            cmd += " --state NEW,RELATED,ESTABLISHED"
            cmd += " -p tcp"
            cmd += " --dport 2049"
            cmd += " -j REJECT"

            error_context.context("Reject NFS connection on host", logging.info)
            process.system(cmd)

            error_context.context("Check if VM status is 'paused'", logging.info)
            if not utils_misc.wait_for(
                lambda: check_vm_status(vm, "paused"),
                    int(params.get('wait_paused_timeout', 120))):
                test.error("Guest is not paused after stop NFS")
        finally:
            error_context.context("Accept NFS connection on host", logging.info)
            cmd = "iptables"
            cmd += " -t filter"
            cmd += " -D INPUT"
            cmd += " -d %s" % host_ip
            cmd += " -m state"
            cmd += " --state NEW,RELATED,ESTABLISHED"
            cmd += " -p tcp"
            cmd += " --dport 2049"
            cmd += " -j REJECT"

            process.system(cmd)

        error_context.context("Continue guest", logging.info)
        vm.resume()

        error_context.context("Check if VM status is 'running'", logging.info)
        if not utils_misc.wait_for(lambda: check_vm_status(vm, "running"), 20):
            test.error("Guest does not restore to 'running' status")

    finally:
        session.close()
        vm.destroy(gracefully=True)
        config.cleanup()
