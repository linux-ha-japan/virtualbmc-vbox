#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import subprocess
import time
import xml.etree.ElementTree as ET

import pyghmi.ipmi.bmc as bmc

from virtualbmc import exception
from virtualbmc import log
from virtualbmc import utils

LOG = log.get_logger()

# Power states
POWEROFF = 0
POWERON = 1

# From the IPMI - Intelligent Platform Management Interface Specification
# Second Generation v2.0 Document Revision 1.1 October 1, 2013
# https://www.intel.com/content/dam/www/public/us/en/documents/product-briefs/ipmi-second-gen-interface-spec-v2-rev1-1.pdf
#
# Command failed and can be retried
IPMI_COMMAND_NODE_BUSY = 0xC0
# Invalid data field in request
IPMI_INVALID_DATA = 0xcc

class HyperVVirtualBMC(bmc.Bmc):

    def __init__(self, username, password, port, address,
                 domain_name, libvirt_uri, libvirt_sasl_username=None,
                 libvirt_sasl_password=None, **kwargs):
        super(HyperVVirtualBMC, self).__init__({username: password},
                                         port=port, address=address)
        self.domain_name = domain_name

    def run_powershell(self, command):
        process = subprocess.Popen(
            ['/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe', command],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            encoding="CP932", universal_newlines=True)

        status = process.wait()
        (out, err) = process.communicate()
        return status, out, err

    def get_power_state(self):
        LOG.debug('Get power state called for domain %(domain)s',
                  {'domain': self.domain_name})
        status, out, err = self.run_powershell(f'(Get-VM -Name {self.domain_name}).State')
        out = out.strip()
        if (out == "Off"):
            return POWEROFF
        elif (out == "Running"):
            return POWERON

        msg = ('Error getting the power state of domain %(domain)s. '
               'Output: %(output)s, Error: %(error)s'
               % {'domain': self.domain_name, 'output': out, 'error': err})
        LOG.error(msg)
        raise exception.VirtualBMCError(message=msg)

    def power_off(self):
        LOG.debug('Power off called for domain %(domain)s',
                  {'domain': self.domain_name})
        try:
            if self.get_power_state() == POWERON:
                status, out, err = self.run_powershell(f'Stop-VM -Name {self.domain_name} -Force')
                if status != 0:
                    raise Exception(f'Output: {out}, Error: {err}')
        except Exception as e:
            LOG.error('Error powering off the domain %(domain)s. '
                      'Error: %(error)s', {'domain': self.domain_name,
                                           'error': e})
            # Command failed, but let client to retry
            return IPMI_COMMAND_NODE_BUSY

    def power_on(self):
        LOG.debug('Power on called for domain %(domain)s',
                  {'domain': self.domain_name})
        try:
            if self.get_power_state() == POWEROFF:
                status, out, err = self.run_powershell(f'Start-VM -Name {self.domain_name}')
                if status != 0:
                    raise Exception(f'Output: {out}, Error: {err}')
        except Exception as e:
            LOG.error('Error powering on the domain %(domain)s. '
                      'Error: %(error)s', {'domain': self.domain_name,
                                           'error': e})
            # Command failed, but let client to retry
            return IPMI_COMMAND_NODE_BUSY

    def power_shutdown(self):
        LOG.debug('Soft power off called for domain %(domain)s',
                  {'domain': self.domain_name})
        try:
            if self.get_power_state() == POWERON:
                status, out, err = self.run_powershell(f'Stop-VM -Name {self.domain_name}')
                if status != 0:
                    raise Exception(f'Output: {out}, Error: {err}')
        except Exception as e:
            LOG.error('Error soft powering off the domain %(domain)s. '
                      'Error: %(error)s', {'domain': self.domain_name,
                                           'error': e})
            # Command failed, but let client to retry
            return IPMI_COMMAND_NODE_BUSY

    def power_reset(self):
        LOG.debug('Power reset called for domain %(domain)s',
                  {'domain': self.domain_name})
        LOG.debug('NOTE: Power reset is not implemented yet. Executing Power cycle for instead.')
        self.power_cycle()

    def power_cycle(self):
        LOG.debug('Power cycle called for domain %(domain)s',
                  {'domain': self.domain_name})
        try:
            if self.get_power_state() == POWERON:
                status, out, err = self.run_powershell(f'Stop-VM -Name {self.domain_name}')
                time.sleep(1)
            status, out, err = self.run_powershell(f'Start-VM -Name {self.domain_name}')
            if status != 0:
                raise Exception(f'Output: {out}, Error: {err}')
        except Exception as e:
            LOG.error('Error power cycle the domain %(domain)s. '
                      'Error: %(error)s' % {'domain': self.domain_name,
                                            'error': e})
            # Command failed, but let client to retry
            return IPMI_COMMAND_NODE_BUSY
