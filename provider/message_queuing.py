import logging

from aexpect import client


DEFAULT_MONITOR_TIMEOUT = 60


class MessageNotFoundError(Exception):
    def __init__(self, message, output):
        Exception.__init__(self, message, output)
        self.message = message
        self.output = output

    def __str__(self):
        return ('No matching message("{}") was found. '
                'Output: {}'.format(self.message, self.output))


class UnknownEventError(Exception):
    def __init__(self, event):
        self.event = event

    def __str__(self):
        return 'Got unknown event: "{}"'.format(self.event)


class MQBase(client.Expect):
    def __init__(self, cmd):
        """
        The base class used to MQ(message queuing).

        :param cmd: The MQ command line.
        """
        super(MQBase, self).__init__(cmd)
        logging.info("MQ command line: %s", self.command)

    def _confirm_message(self, message):
        """
        Send a message to the MQ screen.

        :param message: The message you need to send.
        """
        self.sendline('CONFIRM-' + message)

    def _monitor_message(self, message, timeout=DEFAULT_MONITOR_TIMEOUT):
        """
        Monitor a specified message from the MQ screen.

        :param message: The message you need to monitor.
        :param timeout: The duration to wait until a match is found.
        """
        try:
            self.read_until_last_line_matches([message], timeout)
            logging.info('The message "{}" has been monitored.'.format(message))
        except client.ExpectTimeoutError as err:
            raise MessageNotFoundError(message, err.output)

    def _monitor_confirm_message(self, message,
                                 timeout=DEFAULT_MONITOR_TIMEOUT):
        return self._monitor_message('CONFIRM-' + message, timeout)

    def close(self):
        """
        Check and close the message queuing environment.
        """
        if self.is_alive():
            self.send_ctrl('^C')
        super(MQBase, self).close()


class MQPublisher(MQBase):
    def __init__(self, port=None, udp=False, multiple_connections=False):
        """
        MQ publisher.

        :param port: Specify source port to use.
        :param udp: Use UDP instead of default TCP.
        :param multiple_connections: Accept multiple connections in listen mode.
        """
        cmd_options = ['nc', '-l']
        port and cmd_options.append('-p ' + str(port))
        udp and cmd_options.append('--udp')
        multiple_connections and cmd_options.append('--keep-open')
        super(MQPublisher, self).__init__(' '.join(cmd_options))

    def confirm_access(self, timeout=DEFAULT_MONITOR_TIMEOUT):
        self._monitor_message('ACCESS', timeout)
        self._confirm_message('ACCESS')

    def approve(self, timeout=DEFAULT_MONITOR_TIMEOUT):
        self.sendline('APPROVE')
        self._monitor_confirm_message('APPROVE', timeout)

    def notify(self, timeout=DEFAULT_MONITOR_TIMEOUT):
        self.sendline('NOTIFY')
        self._monitor_confirm_message('NOTIFY', timeout)

    def alert(self, timeout=DEFAULT_MONITOR_TIMEOUT):
        self.sendline('ALERT')
        self._monitor_confirm_message('ALERT', timeout)

    def refuse(self, timeout=DEFAULT_MONITOR_TIMEOUT):
        self.sendline('REFUSE')
        self._monitor_message('REFUSE', timeout)


class MQSubscriber(MQBase):
    def __init__(self, server_address, port=None, udp=False):
        """
        MQ subscriber.

        :param server_address: The address of remote/local MQ server.
        :param port: The listening port of the MQ server.
        :param udp: Use UDP instead of default TCP.
        """
        cmd_options = ['nc', server_address]
        port and cmd_options.append(str(port))
        udp and cmd_options.append('--udp')
        super(MQSubscriber, self).__init__(' '.join(cmd_options))
        self._access()

    def _access(self):
        self.sendline('ACCESS')
        self._monitor_confirm_message('ACCESS')

    def confirm_approve(self):
        self._confirm_message('APPROVE')

    def confirm_notify(self):
        self._confirm_message('NOTIFY')

    def confirm_alert(self):
        self._confirm_message('ALERT')

    def confirm_refuse(self):
        self._confirm_message('REFUSE')

    def receive_event(self, timeout=DEFAULT_MONITOR_TIMEOUT):
        event_pattern = ['APPROVE', 'NOTIFY', 'ALERT', 'REFUSE']
        try:
            event = self.read_until_last_line_matches(event_pattern, timeout)[1]
            if len(event.splitlines()) > 1:
                event = event.splitlines()[-1]
            getattr(self, 'confirm_' + event.strip().lower())()
        except client.ExpectTimeoutError as err:
            raise UnknownEventError(err.output.strip())
        return event.strip()
