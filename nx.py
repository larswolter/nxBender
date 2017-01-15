#!/usr/bin/env python2
import requests
import logging
import sslconn
import ppp

from requests.adapters import HTTPAdapter
from requests.packages.urllib3.poolmanager import PoolManager

class FingerprintAdapter(HTTPAdapter):
    """"Transport adapter" that allows us to pin a fingerprint for the `requests` library."""
    def __init__(self, fingerprint):
        self.fingerprint = fingerprint
        super(FingerprintAdapter, self).__init__()

    def init_poolmanager(self, connections, maxsize, block=False):
        self.poolmanager = PoolManager(
            num_pools=connections, maxsize=maxsize,
            block=block, assert_fingerprint=self.fingerprint)

class NXSession(object):
    def __init__(self, options):
        self.options = options

    def run(self):
        self.host = self.options.server
        self.session = requests.Session()

        if self.options.fingerprint:
            self.session.verify = False
            self.session.mount('https://', FingerprintAdapter(self.options.fingerprint))

        self.session.headers = {
                'User-Agent': 'Dell SonicWALL NetExtender for Linux 8.1.789',
        }

        self.login(
                self.options.username,
                self.options.password,
                self.options.domain
            )
        self.start_session()

        self.tunnel()

    def login(self, username, password, domain):
        resp = self.session.post('https://%s/cgi-bin/userLogin' % self.host,
                                 data={
                                     'username': username,
                                     'password': password,
                                     'domain': domain,
                                     'login': 'true',
                                 }
                                )

        error = resp.headers.get('X-NE-Message', None)
        if error:
            raise IOError('Server returned error: %s' % error)

    def start_session(self):
        """
        Start a VPN session with the server.

        Must be logged in.
        Stores srv_options and routes returned from the server.
        """

        resp = self.session.get('https://%s/cgi-bin/sslvpnclient' % self.host,
                                params={
                                    'launchplatform': 'mac',
                                    'neProto': 3,
                                    'supportipv6': 'no',
                                },
                               )

        srv_options = {}
        routes = []

        # Very dodgily avoid actually parsing the HTML
        for line in resp.iter_lines():
            line = line.strip()
            if line.startswith('<'):
                continue

            key, value = line.split(' = ', 1)

            if key == 'Route':
                routes.append(value)
            elif key not in srv_options:
                srv_options[key] = value
            else:
                logging.info('Duplicated srv_options value %s = %s' % (key, value))

        self.srv_options = srv_options
        self.routes = routes

    def tunnel(self):
        """
        Begin PPP tunneling.
        """

        tunsock = sslconn.SSLTunnel(self.srv_options['SessionId'], self.options, self.host, 443)
        pppd = ppp.PPPSession(self.options, tunsock)

        pppd.wait()
        tunsock.close()
