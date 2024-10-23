"""
windows device and driver utility functions.

"""

import re

from virttest import error_context, utils_misc


@error_context.context_aware
def get_hwids(session, device_name, devcon_folder, timeout=300):
    """
    Return a list of hardware id of specific devices in a period of time.

    :param session: VM session
    :param device: Name of the specified device
    :param devcon_folder: Folder path for devcon.exe
    :param timeout: Timeout in seconds.
    :rtype: list
    """

    def _get_hwid_once():
        """
        Return a list of hardware id of specific devices according to device name.
        """
        hwid_cmd = "%sdevcon.exe find *" % devcon_folder
        output = session.cmd_output(hwid_cmd)
        return re.findall(hwid_pattern, output, re.M)

    hwid_pattern = r"(\S+)\s*:\s%s$" % device_name
    hwids = utils_misc.wait_for(_get_hwid_once, timeout, 0, 5)
    return hwids
