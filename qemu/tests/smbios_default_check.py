import re

from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    Check default smbios strings in qemu :
    1) Boot guest with default smbios set up
    2) Verify if bios info have been emulated correctly

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def check_info(cmd, template):
        msg_log = "Check " + template + " info"
        error_context.context(msg_log, test.log.info)
        cmd_output = session.cmd_output(cmd)
        cmd_output_re = re.split("\n", cmd_output.strip("\n"))[-1].strip(" ")
        template = params[template]
        if not re.match(template, cmd_output_re):
            return cmd_output_re

    re_template = [
        "System_Manufacturer",
        "System_SKU_Number",
        "Baseboard_Manufacturer",
        "Baseboard_Product_Name",
    ]

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)

    failures = []
    check_info_cmd = []
    check_info_cmd.append(params["get_sys_manufacturer"])
    check_info_cmd.append(params["get_sys_SKUNumber"])
    check_info_cmd.append(params["get_baseboard_manufacturer"])
    check_info_cmd.append(params["get_baseboard_product_name"])
    for cmd, template in zip(check_info_cmd, re_template):
        output = check_info(cmd, template)
        if output:
            e_msg = "%s mismatch, out: %s" % (template, output)
            failures.append(e_msg)
    session.close()

    if failures:
        test.fail(
            "Smbios default check test reported %s failures:\n%s"
            % (len(failures), "\n".join(failures))
        )
