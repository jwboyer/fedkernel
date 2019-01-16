#! /usr/bin/env python

# Code taken and modified from koji

# Copyright (c) 2005-2014 Red Hat, Inc.
#
#    Koji is free software; you can redistribute it and/or
#    modify it under the terms of the GNU Lesser General Public
#    License as published by the Free Software Foundation;
#    version 2.1 of the License.
#
#    This software is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#    Lesser General Public License for more details.
#
#    You should have received a copy of the GNU Lesser General Public
#    License along with this software; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301 USA
#
# Authors:
#       Dennis Gregorovic <dgregor@redhat.com>
#       Mike McLean <mikem@redhat.com>
#       Mike Bonnet <mikeb@redhat.com>
#       Cristian Balint <cbalint@redhat.com>

import os
import sys
import socket
import ConfigParser
import krbV
import koji

class Options:
    debug = False
    server = None
    weburl = None
    pkgurl = None
    topdir = None
    cert = None
    ca = None
    serverca = None
    authtype = None
    noauth = None
    user = None
    runas = None


def get_options():
    global options
    # load local config
    defaults = {
        'server': 'http://localhost/kojihub',
        'weburl': 'http://localhost/koji',
        'pkgurl': 'http://localhost/packages',
        'topdir': '/mnt/koji',
        'max_retries': None,
        'retry_interval': None,
        'anon_retry': None,
        'offline_retry': None,
        'offline_retry_interval': None,
        'poll_interval': 5,
        'cert': '~/.koji/client.crt',
        'ca': '~/.koji/clientca.crt',
        'serverca': '~/.koji/serverca.crt',
        'keytab': None,
        'principal': None,
        'authtype': None
    }
    # grab settings from /etc/koji.conf first, and allow them to be
    # overridden by user config
    progname = 'koji'
    for configFile in ('/etc/koji.conf',):
        if os.access(configFile, os.F_OK):
            f = open(configFile)
            config = ConfigParser.ConfigParser()
            config.readfp(f)
            f.close()
            if config.has_section(progname):
                for name, value in config.items(progname):
                    # note the defaults dictionary also serves to indicate which
                    # options *can* be set via the config file. Such options should
                    # not have a default value set in the option parser.
                    if defaults.has_key(name):
                        if name in ('anon_retry', 'offline_retry'):
                            defaults[name] = config.getboolean(progname, name)
                        elif name in ('max_retries', 'retry_interval',
                                      'offline_retry_interval', 'poll_interval'):
                            try:
                                defaults[name] = int(value)
                            except ValueError:
                                parser.error(
                                    "value for %s config option must be a valid integer" % name)
                                assert False
                        else:
                            defaults[name] = value
    for name, value in defaults.iteritems():
        if getattr(options, name, None) is None:
            #        print '%s' % getattr(options, name, None)
            setattr(options, name, value)
    #        print '%s' % getattr(options, name, None)
    dir_opts = ('topdir', 'cert', 'ca', 'serverca')
    for name in dir_opts:
        # expand paths here, so we don't have to worry about it later
        value = os.path.expanduser(getattr(options, name))
        setattr(options, name, value)

    # honor topdir
    if options.topdir:
        koji.BASEDIR = options.topdir
        koji.pathinfo.topdir = options.topdir

    return options


def ensure_connection(session):
    try:
        ret = session.getAPIVersion()
    except xmlrpclib.ProtocolError:
        error(_("Error: Unable to connect to server"))
    if ret != koji.API_VERSION:
        warn(_("WARNING: The server is at API version %d and the client is at %d" % (
            ret, koji.API_VERSION)))

def has_krb_creds():
    if not sys.modules.has_key('krbV'):
        return False
    try:
        ctx = krbV.default_context()
        ccache = ctx.default_ccache()
        princ = ccache.principal()
        return True
    except krbV.Krb5Error:
        return False

def activate_session(session):
    """Test and login the session is applicable"""
    global options
    if options.authtype == "noauth" or options.noauth:
        # skip authentication
        pass
    elif options.authtype == "ssl" or os.path.isfile(options.cert) and options.authtype is None:
        # authenticate using SSL client cert
        session.ssl_login(
            options.cert, options.ca, options.serverca, proxyuser=options.runas)
    elif options.authtype == "password" or options.user and options.authtype is None:
        # authenticate using user/password
        session.login()
    elif options.authtype == "kerberos" or has_krb_creds() and options.authtype is None:
        try:
            if options.keytab and options.principal:
                session.krb_login(principal=options.principal, keytab=options.keytab, proxyuser=options.runas)
            else:
                session.krb_login(proxyuser=options.runas)
        except socket.error as e:
            warn(_("Could not connect to Kerberos authentication service: %s") % e.args[1])
        except Exception as e:
            if krbV is not None and isinstance(e, krbV.Krb5Error):
                print "Kerberos authentication failed: %s (%s)" % (e.args[1], e.args[0])
            else:
                raise

    if not options.noauth and options.authtype != "noauth" and not session.logged_in:
        error(_("Unable to log in, no authentication methods available"))
    ensure_connection(session)
    if options.debug:
        print "successfully connected to hub"

###
# Non-koji code below
###
def get_sha(tasklabel):

    sha = tasklabel.split(':')[1]
    sha = sha.strip(")")
    return sha


def get_build_info(build_id, nvr=False):

    global options
    options = Options()
    options = get_options()

    session = koji.ClientSession(options.server)
    activate_session(session)

    if nvr is True:
        info = session.getBuild(build_id)
    else:
        info = session.getBuild(int(build_id))

    if info is None:
        print "No such build: %s" % build
        return None

    task = None
    if info['task_id']:
        task = session.getTaskInfo(info['task_id'], request=True)

    nvrtag = "%(name)s-%(version)s-%(release)s" % info
    print nvrtag

    if task is None:
        return None

    tasklabel = koji.taskLabel(task)
    print tasklabel

    sha = get_sha(tasklabel)
    print sha
    return (sha, nvrtag)


