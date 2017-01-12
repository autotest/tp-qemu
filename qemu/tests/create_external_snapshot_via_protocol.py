import os
import re
import logging
import subprocess

from avocado.core import exceptions
from avocado.utils import process

from qemu.tests import qemu_disk_img

from virttest import error_context


def run(test, params, env):

    """
    creat external snapshot using external drivers for backing file:
    1). Prepare environment of ssh/https
    2). Boot up vm and copy a file to it, then calculate its md5 value
    3). Create external snapshot using ssh/https driver
    4). Boot up vm using the external snapshot
    5). Calculate the file's md5 value again and then compare

    :param test: Kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def clean_key():

        """
        clear the ssh key
        :return: None
        """
        process.system("rm -rf {}/id*".format(
            params["ssh_key_dir"]), shell=True)

    @error_context.context_aware
    def setup_env_for_ssh():

        """
        Prepare ssh environment
        :return: None
        """
        error_context.context(
            "STEP 1: Prepare ssh login environment.", logging.info)
        copy_pub_key_cmd = params.get("copy_pub_key_cmd")
        logging.info("Create ssh key & copy it using ssh-copy-id")
        process.system(params["create_ssh_key_cmd"], shell=True)
        logging.info("Copy the ssh public key to remote host")
        process.system(copy_pub_key_cmd, shell=True)
        ssh_env = subprocess.check_output(["ssh-agent"]).decode("utf-8")
        ssh_env = ssh_env.replace('\n', '')
        process.system("%s ssh-add" % ssh_env, shell=True)
        for key in params:
            if (key.startswith('image_json_file.driver') and params[key] == "ssh"):
                tag = key.split('_')[-1]
                params.update(
                    {"qemu_img_command_prefix_%s" % tag: ssh_env,
                     "qemu_command_prefix_%s" % tag: ssh_env})

    @error_context.context_aware
    def setup_env_for_https():

        """
        Prepare https environment
        :return: None
        """
        error_context.context(
            "STEP 1: Prepare https environment.", logging.info)
        process.system(params["install_mod_ssl_cmd"], shell=True)
        logging.info("Start httpd service")
        process.system(params.get("http_conf_cmd"), shell=True)
        process.system(params.get("httpd_start_cmd"), shell=True)
        out = process.system_output(params.get("httpd_status_cmd"), shell=True)
        if not re.search(params.get("httpd_status_re"), out):
            err = "Http server fails to start, because of {}".format(out)
            exceptions.TestError(err)

    subcommand = params["subcommand"]
    sub_test = "%s" % subcommand
    try:
        fun_test = locals()[sub_test]()
    except (KeyError, TypeError):
        raise exceptions.TestError(
            "Sub-test '%s' not define in test case" % sub_test)

    snapshot_test = ""
    check_files = []
    md5_dict = {}
    image_chain = params.get("image_chain", "").split()

    base_image = params.get("images", "image1").split()[0]
    params.update(
        {"image_name_%s" % base_image: params["image_name"],
         "image_format_%s" % base_image: params["image_format"]})
    t_file = params["guest_file_name_%s" % base_image]

    try:
        for idx, tag in enumerate(image_chain):
            params["image_chain"] = " ".join(image_chain[:idx + 1])
            t_params = params.object_params(tag)
            if t_params.get("image_json_file.driver") == "ssh":
                t_params["image_json_file.path"] = base_image_filename
            if t_params.get("image_json_file.driver") == "https":
                url = t_params.get("image_json_file.url")
                url = url.format(os.path.basename(base_image_filename))
                t_params["image_json_file.url"] = url
            for k in [key for key in t_params.keys()
                      if key.startswith('image_json_file.driver_')]:
                del t_params[k]
            snapshot_test = qemu_disk_img.QemuImgTest(
                test, t_params, env, tag)
            base_image_filename = snapshot_test.image_filename

            n_params = snapshot_test.create_snapshot()
            snapshot_test.start_vm(n_params)

            for _file in check_files:
                ret = snapshot_test.check_file(_file, md5_dict[_file])
                if not ret:
                    raise exceptions.TestError(
                        "Check md5sum fail (file:%s)" % t_file)

            t_file = params["guest_file_name_%s" % tag]
            md5 = snapshot_test.save_file(t_file)
            if not md5:
                raise exceptions.TestFail("Fail to save tmp file")
            check_files.append(t_file)
            md5_dict[t_file] = md5
            snapshot_test.destroy_vm()
            snapshot_test.check_backingfile()
    finally:
        snapshot_test.clean()
        if [key for key in params.keys() if key.startswith('qemu_img_command_prefix')]:
            clean_key()
            process.kill_process_by_pattern("ssh-agent")
