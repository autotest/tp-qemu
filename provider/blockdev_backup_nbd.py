from avocado.utils import network
from avocado.utils import process

from virttest import data_dir

from provider import backup_utils
from provider import blockdev_base


class BlockdevBackupNbdBaseTest(blockdev_base.BlockdevBaseTest):

    def __init__(self, test, params, env):
        super(
            BlockdevBackupNbdBaseTest,
            self).__init__(
            test,
            params,
            env)
        self.nbd_server_info = None
        self.nbd_nodes = []

    def start_nbd_server(self):
        self.nbd_server_info = backup_utils.start_nbd_server(self.main_vm)

    def stop_nbd_server(self):
        backup_utils.stop_nbd_server(self.main_vm)
        self.nbd_server_info = None

    def expose_blockdev(self, node_name, bitmap=None):
        if not self.nbd_server_info:
            self.start_nbd_server()
        backup_utils.add_nbd_server(self.main_vm, node_name, bitmap=bitmap)
        self.nbd_nodes.append(node_name)

    def unexpose_blockdev(self, node_name):
        backup_utils.remove_nbd_server(self.main_vm, node_name)
        if node_name in self.nbd_nodes:
            self.nbd_nodes.remove(node_name)

    def pull_backup_data(self, source_name, target_file, bitmap=None):
        """
        Get blockdev backup data via nbd server

        :param source_name: source device node-name or image tag
        :param target_file: target image filename
        :param bitmap: bitmap name
        """
        sh_file = "%s/copyif3.sh" % data_dir.get_deps_dir()
        host = self.nbd_server_info['host']
        port = self.nbd_server_info['port']
        temp_cmd = "{sh_file} nbd://{host}:{port}/{source} {target} {bitmap}"
        if not bitmap:
            bitmap = ""
        pull_cmd = temp_cmd.format(sh_file=sh_file,
                                   host=host,
                                   port=port,
                                   source=source_name,
                                   target=target_file,
                                   bitmap=bitmap)
        return process.system(pull_cmd, shell=True, ignore_status=False)

    def prepare_test(self):
        super(BlockdevBackupNbdBaseTest, self).prepare_test()
        self.start_nbd_server()

    def cleanup_nbd_env(self):
        if not self.nbd_server_info:
            return
        host = self.nbd_server_info['data']['host']
        port = self.nbd_server_info['data']['port']
        if network.is_port_free(int(port), host):
            return
        for node in self.nbd_nodes:
            self.unexpose_blockdev(node)
        self.stop_nbd_server()

    def post_test(self):
        self.cleanup_nbd_env()
        super(BlockdevBackupNbdBaseTest, self).post_test()
