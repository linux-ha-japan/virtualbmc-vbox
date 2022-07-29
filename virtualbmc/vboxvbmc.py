import os
import platform
import re
import subprocess
import shlex
import time
import xml.etree.ElementTree as ET

import pyghmi.ipmi.bmc as bmc

from virtualbmc import log
from virtualbmc import utils
from virtualbmc import exception


LOG = log.get_logger()

# Power states
POWEROFF = 0
POWERON = 1

class VBoxVirtualBMC(bmc.Bmc):

    def __init__(self, username, password, port, address,
                 domain_name, libvirt_uri, libvirt_sasl_username=None,
                 libvirt_sasl_password=None, **kwargs):
        # TODO: remove livbirt_* and generalize parameters list
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
                self.vboxmanage_cmd = ['runuser', '-u', self.vbox_user, self.vboxmanage_path]
            else:		  # assumes Darwin
                self.vboxmanage_cmd = ['su', self.vbox_user, self.vboxmanage_path]
        LOG.debug('vbox: vboxmanage_cmd = %s', self.vboxmanage_cmd)

    def run_vboxmanage(self, options):
        process = subprocess.Popen(self.vboxmanage_cmd + shlex.split(options),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   universal_newlines=True)
        status = process.wait()
        (out, err) = process.communicate()
        return status, out, err

    def get_list_vms(self):
        result = {}
        regex = re.compile(r'^\"(.*)\" \{(.*)\}$')

        #status, out, err = self.run_command(self.vbox_cmdline("list vms"))
        status, out, err = self.run_vboxmanage("list vms")
        for line in out.splitlines():
            dom = regex.search(line)
            if dom is not None:
                result[dom.group(1)] = POWEROFF

        #status, out, err = self.run_command(self.vbox_cmdline("list runningvms"))
        status, out, err = self.run_vboxmanage("list runningvms")
        for line in out.splitlines():
            dom = regex.search(line)
            if dom is not None:
                result[dom.group(1)] = POWERON

        return result

    def get_power_state(self):
        LOG.debug('Get power state called for domain %s', self.domain_name)
        try:
            vms = self.get_list_vms()
            return vms[self.domain_name]
        except Exception as e:
            import traceback
            LOG.error('Error getting the power state of domain %(domain)s. '
                      '%(type)s: %(error)s', {'domain': self.domain_name,
                                              'type': type(e).__name__,
                                              'error': e})
            # Command not supported in present state
            return 0xd5

    def power_off(self):
        LOG.debug('Power off called for domain %s', self.domain_name)
        try:
            status, out, err = self.run_vboxmanage("controlvm " + self.domain_name + " poweroff")
        except Exception as e:
            LOG.error('Error powering off the domain %(domain)s. '
                      'Error: %(error)s' % {'domain': self.domain_name,
                                            'error': e})
            # Command not supported in present state
            return 0xd5

    def power_on(self):
        LOG.debug('Power on called for domain %s', self.domain_name)
        try:
            status, out, err = self.run_vboxmanage("startvm " + self.domain_name + " --type headless")
        except Exception as e:
            LOG.error('Error powering off the domain %(domain)s. '
                      'Error: %(error)s' % {'domain': self.domain_name,
                                            'error': e})
            # Command not supported in present state
            return 0xd5

    def power_cycle(self):
        LOG.debug('Power cycle called for domain %s', self.domain_name)
        try:
            status, out, err = self.run_vboxmanage("controlvm " + self.domain_name + " poweroff")
            time.sleep(1)
            status, out, err = self.run_vboxmanage("startvm " + self.domain_name + " --type headless")
        except Exception as e:
            LOG.error('Error power cycle the domain %(domain)s. '
                      'Error: %(error)s' % {'domain': self.domain_name,
                                            'error': e})
            # Command not supported in present state
            return 0xd5

    def power_reset(self):
        LOG.debug('Power reset called for domain %s', self.domain_name)
        try:
            status, out, err = self.run_vboxmanage("controlvm " + self.domain_name + " reset")
        except Exception as e:
            LOG.error('Error power reset the domain %(domain)s. '
                      'Error: %(error)s' % {'domain': self.domain_name,
                                            'error': e})
            # Command not supported in present state
            return 0xd5

    def power_shutdown(self):
        LOG.debug('Soft power off called for domain %s', self.domain_name)
        try:
            status, out, err = self.run_vboxmanage("controlvm " + self.domain_name + " acpipowerbutton")
        except Exception as e:
            LOG.error('Error powering off the domain %(domain)s. '
                      'Error: %(error)s' % {'domain': self.domain_name,
                                            'error': e})
            # Command not supported in present state
            return 0xd5

#    def listen(cls, timeout=30):
#        import pyghmi.ipmi.private.session as ipmisession
#        while True:
#            r = ipmisession.Session.wait_for_rsp(timeout)
#            LOG.info('listen.wait_for_rsp() = %s' % (r))

def main():
    vbmc = VBoxVirtualBMC("pacemaker", "pacemakerpass", 623, "192.168.200.91", "node01")
    LOG.info('Virtual BMC for domain %s started', 'node01')
    vbmc.listen(timeout=300)


if __name__ == '__main__':
    main()
