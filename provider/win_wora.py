"""
windows workaround functions.

"""

import logging
import re

from virttest import error_context, utils_misc

LOG_JOB = logging.getLogger("avocado.test")


@error_context.context_aware
def modify_driver(params, session):
    """
    Add a workaround for win2016 guest to solve the issue that
    "HID Button over Interrupt Driver" does occupy hot-added cpu's driver,
    cause the system cannot detected new added cpu, need modify the driver.
    issue details please refer to:
    https://support.huawei.com/enterprise/zh/doc/EDOC1100034211/5ba99a60.
    """
    devcon_path = utils_misc.set_winutils_letter(session, params["devcon_path"])
    dev_hwid = params["dev_hwid"]
    chk_cmd = "%s find %s" % (devcon_path, dev_hwid)
    chk_pat = r"ACPI\\ACPI0010.*\: Generic Bus"
    if not re.search(chk_pat, session.cmd(chk_cmd)):
        error_context.context(
            "Install 'HID Button over Interrupt Driver' " "to Generic Bus", LOG_JOB.info
        )
        inst_cmd = "%s install %s %s" % (
            devcon_path,
            params["driver_inf_file"],
            dev_hwid,
        )
        if session.cmd_status(inst_cmd, timeout=60):
            LOG_JOB.error("'HID Button over Interrupt Driver' modify failed")
    LOG_JOB.info("'HID Button over Interrupt Driver' modify finished")
