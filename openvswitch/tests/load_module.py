import sys
import traceback
import logging
import six

from avocado.utils import process
from virttest import openvswitch
from virttest import versionable_class
from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    Run basic test of OpenVSwitch driver.
    """
    _e = None
    ovs = None
    try:
        try:
            error_context.context("Remove all bridge from OpenVSwitch.")
            ovs = versionable_class.factory(openvswitch.OpenVSwitchSystem)(test.tmpdir)
            ovs.init_system()
            ovs.check()
            for br in ovs.list_br():
                ovs.del_br(br)

            ovs.clean()

            for _ in range(int(params.get("mod_loaditer", 100))):
                process.run("modprobe openvswitch")
                process.run("rmmod openvswitch")

        except Exception:
            _e = sys.exc_info()
            raise
    finally:
        try:
            if ovs:
                if ovs.cleanup:
                    ovs.clean()
        except Exception:
            e = sys.exc_info()
            if _e is None:
                raise
            else:
                logging.error("Cleaning function raised exception too: \n" +
                              "".join(traceback.format_exception(e[0],
                                                                 e[1],
                                                                 e[2])))
                six.reraise(_e[0], _e[1], _e[2])
