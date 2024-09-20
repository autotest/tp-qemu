import locale
import logging
import subprocess
import sys
import time

import pexpect
from six import string_types

nic1_driver = sys.argv[1]
nic2_driver = sys.argv[2]
whitelist_option = sys.argv[3]
nic1 = sys.argv[4]
nic2 = sys.argv[5]
cores = int(sys.argv[6])
queues = int(sys.argv[7])
running_time = int(sys.argv[8])

ENCODING = locale.getpreferredencoding()


class TestPMD(object):
    def __init__(self):
        self.proc = None
        testpmd_cmd = subprocess.check_output(
            "rpm -ql dpdk |grep testpmd", shell=True
        ).decode()
        self.testpmd_exec = testpmd_cmd

    def launch(
        self, nic1_driver, nic2_driver, whitelist_option, nic1, nic2, cores, queues
    ):
        cmd = (
            "-l 1,2,3 -n 4 -d %s -d %s"
            " %s %s %s %s "
            " -- "
            " -i --nb-cores=%d "
            " --disable-rss --rxd=512 --txd=512 "
            " --rxq=%d --txq=%d"
            % (
                nic1_driver,
                nic2_driver,
                whitelist_option,
                nic1,
                whitelist_option,
                nic2,
                cores,
                queues,
                queues,
            )
        )
        cmd_str = self.testpmd_exec + cmd
        logging.info("[cmd] %s", cmd_str)
        try:
            self.proc = pexpect.spawn(cmd_str)
            self.proc.expect("testpmd>")
        except pexpect.ExceptionPexpect as e:
            logging.error(e)
            return False

    def start(self):
        self.command("start")

    def stop(self):
        self.command("stop")

    def quit(self):
        self.proc.sendline("quit")
        logging.info("testpmd> quit")
        print("testpmd> quit")
        self.proc.expect("Bye...")
        logging.info(self.proc.before)
        line_list = to_text(self.proc.before).split("\n")
        for subline in line_list:
            if len(subline.strip()) > 0:
                print(subline)
        return to_text(self.proc.before)

    def set_port_stats(self):
        self.command("show port stats all")

    def set_portlist(self, portlist):
        self.command("set portlist %s" % portlist)

    def get_config_fwd(self):
        self.command("show config fwd")

    def set_fwd_mac_retry(self):
        self.command("set fwd mac retry")

    def set_vlan_0(self):
        self.command("vlan set strip on 0")

    def set_vlan_1(self):
        self.command("vlan set strip on 1")

    def command(self, cmd):
        self.proc.sendline(cmd)
        self.proc.expect("testpmd>")
        logging.info("testpmd> %s", cmd)
        print("testpmd> %s" % cmd)
        logging.info(self.proc.before)
        line_list = to_text(self.proc.before).split("\n")
        for subline in line_list:
            if len(subline.strip()) > 0:
                print(subline)

        return to_text(self.proc.before)


def start_testpmd(
    nic1_driver, nic2_driver, whitelist_option, nic1, nic2, cores, queues
):
    my_testpmd = TestPMD()
    my_testpmd.launch(
        nic1_driver=nic1_driver,
        nic2_driver=nic2_driver,
        whitelist_option=whitelist_option,
        nic1=nic1,
        nic2=nic2,
        cores=cores,
        queues=queues,
    )

    my_testpmd.set_fwd_mac_retry()
    my_testpmd.set_vlan_0()
    my_testpmd.set_vlan_1()

    my_testpmd.start()
    my_testpmd.set_port_stats()

    # testmpd will quit after running_time
    start_time = time.time()
    end_time = start_time + running_time
    while time.time() < end_time:
        time.sleep(10)
        print("time.time=%s" % time.time)
    my_testpmd.stop()
    my_testpmd.set_port_stats()
    my_testpmd.quit()


def to_text(data):
    """
    Convert anything to text decoded text

    When the data is bytes, it's decoded. When it's not of string types
    it's re-formatted into text and returned. Otherwise (it's string)
    it's returned unchanged.

    :param data: data to be transformed into text
    :type data: either bytes or other data that will be returned
                unchanged
    """
    if isinstance(data, bytes):
        return data.decode(ENCODING)
    elif not isinstance(data, string_types):
        return str(data)
    return data


start_testpmd(nic1_driver, nic2_driver, whitelist_option, nic1, nic2, cores, queues)
