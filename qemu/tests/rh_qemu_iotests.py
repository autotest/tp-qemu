import os
import re

from avocado.core import exceptions
from avocado.utils import process
from virttest import error_context, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    Get qemu src code from src rpm and run qemu-iotests using the
    qemu binaries.

    1) Download src rpm from brew
    2) Unpack src code and apply patches
    3) Run test for the file format detected
    4) Check result

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """

    def retry_command(cmd):
        """
        Retry the command when it fails, and raise the error once
        retry has exceeded the maximum number

        :param cmd: command expect to be executed
        :return: output of the command
        """
        max_retry = int(params.get("max_retry", 3))
        retry = max_retry
        while retry:
            retry -= 1
            try:
                return process.system(cmd, shell=True)
            except process.CmdError as detail:
                msg = "Fail to execute command"
                test.log.error("%s: %s.", msg, detail)
                raise exceptions.TestError(
                    "%s after %s times retry: %s" % (msg, max_retry, detail)
                )

    def install_test(build_root):
        """
        Download src rpm, unpack src code and applying patches

        :param build_root: build path of rpmbuild
        :return: A tuple containing directory of qemu source code
                 and qemu-kvm spec
        """
        error_context.context("Get qemu source code", test.log.info)
        os.chdir(test.tmpdir)
        query_format = params["query_format"]
        download_rpm_cmd = params["download_rpm_cmd"]
        get_src_cmd = params["get_src_cmd"]
        qemu_spec = params.get("qemu_spec", "SPECS/qemu-kvm.spec")
        get_rpm_name_cmd = "rpm -qf %s --queryformat=%s" % (
            utils_misc.get_qemu_binary(params),
            query_format,
        )
        src_rpm_name = process.system_output(get_rpm_name_cmd, shell=True)
        retry_command(download_rpm_cmd % src_rpm_name)
        spec = os.path.join(build_root, qemu_spec)
        build_dir = os.path.join(build_root, "BUILD")
        cmd = get_src_cmd % (src_rpm_name, spec)
        process.system(cmd, shell=True)
        src_dir = os.listdir(build_dir)[0]
        return (os.path.join(build_dir, src_dir), spec)

    def config_test(qemu_src_dir):
        """
        Generate common.env for test

        :qemu_src_dir: path of qemu source code
        """
        need_run_configure = params.get("need_run_configure", "no")
        if need_run_configure == "yes":
            make_socket_scm_helper = params.get("make_socket_scm_helper", "")
            test.log.info("Generate common.env")
            os.chdir(qemu_src_dir)
            cmd = "./configure"
            if make_socket_scm_helper:
                cmd += " %s" % make_socket_scm_helper
            process.system(cmd, shell=True)

    def run_test(qemu_src_dir):
        """
        run QEMU I/O test suite

        :qemu_src_dir: path of qemu source code
        """
        iotests_root = params.get("iotests_root", "tests/qemu-iotests")
        extra_options = params.get("qemu_io_extra_options", "")
        image_format = params.get("qemu_io_image_format")
        result_pattern = params.get("iotests_result_pattern")
        error_context.context(
            "running qemu-iotests for image format %s" % image_format, test.log.info
        )
        os.environ["QEMU_PROG"] = utils_misc.get_qemu_binary(params)
        os.environ["QEMU_IMG_PROG"] = utils_misc.get_qemu_img_binary(params)
        os.environ["QEMU_IO_PROG"] = utils_misc.get_qemu_io_binary(params)
        os.environ["QEMU_NBD_PROG"] = utils_misc.get_binary("qemu-nbd", params)
        os.chdir(os.path.join(qemu_src_dir, iotests_root))
        cmd = "./check"
        if extra_options:
            cmd += " %s" % extra_options
        cmd += " -%s" % image_format
        output = process.system_output(cmd, ignore_status=True, shell=True)
        match = re.search(result_pattern, output, re.I | re.M)
        if match:
            iotests_log_file = "qemu_iotests_%s.log" % image_format
            iotests_log_file = utils_misc.get_path(test.debugdir, iotests_log_file)
            with open(iotests_log_file, "w+") as log:
                log.write(output)
                log.flush()
            msg = "Total test %s cases, %s failed"
            raise exceptions.TestFail(msg % (match.group(2), match.group(1)))

    build_root = params.get("build_root", "/root/rpmbuild")
    rpmbuild_clean_cmd = params["rpmbuild_clean_cmd"]
    cmd = "%s -version" % utils_misc.get_qemu_binary(params)
    output = process.system_output(cmd, shell=True)
    cwd = os.getcwd()
    (qemu_src_dir, spec) = install_test(build_root)
    try:
        if "qemu-kvm-rhev" in output:
            config_test(qemu_src_dir)
        run_test(qemu_src_dir)
    finally:
        try:
            os.chdir(cwd)
            process.system(rpmbuild_clean_cmd % spec, shell=True)
        except Exception:
            test.log.warning("Fail to clean test environment")
