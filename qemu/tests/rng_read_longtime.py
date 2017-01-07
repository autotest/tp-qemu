import time
from virttest import utils_test


def run(test, params, env):
    """
    1) boot guest with virtio-rng device
    2) check host random device opened by qemu (optional)
    3) enable driver verifier in guest
    4) read random data from guest
    5) repeat step2 ~ step4 10 hours (can be set)
    """
    login_timeout = int(params.get("login_timeout", 360))
    sub_test = params.get("sub_test")
    test_duration = float(params.get("test_duration", "3600"))
    rng_data_rex = params.get("rng_data_rex", r".*")
    read_rng_timeout = float(params.get("read_rng_timeout", "360"))

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=login_timeout)

    read_rng_cmd = utils_misc.set_winutils_letter(
        session, params["read_rng_cmd"])
    start_time = time.time()
    while (time.time() - start_time) < test_duration:
        output = session.cmd_output(read_rng_cmd, timeout=read_rng_timeout)
        if len(re.findall(rng_data_rex, output, re.M)) < 2:
            raise exceptions.TestFail("Unable to read random numbers from"
                                      "guest: %s" % output)

