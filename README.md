# mpinstall
Macports installer that automaticaly determines the latest version and adjusts if port 873 is blocked.

## Overview
This tool installs the macports package management infrastructure in a
custom directory which allows you to create a USB or portable drive
with your favorite macports tools. It also makes removal easier because
no system directorie are affected.

## Features

1. It automatically selects the latest release.
2. It automatically handles the case where port 873 (rsync) is blocked by the firewall by changing the configuration to use port 80 (HTTP).

## Usage
Here is how you might use it.

```bash
$ # If this is not your first installation, grab the existing
$ # packages that you have installed.
$ port installed requested >/tmp/existing-pkgs.txt

$ # Download, install and capture the output to a log file (-t).
$ git clone https://github.com/jlinoff/mpinstall.git
$ cd mpinstall
$ sudo ./mpinstall.py -t -b /tmp/macports -r /opt/macports

$ # Update your ~/.bashrc file.
$ cat >>~/.bashrc <<EOF
export MP_PATH="/opt/macports"
export PATH="${MP_PATH}/bin:${PATH}"
export MANPATH="${MP_PATH}/share/man:${MANPATH}"
EOF
$ source ~/.bashrc

$ # Install some packages if this is a fresh installation.
$ sudo port install git
$ sudo port install git-extras
$ sudo port install htop
$ sudo port install meld
$ sudo port install tkdiff
$ sudo port install nodejs
$ sudo port install py27-crypto
$ sudo port install py27-pip
$ sudo port install py27-virtualenv
$ sudo port install py35-crypto
$ sudo port install py35-pip
$ sudo port install py35-virtualenv
$ sudo port install xorg-server
$ sudo port install nmap
$ sudo port install wireshark
$ sudo port install mongodb
$ sudo port install virtualbox

$ # If it is not a fresh installation, reinstall
$ # the previous packages.
$ grep '^ ' /tmp/existing-pkgs.txt | awk '{print $1;}' | xargs -L 1 sudo port install

$ # Clean up.
$ sudo rm -rf /tmp/macports
$ rm -f mpinstall*.log

$ # Update periodically.
$ sudo port sync
$ sudo port upgrade outdated
```

## Command Line Options
The table below briefly summarizes the command line options.
They are also available from the on-line help (-h or --help).

| Short  | Long         | Description |
| ------ | ------------ | ----------- |
| -b DIR | --blddir DIR | The build directory. Defaults to <pwd>/bld. |
| -h     | --help       | Help message. |
| -r DIR | --reldir DIR | The release directory. Defaults to <pwd>/rel. |
| -t     | --tee        | Tee the stdout and stderr to a log file. |
| -V     | --version    | Display the program version and exit.    |
| -u URL | --url URL    | Macports download URL: http://iweb.dl.sourceforge.net/project/macports/MacPorts/ |

## Finally
For more information about the macports project visit
https://macports.org.

Enjoy!
