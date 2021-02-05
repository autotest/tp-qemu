import logging
import re
import os
import shutil

from virttest import error_context
from virttest import data_dir
from avocado.utils import process
from avocado.utils import archive


@error_context.context_aware
def run(test, params, env):
    """
    Use tcpreplay to replay a pcap file, and check the guest is alive
    1) copy tcpreplay from deps directory
    2) compile the tcpreplay
    3) copy target pcap file from deps directory
    4) use the rcpreply to replay the pcap file to guest
    5) check the guest is still alive, no bsod occrued

    param test: test object
    param params: test params
    param env: test environment
    """

    def execute_host_cmd(host_cmd, timeout=60):
        """
        Execute the host_cmd on host, limited in timeout period

        param host_cmd: the host_cmd to run on host
        param timeout: the timeout for running this command
        return: the output of the host_cmd
        """
        logging.info("Executing host command: %s", host_cmd)
        cmd_result = process.run(host_cmd, timeout=timeout, shell=True)
        output = cmd_result.stdout_text
        return output

    def copy_file_from_deps(file_name, sub_dir, dst_dir="/tmp"):
        """
        Copy a file from deps directory

        param file_name: the file name
        param sub_dir: sub directory that contain the file
        param dst_dir: the target directory the file copied to
        """
        src_full_path = os.path.join(
            data_dir.get_deps_dir(sub_dir), file_name)
        dst_full_path = os.path.join(dst_dir, file_name)
        shutil.copyfile(src_full_path, dst_full_path)
        return dst_full_path

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    tcpreplay_dir = params.get("tcpreplay_dir", "tcpreplay")
    tcpreplay_file_name = params.get("tcpreplay_file_name")
    tcpreplay_compile_cmd = params.get("tcpreplay_compile_cmd")
    pcap_file_name = params.get("pcap_file_name")
    run_tcpreplay_cmd = params.get("run_tcpreplay_cmd")
    tmp_dir = params.get("tmp_dir", "/tmp")
    uncompress_dir = params.get("uncompress_dir")

    error_context.context("Copy %s to %s" % (tcpreplay_file_name, tmp_dir),
                          logging.info)
    tcpreplay_full_path = copy_file_from_deps(tcpreplay_file_name,
                                              tcpreplay_dir, tmp_dir)

    error_context.context("Compile tcpreplay", logging.info)
    uncompress_full_path = os.path.join(tmp_dir, uncompress_dir)

    logging.info("Remove old uncompress directory")
    shutil.rmtree(uncompress_full_path, ignore_errors=True)

    logging.info(
        "Uncompress %s to %s", tcpreplay_full_path, uncompress_full_path)
    uncompress_dir = archive.uncompress(
        tcpreplay_full_path, tmp_dir)
    if not uncompress_dir:
        test.error("Can't uncompress %s" % tcpreplay_full_path)

    logging.info("Compile files at %s", uncompress_full_path)
    execute_host_cmd(tcpreplay_compile_cmd % uncompress_full_path)

    error_context.context("Copy %s to %s" % (pcap_file_name, tmp_dir),
                          logging.info)
    copy_file_from_deps(pcap_file_name, tcpreplay_dir, tmp_dir)

    error_context.context("Run tcpreplay with pcap file", logging.info)
    output = execute_host_cmd(run_tcpreplay_cmd)
    result = re.search(r'Successful packets:\s+(\d+)', output)
    success_packet = 0
    if result:
        success_packet = int(result.group(1))
    if success_packet != 1:
        test.fail("tcpreplay result error with output: %s" % output)

    vm.verify_alive()
