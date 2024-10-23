import os
import signal

from avocado.utils import process
from virttest import error_context, qemu_storage, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    1) Start tcpdump to capture the request
    2) Access libcurl image by qemu-img
    3) Wait till tcpdump finished
    4) tcpdump should catch the cookie data

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def _get_tcpdump_pid(dump_file):
        cmd = "ps -ef|grep tcpdump|grep %s|grep -v grep|awk '{print $2}'" % dump_file
        return process.system_output(cmd, shell=True, ignore_status=True).strip()

    def _wait_for_tcpdump_done(dump_file):
        response_timeout = params.get_numeric("response_timeout", 10)
        if not utils_misc.wait_for(
            lambda: not _get_tcpdump_pid(dump_file), response_timeout, 0, 1
        ):
            test.fail("tcpdump is running unexpectedly")

    def _cleanup(dump_file):
        if os.path.exists(dump_file):
            os.unlink(dump_file)

        pid = _get_tcpdump_pid(dump_file)
        if pid:
            os.kill(int(pid), signal.SIGKILL)

    tag = params["remote_image_tag"]
    img_params = params.object_params(tag)
    img_obj = qemu_storage.QemuImg(img_params, None, tag)
    dump_file = utils_misc.generate_tmp_file_name("%s_access_tcpdump" % tag, "out")

    test.log.info("start tcpdump, save packets in %s", dump_file)
    process.system(
        params["tcpdump_cmd"].format(
            server=img_params["curl_server"], dump_file=dump_file
        ),
        shell=True,
        ignore_status=True,
        ignore_bg_processes=True,
    )

    try:
        img_obj.info()
        _wait_for_tcpdump_done(dump_file)
        with open(dump_file, "rb") as fd:
            for line in fd:
                line = line.decode("utf-8", "ignore")
                if "Cookie: %s" % img_params["curl_cookie_secret"] in line:
                    test.log.info(
                        'get "%s" from "%s"', img_params["curl_cookie_secret"], line
                    )
                    break
            else:
                test.fail("Failed to get cookie data from tcpdump output")
    finally:
        _cleanup(dump_file)
