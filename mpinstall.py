#!/usr/bin/env python
'''
This tool installs the macports package management infrastructure in a
custom directory which allows you to create a USB or portable drive
with your favorite macports tools. It also makes removal easier because
no system directories are affected.

It has a couple of important features.

   1. It automatically selects the latest release.

   2. It automatically handles the case where port 873 (rsync) is
      blocked by the firewall by changing the configuration to use
      port 80 (HTTP).

Here is how you might use it:

   $ # If this is not your first installation, grab the existing
   $ # packages that you have installed.
   $ port installed requested >/tmp/existing-pkgs.txt

   $ # Install and capture the output to a log file (-t).
   $ sudo ./mpinstall.py -t -b /tmp/macports -r /opt/macports

   $ # Update your ~/.bashrc file.
   $ cat >>~/.bashrc <<EOF
   export MP_PATH="/opt/macports"
   export PATH="${MP_PATH}/bin:${PATH}"
   export MANPATH="${MP_PATH}/share/man:${MANPATH}"
   EOF
   $ source ~/.bashrc

   $ # Run it.
   $ port list
   $ sudo port install org-server

   $ # Clean up the build data.
   $ sudo rm -rf /tmp/macports

   $ # If this is not your first installation, reinstall
   $ # the packages.
   $ grep '^ ' /tmp/x | awk '{print $1;}' | xargs -L 1 sudo port install

   $ # If it is your first installation, install packages:
   $ sudo port install htop
   $ sudo port install nodejs
   $ sudo port install wireshark

If you do not specify -b (build directory) or -r (release directory),
macports will be built and installed in the current directory. The
build data will be in the "bld" subdirectory. The release data will be
in the "rel" (release to field) subdirectory.

For more information about the macports project, visit
https://macports.org.
'''
# MIT License
#
# Copyright (c) 2015 Joe Linoff
# 
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
# 
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
# 
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

from __future__ import print_function
import argparse
import datetime
import logging
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib2


VERSION = '1.0'


class Tee(object):
    '''
    Tee output to a log file.

    This allows stdout data to be tee'ed to stdout and to a file
    simultaneously.
    '''
    s_enable_file_writes = True
    
    def __init__(self, logfile):
        self.stdout = sys.stdout
        self.ofp = open(logfile, 'a')

    def write(self, msg):
        self.stdout.write(msg)
        if Tee.s_enable_file_writes is True:
            self.ofp.write(msg)
        self.flush()

    def flush(self):
        self.stdout.flush()
        self.ofp.flush()

    @classmethod
    def disable_file_writes(cls):
        cls.s_enable_file_writes = False

    @classmethod
    def enable_file_writes(cls):
        cls.s_enable_file_writes = True


def __runcmd(opts, logger, cmd, show_output=True, exit_on_error=True):
    '''
    Execute a shell command with no inputs.

    Capture output and exit status.

    For long running commands, this implementation displays output
    information as it is captured.

    For fast running commands it would be better to use
    subprocess.check_output.
    '''
    logger.info('Running command: {0}'.format(cmd))
    proc = subprocess.Popen(cmd,
                            shell=True,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)

    # Read the output 1 character at a time so that it can be
    # displayed in real time.
    out = ''
    while not proc.returncode:
        char = proc.stdout.read(1)
        if not char:
            # all done, wait for returncode to get populated
            break
        else:
            out += char
            if show_output:
                sys.stdout.write(char)
                sys.stdout.flush()

    proc.wait()
    sts = proc.returncode

    if sts != 0:
        logger.error('Command failed with exit status {0}.'.format(sts))
        if exit_on_error:
            if show_output is False:
                sys.stdout.write(out)
            sys.exit(1)
            
    return sts, out


def runcmd(opts, logger, cmd):
    '''
    Execute a shell command with no inputs.
    Exit on error.
    '''
    __runcmd(opts, logger, cmd, show_output=True, exit_on_error=True)


def init_logger(name):
    '''
    Initialize the logger.
    '''
    logger = logging.getLogger(name)
    lch = logging.StreamHandler(stream=sys.stdout)
    fmt = '%(asctime)s %(levelname)-7s %(filename)s %(lineno)5d %(message)s'
    formatter = logging.Formatter(fmt)
    lch.setFormatter(formatter)
    logger.addHandler(lch)
    logger.setLevel(logging.INFO)
    return logger

    
def xcode_check(opts, logger):
    '''
    Check to see if xcode is installed.
    If it isn't, try to install it.
    '''
    cmd = 'sudo xcode-select -p'
    _, out = __runcmd(opts, logger, cmd, show_output=True, exit_on_error=False)
    expected = '/Applications/Xcode.app/Contents/Developer'
    if out.find(expected) < 0:
        logger.info('Could not find expected output: "{0}".'.format(expected))
        logger.info('Installing xcode.')
        cmd = 'sudo xcode-select --install'
        runcmd(opts, logger, cmd)
    else:
        logger.info('Xcode installed.')

    # Make sure that the xcode license has been agreed to.
    cmd = 'sudo clang --version'
    runcmd(opts, logger, cmd)


def get_content_length(url):
    '''
    Get URL content length.
    '''
    response = urllib2.urlopen(url)
    for header in response.info().headers:
        match = re.search(r'content-length:\s+(\d+)', header, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return 0

    
def get_all_pkgs(opts, logger):
    '''
    Get the list of packages available from the
    official release area.
    '''
    logger.info('Get all releases from "{0}".'.format(opts.url))
    response = urllib2.urlopen(opts.url)
    html = response.read()
    vermap = {}
    releases = []
    for line in html.split('\n'):
        match = re.search(r'href="(\d+)\.(\d+)\.(\d+)/"', line)
        if match:
            ver = '{0}.{1}.{2}'.format(match.group(1), match.group(2), match.group(3))
            key = match.group(1).zfill(5) + '-' + match.group(2).zfill(5) + '-' + match.group(3).zfill(5)
            tarfile_name = 'MacPorts-{0}.tar.bz2'.format(ver)
            newurl = opts.url + ver + '/' + tarfile_name
            vermap[key] = {'tarfile': tarfile_name, 'url': newurl,}

    for key in sorted(vermap, key=str.lower):
        releases.append( (vermap[key]['tarfile'], vermap[key]['url']) )

    return releases  # last one is guaranteed to be the latest


def list_pkgs(opts, logger, pkgs):
    '''
    List the available releases.
    '''
    logger.info('List available releases from "{0}".'.format(opts.url))
    for pkg in pkgs:
        name = pkg[0]
        url = pkg[1]
        size = get_content_length(url)
        print('{0:<10}  {1:>10}  {2}'.format(name, size, url))
    print('{0} items'.format(len(pkgs)))


def download(opts, logger, tarfile_name, url):
    '''
    Download the tar file.
    '''
    if os.path.exists(tarfile_name) is False:
        # download the tar data and create the tar file
        clen = get_content_length(url)
        logger.info('Downloading "{0}".'.format(url))

        # Show progress as the data is downloaded.
        response = urllib2.urlopen(url)
        chunk_size = clen / 100  # read 1% at a time.
        tardata = ''
        read = 0
        Tee.disable_file_writes()
        while read < clen:
            cdata = response.read(chunk_size)
            tardata += cdata
            read += len(cdata)
            per = 100. * float(read) / float(clen)
            sys.stdout.write('\b'*(32 * len(url)))
            sys.stdout.write('{0:>10} of {1} {2:5.1f}% {3}'.format(read, clen, per, url))
            sys.stdout.flush()

        sys.stdout.write('\b'*(32 * len(url)))
        sys.stdout.write(' '*(32 * len(url)))
        sys.stdout.write('\b'*(32 * len(url)))
        Tee.enable_file_writes()
        logger.info('Read {0} bytes.'.format(len(tardata)))

        # Create the tar file.
        with open(tarfile_name, 'wb') as ofp:
            ofp.write(tardata)
    else:
        logger.info('Downloaded "{0}".'.format(tarfile_name))


def build(opts, logger, base, tarfile_name):
    '''
    Build the infrastructure.
    '''
    if os.path.exists(base) is False:
        # extract the tar contents
        logger.info('Extracting "{0}".'.format(tarfile_name))
        tar = tarfile.open(tarfile_name)
        tar.extractall()
        tar.close()

        # build mac ports
        os.chdir(base)  # change the working directory
        logger.info('Changed working directory to "{0}".'.format(os.getcwd()))

        logger.info('Building "{0}".'.format(base))
        cmds = ['sudo find /Library/ -type f -name \'*macports*\' -delete',
                './configure --help > configure.help',
                './configure --prefix="{0}" --with-applications-dir={0}/Applications'.format(opts.reldir),
                'make',
                'sudo make install',
        ]
        for cmd in cmds:
            runcmd(opts, logger, cmd)

        os.chdir('..')  # change the working directory
        logger.info('Changed working directory to "{0}".'.format(os.getcwd()))
    else:
        logger.info('Already built "{0}".'.format(base))

    
def update(opts, logger):
    '''
    Update the installations.
    '''
    logger.info('Updating mac ports.')
    
    # Setup the path so that commands like "port" work correctly.
    os.environ['PATH'] = os.path.join(opts.reldir, 'bin') + os.pathsep + os.environ['PATH']
    os.environ['MANPATH'] = os.path.join(opts.reldir, 'share', 'man') + os.pathsep + os.environ['PATH']
    runcmd(opts, logger, 'which port')  # verify PATH setup

    sync_cmd = 'sudo port -v selfupdate'
    sts, out = __runcmd(opts, logger, sync_cmd, show_output=True, exit_on_error=False)
    if sts != 0:
        # The update failed: sudo port -v selfupdate.
        # This may be because you cannot run rsync from behind your firewall.
        # Automatically configure to run behind your firewall by using http access.
        logger.info('Rsync update failed. Rsync operations may be blocked. Trying another option.')
        conf = os.path.join(opts.reldir, 'etc', 'macports', 'sources.conf')
        orig = conf + '.orig'
        if os.path.exists(orig) is False:
            runcmd(opts, logger, 'sudo cp -v {0} {1}'.format(conf, orig))
            runcmd(opts, logger, 'sudo chmod 0666 {0}'.format(conf))
    
            # Comment out the rsync: access line and insert the http access line.
            # The sed command is Mac OS X specific, it relies on the fact that
            # the older version of of the bash shell shipped by default
            # interprets $'\n' as a newline.
            with open(conf, 'r') as ifp:
                data = ifp.read()
                update = re.sub(r'^rsync:',
                                'http://distfiles.macports.org/ports.tar.gz [default]\n##rsync:',
                                data,
                                flags=re.MULTILINE)
                
            with open(conf, 'w') as ofp:
                ofp.write(update)
                
            runcmd(opts, logger, 'sudo chmod 0644 {0}'.format(conf))
            sync_cmd = 'sudo port -v sync'
            runcmd(opts, logger, sync_cmd)
            logger.info('Alternative approach worked! You must use "sync" to update instead of "selfupdate".')
            logger.info('To allow the use of "selfupdate", open up port 873 for rsync on your firewall.')
            
    logger.info('Macports has successfully been installed in "{0}".'.format(opts.reldir))
    return sync_cmd


def alldone(opts, logger, sync_cmd):
    '''
    Final installation message.
    '''
    sys.stdout.write('''
The macports installation has been successfully installed in
{1}.

To use it please update the PATH and MANPATH environment variables in
your ~/.bashrc file as follows:

   export MP_PATH="{1}"
   export PATH="${{MP_PATH}}/bin:${{PATH}}"
   export MANPATH="${{MP_PATH}}/share/man:${{MANPATH}}"

Once that is done and you have sourced ~/.bashrc, you will be able to
run the "port: command directly.

   $ source ~/.bashrc
   $ port list

If that works you can start installing packages like this:

   $ sudo port install org-server

You can update your installation like this:

   $ {0}

To clean up the build data now that it is no longer needed:

   $ sudo rm -rf {2}

To delete this installation simply remove the build, installation and
release areas as follows. Then remove the MP_PATH data from ~/.bashrc.

   $ sudo rm -rf {1} {2}

'''.format(sync_cmd, opts.reldir, opts.blddir))


def install(opts, logger, pkgs):
    '''
    Install macports.
    '''
    logger.info('Install macports.')
    xcode_check(opts, logger)

    # Get the configuration data.
    latest = pkgs[-1]  # could be selectable but is that needed?
    tarfile_name = latest[0]
    base = tarfile_name[:-len('.tar.bz2')]
    url = latest[1]

    logger.info('   Base    : "{0}".'.format(base))
    logger.info('   BldDir  : "{0}".'.format(opts.blddir))
    logger.info('   RelDir  : "{0}".'.format(opts.reldir))
    logger.info('   TarFile : "{0}".'.format(tarfile_name))
    logger.info('   URL     : "{0}".'.format(url))

    # create the installation (bld) area
    if os.path.exists(opts.blddir) is False:
        logger.info('Creating build directory tree: "{0}".'.format(opts.blddir))
        os.makedirs(opts.blddir)

    os.chdir(opts.blddir)  # change the working directory
    logger.info('Changed working directory to "{0}".'.format(os.getcwd()))
    
    download(opts, logger, tarfile_name, url)
    build(opts, logger, base, tarfile_name)
    sync_cmd = update(opts, logger)
    alldone(opts, logger, sync_cmd)
        
    
def getopts():
    '''
    Get the command line options.
    '''
    base = os.path.basename(sys.argv[0])
    def usage():
        'usage'
        usage = '{0} [OPTIONS]'.format(base)
        return usage
    def epilog():
        'epilogue'
        epilog = r'''
examples:
  $ # Example 1. Help
  $ {0} -h
  $ {0} --help

  $ # Example 2. Build and install in the current directory
  $ sudo {0}
  $ sudo {0} -b ./bld -r ./rel

  $ # Example 3. Build and install in a specific directory
  $ sudo {0} -b /tmp/macports -r /opt/macports
  $ sudo {0} --blddir /tmp/macports --reldir /opt/macports

  $ # Example 4. Build and install in a specific directory,
  $ #            and capture everything in a log file.
  $ sudo {0} -t -b /tmp/macports -r /opt/macports
  $ sudo {0} --tee --blddir /opt/macports --reldir /opt/macports
  $ ls -l {0}-*.log

'''.format(base)
        return epilog

    now = datetime.datetime.now()
    dts = now.strftime('%Y%m%d%H%M')
    log = '{0}-{1}.log'.format(base[:base.find('.')], dts)

    afc = argparse.RawDescriptionHelpFormatter
    desc = 'description:{0}'.format('\n'.join(__doc__.split('\n')))
    parser = argparse.ArgumentParser(formatter_class=afc,
                                     description=desc[:-2],
                                     usage=usage(),
                                     epilog=epilog())

    parser.add_argument('-b', '--blddir',
                        action='store',
                        type=str,
                        metavar=('DIR'),
                        default=os.path.join(os.path.abspath(os.getcwd()), 'bld'),
                        help='build directory (%(default)s)')
    
    parser.add_argument('-r', '--reldir',
                        action='store',
                        type=str,
                        metavar=('DIR'),
                        default=os.path.join(os.path.abspath(os.getcwd()), 'rel'),
                        help='release directory (%(default)s)')
    
    parser.add_argument('-t', '--tee',
                        action='store_true',
                        help='tee output to stdout and to a logfile named {0}'.format(log))

    parser.add_argument('-V', '--version',
                        action='version',
                        help='%(prog)s v{0}'.format(VERSION))

    parser.add_argument('-u', '--url',
                        action='store',
                        type=str,
                        default='http://iweb.dl.sourceforge.net/project/macports/MacPorts/',
                        help='macports download url (%(default)s)')

    opts = parser.parse_args()
    if opts.tee:
        sys.stdout = Tee(log)
    logger = init_logger(base)
    if opts.tee:
        logger.info('Logging to "{0}".'.format(log))

    if os.path.isabs(opts.reldir) is False:
        opts.reldir = os.path.abspath(opts.reldir)
    if os.path.isabs(opts.blddir) is False:
        opts.blddir = os.path.abspath(opts.blddir)
    
    return opts, logger
    

def main():
    '''
    main
    '''
    opts, logger = getopts()
    pkgs = get_all_pkgs(opts, logger)
    list_pkgs(opts, logger, pkgs)
    install(opts, logger, pkgs)
    logger.info('Done.')
    

if __name__ == '__main__':
    main()    
