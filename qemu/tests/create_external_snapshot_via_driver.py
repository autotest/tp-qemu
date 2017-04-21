import logging
import re
import shutil

from autotest.client.shared import error

from avocado.core import exceptions
from avocado.utils import process

from qemu.tests import qemu_disk_img_info


def run(test, params, env):

    """
    creat external snapshot using external drivers for backing file:
    1). Prepare enviroment of ssh/https
    2). Boot up vm and copy a file to it, then calculate its md5 value
    3). Create external snapshot using ssh/https driver
    4). Boot up vm using the external snapshot
    5). Calculate the file's md5 value again and then compare

    :param test: Kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def clean_key():
        process.system("rm -rf {}/id*".format(
            params.get("ssh_key_dir")), shell=True)

    @error.context_aware
    def create_ssh_test():

        """
        Prepare ssh environment
        :return: None
        """
        error.context("STEP 1: Prepare ssh login environment.")
        clean_key()
        copy_pub_key_cmd = params.get("copy_pub_key_cmd")
        logging.info("Create ssh key & copy it using ssh-copy-id")
        process.system(params.get("create_ssh_key_cmd"), shell=True)
        logging.info("Copy the ssh public key to remote host")
        process.system(copy_pub_key_cmd, shell=True)

    @error.context_aware
    def create_https_test():

        """
        Prepare https environment
        :return: None
        """
        error.context("STEP 1: Prepare https login environment.")
        process.system("yum install -y mod_ssl")
        logging.info("Start httpd service")
        process.system(params.get("http_conf_cmd"), shell=True)
        process.system(params.get("httpd_start_cmd"), shell=True)
        out = process.system_output(params.get("httpd_status_cmd"))
        if not re.search(params.get("httpd_status_re"), out):
            err = "Http server fails to start, because of {}".format(out)
            exceptions.TestError(err)

    subcommand = params.get("subcommand")
    eval("%s_test()" % subcommand)

    user_profile = ""
    user_profile_backup = ""
    if params.get("external_snapshot_driver") == "ssh":
        user_profile = params.get("user_profile")
        user_profile_backup = params.get("user_profile_backup")
        shutil.copy(user_profile, user_profile_backup)

    base_image = params.get("images", "image1").split()[0]
    params.update(
        {"image_name_%s" % base_image: params["image_name"],
         "image_format_%s" % base_image: params["image_format"]})
    t_file = params["guest_temp_file_%s" % base_image]
    snapshot_test = qemu_disk_img_info.InfoTest(
        test, params, env, base_image)
    logging.info("STEP 2: Save file md5sum before create snapshot.")
    snapshot_test.start_vm(params)
    md5_before_snapshot = snapshot_test.save_file(t_file)
    if not md5_before_snapshot:
        raise error.TestError("Fail to save tmp file.")
    snapshot_test.destroy_vm()

    logging.info("STEP 3: Start to create snapshot")
    snapshot_test_2 = qemu_disk_img_info.InfoTest(test, params, env, "sn1")
    n_params = snapshot_test_2.create_snapshot()
    if params.get("external_snapshot_driver") == "ssh":
        ssh_cfg = process.system_output("cat /root/.bash_profile", shell=True)
        ssh_sock = re.search("(SSH_AUTH_SOCK)=(.*?);", ssh_cfg)
        ssh_pid = re.search("(SSH_AGENT_PID)=(\d+);", ssh_cfg)
        command_prefix = "%s=%s;export %s;"
        command_prefix += "%s=%s;export %s;"
        ssh_auth_sock = ssh_sock.group(1)
        ssh_sock_path = ssh_sock.group(2)
        ssh_agent_pid = ssh_pid.group(1)
        ssh_pid_num = ssh_pid.group(2)

        n_params["qemu_command_prefix"] = command_prefix % (
            ssh_auth_sock,
            ssh_sock_path,
            ssh_auth_sock,
            ssh_agent_pid,
            ssh_pid_num,
            ssh_agent_pid)

    remove_https_proxy = params.get("remove_https_proxy")
    if params.get("external_snapshot_driver") == "https":
        n_params["qemu_command_prefix"] = "%s" % remove_https_proxy

    logging.info("STEP 4: Start vm using external snapshot created")
    snapshot_test.start_vm(n_params)
    output = snapshot_test.info()
    snapshot_test.check_backingfile(output)

    logging.info("STEP 5: Compare md5 value")
    t_file = params.get("guest_temp_file_%s" % "sn1")
    md5_after_snapshot = snapshot_test.check_file(t_file, md5_before_snapshot)
    if not md5_after_snapshot:
        raise error.TestError("Check md5sum fail (file:%s)" % t_file)
    snapshot_test.destroy_vm()

    if params.get("external_snapshot_driver") == "ssh":
        shutil.copy(user_profile_backup, user_profile)
        process.kill_process_by_pattern("ssh-agent")
        clean_key()

    snapshot_test.clean()

