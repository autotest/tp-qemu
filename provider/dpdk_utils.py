import re
import subprocess
import sys

# Ensure paramiko is installed
for pip in ["pip3", "pip"]:
    try:
        subprocess.check_call([pip, "install", "--default-timeout=100", "paramiko"])
        import paramiko

        break
    except ImportError:
        continue
else:
    print("Failed to install paramiko. Please install it manually.")
    sys.exit(1)


def install_dpdk(params, session):
    """
    Install the dpdk related packages.

    :param params: Dictionary with the test parameters
    :param session: the session of guest or host
    """

    cmd = "yum install -y %s" % params.get("env_pkg")
    session.cmd(cmd, timeout=360, ignore_all_errors=True)


def load_vfio_modules(session):
    """
    Load vfio and vfio-pci modules.

    :param session: the session of guest or host
    """

    if session.cmd_status("lsmod | grep -wq vfio"):
        session.cmd("modprobe -r vfio-pci")
        print("vfio-pci module removed")

    if session.cmd_status("lsmod | grep -wq vfio_pci"):
        session.cmd("modprobe -r vfio")
        print("vfio module removed")

    session.cmd_output("modprobe vfio enable_unsafe_noiommu_mode=Y")
    print("vfio module loaded")

    session.cmd_output("modprobe vfio-pci")
    print("vfio-pci module loaded")


def bind_pci_device_to_vfio(session, pci_id):
    """
    Bind PCI device to vfio-pci.

    :param session: the session of guest or host
    :param pci_id: PCI ID of the device to bind
    """

    cmd = "dpdk-devbind.py --bind=vfio-pci %s" % pci_id
    status, output = session.cmd_status_output(cmd)
    if status == 0:
        print("PCI device %s bound to vfio-pci successfully." % pci_id)
    elif "already bound to driver vfio-pci" in output:
        print("PCI device %s is already bound to vfio-pci." % pci_id)
    else:
        print("Failed to bind PCI device %s to vfio-pci" % pci_id)


class TestPMD:
    def __init__(self, host, username, password):
        """
        Initialize TestPMD class.

        :param host: Hostname or IP address of the target machine
        :param username: Username for SSH login
        :param password: Password for SSH login
        """

        self.host = host
        self.username = username
        self.password = password
        self.session = None
        self.dpdk_channel = None

    def _expect_prompt(self, timeout=10):
        """
        Wait for the testpmd prompt.

        :param timeout: Maximum time to wait for the prompt
        :return: Output received from the channel
        """

        output = ""
        while True:
            data = self.dpdk_channel.recv(16384).decode()
            output += data
            print(data, end="")

            if "testpmd>" in output:
                return output

    def extract_pps_value(self, output, forward_mode):
        """
        Extract the pps value from the dpdk output based on the forward mode.

        :param output: The pps value from dpdk output.
        :param forward_mode: forward_mode, either "txonly" or "rxonly".
        :return: pps value as an integer.
        """

        if forward_mode == "txonly":
            pps = re.search(r"Tx-pps:\s+(\d+)", output).group(1)
        elif forward_mode == "rxonly":
            pps = re.search(r"Rx-pps:\s+(\d+)", output).group(1)
        else:
            raise ValueError(f"unexpected forward mode: {forward_mode}")
        return int(pps)

    def login(self):
        """
        Login to the target machine using SSH.

        :return: SSH session if successful, None otherwise
        """

        self.session = paramiko.SSHClient()
        self.session.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            self.session.connect(
                self.host, username=self.username, password=self.password
            )
            print("Successfully logged in to %s." % self.host)
            return self.session
        except paramiko.AuthenticationException:
            print("Failed to authenticate with SSH on %s." % self.host)
        except paramiko.SSHException as e:
            print("SSH error occurred while connecting to %s: %s" % (self.host, str(e)))
        except paramiko.ssh_exception.NoValidConnectionsError:
            print("Failed to connect to %s." % self.host)
        except Exception as e:
            print("Error occurred while logging in to %s: %s" % (self.host, str(e)))

    def launch_testpmd(
        self, dpdk_tool_path, cpu_cores, pci_id, forward_mode, queue, pkts, mac=None
    ):
        """
        Launch the testpmd tool with the specified parameters.

        :param dpdk_tool_path: Path to the dpdk tool
        :param cpu_cores: Number of CPU cores to use
        :param pci_id: PCI ID of the device to test
        :param forward_mode: Forwarding mode (e.g., 'txonly')
        :param queue: Number of queues
        :param pkts: Number of packets
        :param mac: MAC address (optional)
        """

        base_cmd = (
            "{} -l 0-{} -a {} --file-prefix {} -- "
            "--port-topology=chained --disable-rss -i "
            "--rxq={} --txq={} --rxd=256 --txd=256 "
            "--nb-cores={} --burst=64 --auto-start "
            "--forward-mode={} --{}pkts={} "
        )

        eth_peer = "--eth-peer={} ".format(mac) if mac else ""

        cmd = (
            base_cmd.format(
                dpdk_tool_path,
                int(cpu_cores) - 1,
                pci_id,
                "tx" if forward_mode == "txonly" else "rx",
                queue,
                queue,
                int(cpu_cores) - 1,
                forward_mode,
                "tx" if forward_mode == "txonly" else "rx",
                pkts,
            )
            + eth_peer
        )

        if forward_mode == "txonly":
            cmd += "--txonly-multi-flow "

        # Open an interactive shell session
        self.dpdk_channel = self.session.invoke_shell()

        # Send the command to the shell
        self.dpdk_channel.send(cmd + "\n")
        self._expect_prompt()

    def show_port_stats_all(self):
        """
        Show port statistics for all ports.

        :return: Output containing port statistics
        """

        self.dpdk_channel.sendall("show port stats all\n")
        output = self._expect_prompt()

        return output

    def quit_testpmd(self):
        """
        Quit the testpmd tool.
        """

        self.dpdk_channel.sendall("quit\n")

    def logout(self):
        """
        Logout from the SSH session.
        """

        if self.session:
            self.session.close()
