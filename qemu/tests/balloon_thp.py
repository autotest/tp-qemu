import time

from virttest import funcatexit, utils_misc
from virttest.staging import utils_memory


def clean_env(session, file_name):
    """
    Clean the file created inside guest
    :param session: The vm session
    :param file_name: The file name
    """
    session.cmd_output_safe("rm -rf %s" % file_name)


def run(test, params, env):
    """
    Memory balloon with thp

    1. Boot up a guest with balloon support, record memory fragement
    2. Make fragement in guest with tmpfs
    3. check the memory fragement with proc system, should increase
    4. Do memory balloon the memory size ballooned should be a legal value
    5. Check the memory fragement with proc system, should decrease

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def get_buddy_info(sleep=False):
        """Get buddy info"""
        if sleep:
            time.sleep(10)
        buddy_info = utils_memory.get_buddy_info("0", session=session)["0"]
        test.log.info("Checked buddy info, value is %s", buddy_info)
        return buddy_info

    fragement_dir = params["fragement_dir"]
    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()
    buddy_info_bf = get_buddy_info()
    test.log.info("Making fragement on guest...")
    session.cmd_output_safe(params["cmd_make_fragement"], timeout=600)
    for i in range(1, 10, 2):
        session.cmd_output_safe("rm -f %s/*%s" % (fragement_dir, i))
    funcatexit.register(env, params["type"], clean_env, session, fragement_dir)
    buddy_info_af_fragement = get_buddy_info(sleep=True)
    if buddy_info_bf >= buddy_info_af_fragement:
        test.fail("Buddy info should increase.")
    mem = int(float(utils_misc.normalize_data_size("%sM" % params["mem"])))
    vm.balloon(mem - 1024)
    buddy_info_af_balloon = get_buddy_info(sleep=True)
    if buddy_info_af_balloon >= buddy_info_af_fragement:
        test.fail("Buddy info should decrease.")
