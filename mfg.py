#!/usr/bin/env python
import sys
import socket
import time
import subprocess
import ConfigParser
import logging
from optparse import OptionParser

import yaml

from munin import MuninClient

DEFAULT_CONFIG = {
		'config_file': '/etc/mfg.ini',
		'log_file': '/var/log/mfg.log',
		'carbon_port': 2003,
		'metric_prefix': '{hostname}.',
		'interval': 60
		}
LOGGER = None

def facter():
    global LOGGER
    try:
        facter_output = subprocess.Popen(['facter','-py'], stdout=subprocess.PIPE, stderr=open("/dev/null", "w")).communicate()[0]
        y = yaml.load(facter_output)
        LOGGER.debug('Got facts: %s', y)
        return y
    except OSError, e:
        LOGGER.warning('Could not get facts: %s', e)
        return None

def compute_prefix(facts, prefix_pattern):
    """
    >>> prefix = 'servers.{datacenter}.{hostname}.'
    >>> facts = {'datacenter':'eu-west', 'hostname':'kellerautomat'}
    >>> compute_prefix(facts, prefix)
    'servers.eu-west.kellerautomat.'
    >>> prefix = '{hostname}.'
    >>> facts = None
    >>> compute_prefix(facts, prefix) == socket.gethostname() + '.'
    True
    """
    try:
        if facts:
            return prefix_pattern.format(**facts)
        else:
            return prefix_pattern.format(hostname=socket.gethostname())
    except KeyError, e:
        LOGGER.error('not all facts in "%s" could be resolved: %s', prefix_pattern, e)
        sys.exit(1)

class CarbonClient(object):

    def __init__(self, host, port):
        self.host = host
        self.port = int(port)
        self._init_socket()

    def _init_socket(self):
        try:
            self.sock = socket.socket()
            self.sock.settimeout(2)
            self.sock.connect((self.host, self.port))
        except IOError, e:
            raise e.__class__(e.errno, "%s:%s: %s" % (self.host, self.port, e.strerror))

    def send(self, message):
        self.sock.sendall(message)


def parse_config_file(config_file):
    config_file_structure = (
            ('carbon_port', 'carbon', 'port'),
            ('carbon_host', 'carbon', 'host'),
            ('metric_prefix', 'mfg', 'prefix'),
            ('interval', 'mfg', 'interval'),
            ('log_file', 'mfg', 'log_file'),
            )

    config = {}
    c = ConfigParser.ConfigParser()
    c.read(config_file)
    for config_key, section, key in config_file_structure:
        try:
            config[config_key] = c.get(section, key)
        except ConfigParser.Error:
            logging.debug('Could not get %s from config %s(section %s, key %s)',
                    config_key,
                    config_file,
                    section,
                    key)

    return config

def parse_command_line():
    # TODO
    parser = OptionParser()
    parser.add_option("-c", "--config", dest="config_file",
            help="use configuration in FILE, default: %s" % DEFAULT_CONFIG['config_file'], metavar="FILE")
    parser.add_option("-l", "--log", dest="log_file",
            help="use configuration in FILE, default: %s" % DEFAULT_CONFIG['log_file'], metavar="FILE",
            default=DEFAULT_CONFIG['log_file'])
    parser.add_option("-i", "--interval", dest="interval",
            help="send metrics every SECONDS, default: %s" % DEFAULT_CONFIG['interval'], metavar="SECONDS")
    parser.add_option("-H", "--carbon-host",
            help="send metrics to carbon host HOST", metavar="HOST")
    parser.add_option("-p", "--carbon-port",
            help="use carbon port PORT, default: %s" % DEFAULT_CONFIG['carbon_port'], metavar="PORT")
    parser.add_option("-m", "--metric-prefix",
            help="prefix every sent metric with PREFIX, default: %s" % DEFAULT_CONFIG['metric_prefix'], metavar="PREFIX")
    parser.add_option("-v", "--verbose", action="count", dest="verbose", help="be more verbose, may be used multiple times", default=0)

    (options, args) = parser.parse_args()
    return dict((k,v) for k,v in options.__dict__.items() if v)

def fetch_from_munin(munin_client):
    LOGGER.debug('going to ask munin for items')
    list_result = munin_client.list()
    LOGGER.debug('munin: list command returned %d results', len(list_result))
    messages = []
    for item in list_result:
        values = munin_client.fetch(item)
        try:
            for key in values:
                timestamp = int(time.time())
                if '.' in key: # It is from multigraph ?
                    graphite_path = key
                else:
                    graphite_path = "%s.%s" % (item, key)
                message = "%s %s %d\n" % (graphite_path, values[key], timestamp)
                LOGGER.debug('fetched from munin: %s', message)
                messages.append(message)
        except:
            LOGGER.warning('no data for: %s', values)
    return messages

def send_to_carbon(carbon_client, prefix, messages):
    prefixed_messages = [prefix + message for message in messages]
    carbon_client.send("".join(prefixed_messages))
    LOGGER.info('sent %d messages', len(prefixed_messages))

def main():
    global LOGGER
    config_file = DEFAULT_CONFIG['config_file']
    command_line_config = parse_command_line()


    if 'config_file' in command_line_config:
        config_file = command_line_config['config_file']

    config_from_file = parse_config_file(config_file)

    config = DEFAULT_CONFIG.copy()
    config.update(config_from_file)
    config.update(command_line_config)
 

    level = (logging.ERROR, logging.WARNING, logging.INFO, logging.DEBUG)[command_line_config.get('verbose', 0)]
    format = '%(asctime)s %(levelname)s %(name)s:%(lineno)d %(message)s'
    logger = logging.getLogger("mfg")
    logger.setLevel(level)
    fh = logging.FileHandler(config['log_file'])
    fh.setLevel(level)
    formatter = logging.Formatter(format)
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    LOGGER = logger

    LOGGER.debug('command line options: %s', command_line_config)

    LOGGER.debug('merged config: %s', config)
    if 'carbon_host' not in config:
        LOGGER.fatal('carbon_host not set, set in config file or use -H')
        raise RuntimeError()

    facts = facter()

    prefix = compute_prefix(facts, config['metric_prefix'])
    if not prefix.endswith('.'):
        prefix = prefix + '.'
    try:
        carbon_client = CarbonClient(config['carbon_host'], config['carbon_port'])
    except socket.error, e:
        print e
        sys.exit(1)

    munin_client = MuninClient('127.0.0.1')
    while True:
        try:
            munin_client = MuninClient('127.0.0.1')
            started = time.time()
            next_iteration = started + int(config['interval'])

            messages = fetch_from_munin(munin_client)
            send_to_carbon(carbon_client, prefix, messages)

            now = time.time()
            remaining_sleep = next_iteration - now
            if remaining_sleep > 0:
                LOGGER.debug('sleeping %d', remaining_sleep)
                time.sleep(remaining_sleep)
            else:
                LOGGER.warning('processing took %d seconds more than interval(%d), increase interval', -remaining_sleep, interval)

        except socket.error, e:
            print e
            sys.exit(1)

        except KeyboardInterrupt:
            munin_client.close()
            sys.exit(0)

if __name__ == '__main__':
    main()
