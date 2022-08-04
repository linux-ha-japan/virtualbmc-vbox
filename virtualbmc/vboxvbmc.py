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

import platform
import re
import subprocess
import shlex
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

class VBoxError(Exception):
    pass

class VBoxVirtualBMC(bmc.Bmc):

    def __init__(self, username, password, port, address,
                 domain_name, libvirt_uri, libvirt_sasl_username=None,
                 libvirt_sasl_password=None, **kwargs):
        super(VBoxVirtualBMC, self).__init__({username: password},
                                         port=port, address=address)
        self.domain_name = domain_name

        self.vbox_user = None
        self.vboxmanage_path = 'VBoxManage' # Linux and Darwin should work with PATH
        system = platform.system()
        if system == 'Windows':
            self.vboxmanage_path = 'c:/Program Files/Oracle/VirtualBox/VBoxManage.exe'
        if 'microsoft-standard' in platform.uname().release: # is in WSL2?
            self.vboxmanage_path = '/mnt/c/Program Files/Oracle/VirtualBox/VBoxManage.exe'

        # configurable parameters
        from virtualbmc import config as vbmc_config
        try:
            self.vbox_user = vbmc_config.get_config()['vbox']['vbox_user']
        except KeyError:
            pass
        try:
            self.vboxmanage_path = vbmc_config.get_config()['vbox']['vboxmanage_path']
        except KeyError:
            pass

        self.vboxmanage_cmd = [self.vboxmanage_path]
        if self.vbox_user:
            if system == 'Linux': # assumes CentOS/RHEL
                self.vboxmanage_cmd = ['runuser', '-u', self.vbox_user, '--', self.vboxmanage_path]
            else:		  # assumes Darwin
                self.vboxmanage_cmd = ['su', self.vbox_user, self.vboxmanage_path]
        LOG.debug('vbox: vboxmanage_cmd = %s', self.vboxmanage_cmd)

    def run_vboxmanage(self, options):
        process = subprocess.Popen(self.vboxmanage_cmd + shlex.split(options),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   universal_newlines=True)
        status = process.wait()
        (out, err) = process.communicate()
        if status != 0:
            raise VBoxError('VBoxManage failed (%(status)d): %(error)s'
                            % {'status': status, 'error': err})
        return status, out, err

    def get_list_vms(self):
        result = {}
        regex = re.compile(r'^\"(.*)\" \{(.*)\}$')

        status, out, err = self.run_vboxmanage("list vms")
        for line in out.splitlines():
            dom = regex.search(line)
            if dom is not None:
                result[dom.group(1)] = POWEROFF

        status, out, err = self.run_vboxmanage("list runningvms")
        for line in out.splitlines():
            dom = regex.search(line)
            if dom is not None:
                result[dom.group(1)] = POWERON

        return result
    def get_vm_status(self):
        try:
            vms = self.get_list_vms()
            return vms[self.domain_name]
        except KeyError:
            raise VBoxError('domain %(domain)s not found' % {'domain': self.domain_name})

    def get_power_state(self):
        LOG.debug('Get power state called for domain %(domain)s',
                  {'domain': self.domain_name})
        try:
            return self.get_vm_status()
        except VBoxError as e:
            msg = ('Error getting the power state of domain %(domain)s. '
                   'Error: %(error)s' % {'domain': self.domain_name,
                                         'error': e})
            LOG.error(msg)
            raise exception.VirtualBMCError(message=msg)

    def power_off(self):
        LOG.debug('Power off called for domain %(domain)s',
                  {'domain': self.domain_name})
        try:
            if self.get_vm_status() == POWERON:
                status, out, err = self.run_vboxmanage("controlvm " + self.domain_name + " poweroff")
        except VBoxError as e:
            LOG.error('Error powering off the domain %(domain)s. '
                      'Error: %(error)s', {'domain': self.domain_name,
                                           'error': e})
            # Command failed, but let client to retry
            return IPMI_COMMAND_NODE_BUSY

    def power_on(self):
        LOG.debug('Power on called for domain %(domain)s',
                  {'domain': self.domain_name})
        try:
            if self.get_vm_status() == POWEROFF:
                status, out, err = self.run_vboxmanage("startvm " + self.domain_name + " --type headless")
        except VBoxError as e:
            LOG.error('Error powering on the domain %(domain)s. '
                      'Error: %(error)s', {'domain': self.domain_name,
                                           'error': e})
            # Command failed, but let client to retry
            return IPMI_COMMAND_NODE_BUSY

    def power_shutdown(self):
        LOG.debug('Soft power off called for domain %(domain)s',
                  {'domain': self.domain_name})
        try:
            if self.get_vm_status() == POWERON:
                status, out, err = self.run_vboxmanage("controlvm " + self.domain_name + " acpipowerbutton")
        except VBoxError as e:
            LOG.error('Error soft powering off the domain %(domain)s. '
                      'Error: %(error)s', {'domain': self.domain_name,
                                           'error': e})
            # Command failed, but let client to retry
            return IPMI_COMMAND_NODE_BUSY

    def power_reset(self):
        LOG.debug('Power reset called for domain %(domain)s',
                  {'domain': self.domain_name})
        try:
            if self.get_vm_status() == POWERON:
                status, out, err = self.run_vboxmanage("controlvm " + self.domain_name + " reset")
            else:
                # Command not supported in present state
                return 0xd5
        except VBoxError as e:
            LOG.error('Error reseting the domain %(domain)s. '
                      'Error: %(error)s', {'domain': self.domain_name,
                                           'error': e})
            # Command failed, but let client to retry
            return IPMI_COMMAND_NODE_BUSY

    def power_cycle(self):
        LOG.debug('Power cycle called for domain %(domain)s',
                  {'domain': self.domain_name})
        try:
            if self.get_vm_status() == POWERON:
                status, out, err = self.run_vboxmanage("controlvm " + self.domain_name + " poweroff")
            time.sleep(1)
            status, out, err = self.run_vboxmanage("startvm " + self.domain_name + " --type headless")
        except VBoxError as e:
            LOG.error('Error power cycle the domain %(domain)s. '
                      'Error: %(error)s' % {'domain': self.domain_name,
                                            'error': e})
            # Command failed, but let client to retry
            return IPMI_COMMAND_NODE_BUSY
