#!/usr/bin/env python

import os
import string
import time
import thread
import sys

import ConfigParser
import koji

import fedmsg
import fedmsg.config
import fedmsg.meta

from git import Repo

from parse_spec import *

pkg_git_dir = '/home/jwboyer/tmp/kernel'
linux_git_dir = '/home/jwboyer/tmp/linux'

# This is pretty hacky.  It's only in place so I can use the koji session code
# drop-in.  Sigh.


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
    if not options.noauth and options.authtype != "noauth" and not session.logged_in:
        error(_("Unable to log in, no authentication methods available"))
    ensure_connection(session)
    if options.debug:
        print "successfully connected to hub"


def get_sha(tasklabel):

    sha = tasklabel.split(':')[1]
    sha = sha.strip(")")
    return sha


def get_build_info(build_id):

    global options
    options = Options()
    options = get_options()

    session = koji.ClientSession(options.server)
    activate_session(session)

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


def check_pkg(msg):
    buildinfo = None
    if msg['instance'] == "primary":
        if msg['new'] == 1:
            if msg['name'] == "kernel":
                print msg['name']
                print msg['build_id']
                buildinfo = get_build_info(msg['build_id'])

    return buildinfo


def create_tree(info):

    print "Creating tree for pkg-git commit %s with tag %s" % info
    sha = info[0]
    tag = info[1]
    branch = 'f' + re.split(r'.*fc(\d+)', tag)[1]

    if branch == 'f24':
        branch = 'rawhide'

    pkg = Repo(pkg_git_dir)
    pkg_git = pkg.git

    pkg_git.remote('update')
    pkg_git.checkout(branch)
    pkg_git.reset('--hard', '%s' % sha)

    parse_spec("%s/kernel.spec" % pkg_git_dir)

if __name__ == '__main__':

    config = fedmsg.config.load_config([], None)
    fedmsg.meta.make_processors(**config)

    for name, endpoint, topic, msg in fedmsg.tail_messages(**config):
        info = None
        if "buildsys.build.state.change" in topic:
            info = check_pkg(msg['msg'])

        if info is None:
            continue

        create_tree(info)
#			if "kernel" in msg['msg']['name']:
#			if msg['msg']['instance'] == "primary":
#				if msg['msg']['new'] == 1:
#					print msg['msg']['name']
#					print msg['msg']['build_id']
