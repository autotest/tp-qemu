import logging
import time
import re

from virttest import utils_disk
from virttest import utils_misc


def run(test, params, env):
    """
    Test the performance improvement with option:queue-size/num-queues

    1) Boot guest with two disk that with different option set
    2) Format the disk
    3) Use dd to test disk performance
    4) Compare the result of two disk

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def get_disk_op_cmd(disk_op_cmd, disk_size):
        """
        Find the disk driver letter and format the disk, and get
        disk driver letter,return disk_op_command
        """
        if os_type == "windows":
            disk_op_cmd = utils_misc.set_winutils_letter(session, disk_op_cmd)
            logging.info("Get windows disk index that to be formatted")
            disk_id = utils_disk.get_windows_disks_index(session, disk_size)
            if not utils_disk.update_windows_disk_attributes(session, disk_id):
                test.error("Failed to enable data disk %s" % disk_id)
            d_letter = utils_disk.configure_empty_windows_disk(session,
                                                               disk_id[0],
                                                               disk_size)[0]
            output_path = d_letter + ":\\test.dat"
        else:
            disks = utils_disk.get_linux_disks(session)
            for key, value in disks.items():
                if value[1] == disk_size and value[2] == "disk":
                    output_path = key
        if not output_path:
            test.fail("Can not get output file path in guest.")
        disk_op_cmd %= output_path
        return disk_op_cmd

    def dd_test(stg0_dd_cmd, stg1_dd_cmd):
        """
        run the dd command and compare the results of the two disks,
        and then return the comparison result
        """
        stg0_result = 0.0
        stg1_result = 0.0
        for i in range(6):
            stg0_output = session.cmd_output(stg0_dd_cmd, timeout=cmd_timeout)
            time.sleep(5)
            stg1_output = session.cmd_output(stg1_dd_cmd, timeout=cmd_timeout)
            time.sleep(5)
            # Discard first test result to get a more accurate result
            if i != 0:
                stg0_result += extract_time_from_output(stg0_output)
                stg1_result += extract_time_from_output(stg1_output)
        return stg0_result, stg1_result

    def extract_time_from_output(output):
        """
        extract time from output
        """
        if os_type == "linux":
            output = output.split("\n")[2]
            time_spend = re.search(r"\d*.\d* s", output).group().split(" ")[0]
        elif os_type == "windows":
            output = output.split("\n")[4]
            time_spend = output.split(" ")[2]
        return float(time_spend)

    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()
    # Wait 2 minutes then start the testing due to wait some sevices begining
    time.sleep(60)

    os_type = params["os_type"]
    stg0_disk_size = params["image_size_stg0"]
    stg1_disk_size = params["image_size_stg1"]
    stg2_disk_size = params["image_size_stg2"]
    dd_cmd = params["dd_cmd"]
    cmd_timeout = int(params["dd_cmd_timeout"])

    stg0_dd_cmd = get_disk_op_cmd(dd_cmd, stg0_disk_size)
    stg1_dd_cmd = get_disk_op_cmd(dd_cmd, stg1_disk_size)
    if params.get("check_default_mp", 'no') == 'yes':
        check_default_mp_cmd = params["check_default_mp_cmd"]
        check_default_mp_cmd = get_disk_op_cmd(check_default_mp_cmd,
                                               stg2_disk_size)
        output = session.cmd_output(check_default_mp_cmd)
        output = output.split('\n')[0]
        default_mq_nums = len(re.split(r"[ ]+", output))
        if default_mq_nums != int(params["vcpu_maxcpus"]):
            test.fail("Default num-queue value(%s) not equal vcpu nums(%s)"
                      % (default_mq_nums, int(params["vcpu_maxcpus"])))
    stg0_result, stg1_result = dd_test(stg0_dd_cmd, stg1_dd_cmd)
    if stg0_result < stg1_result:
        test.fail("The result are not as expected.Stg0 dd test spend time is "
                  "%s,stg1 disk dd test spend time is %s"
                  % (stg0_result, stg1_result))
