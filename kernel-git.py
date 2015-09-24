#!/usr/bin/env python

import os
import string
import time
import thread
import sys
import tempfile

import ConfigParser
import koji

import fedmsg
import fedmsg.config
import fedmsg.meta

import pyrpkg
import fedpkg

from git import Repo

from parse_spec import *

from exp_tree import *

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


def check_pkg(msg):
    buildinfo = None
    if msg['instance'] == "primary":
        if msg['new'] == 1:
            if msg['name'] == "kernel":
                print msg['name']
                print msg['build_id']
                buildinfo = get_build_info(msg['build_id'])

    return buildinfo


def lookup_branch(branch):
    branches = {
            'f21': 'f21',
            'f22': 'f22',
            'f23': 'f23',
            'f24': 'master'
            }

    try:
        b = branches[branch]
    except:
        b = None

    return b

def prep_pkg_git(fedcli):

    fedcli.args = fedcli.parser.parse_args(['prep'])
    fedcli.args.path = pkg_git_dir

    fedcli.args.arch = None
    fedcli.args.builddir = None

    fedcli.args.command()

def create_tree(fedcli, info):

    print "Creating tree for pkg-git commit %s with tag %s" % info
    sha = info[0]
    tag = info[1]
    b = 'f' + re.split(r'.*fc(\d+)', tag)[1]

    branch = lookup_branch(b)
    if branch is None:
        print 'Could not create tree for branch %s' % b
        return

    # Get the package git repo and prep the tree from the commit that
    # corresponds to this build
    pkg = Repo(pkg_git_dir)
    pkg_git = pkg.git

    pkg_git.remote('update')
    pkg_git.checkout(branch)
    pkg_git.reset('--hard', '%s' % sha)

    prep_pkg_git(fedcli)

    specv = parse_spec("%s/kernel.spec" % pkg_git_dir)

    # Get the working directory for this pkg git tree and the git repo
    # that it contains
    wdir = get_work_dir(specv, tag)
    wdir = pkg_git_dir + '/' + wdir

    prepr = Repo(wdir)
    prepg = prepr.git

    # OK, the below probably needs some explanation.
    # We know that the pkg-git prep will create a git tree with the base
    # commit being one of two things; 1) a tree with all upstream content
    # contained within the root commit or 2) a root commit with the bulk of
    # the upstream content followed by a single commit for any stable patch
    #
    # So the code below gets the revision list for the git tree that is created
    # by 'fedpkg prep' and then uses either the first commit for the base
    # revision, or the second commit in the case of a stable kernel.
    #
    # Note: I have no idea how this will scale to a very large number of
    # commits (patches in the spec), but since it is just returning a list
    # of sha1sums and we tend to not carry more than a couple hundred patches
    # I suspect it will be ok.
    revlist = prepg.rev_list('--reverse', 'HEAD')
    rvlist = revlist.split('\n')

    if specv['stable_update'] == '1':
        baserev = rvlist[1]
    else:
        baserev = rvlist[0]

    # Now generate a patch that we are going to apply to the exploded tree
    # with git-am later
    #
    # Note: Another warning about scale here.  This is literally all of the
    # patches we have in the spec.  It might be large.  We'll see I guess.
    patch = prepg.format_patch('--stdout', '%s' % (baserev + '..'))
    temp = tempfile.NamedTemporaryFile(suffix=".patch", delete=False)

    for line in patch:
        temp.write(line.encode("utf-8"))

    print temp.name
    temp.flush()

    lingit = prep_exp_tree(linux_git_dir, branch, specv)

    build_exp_tree(lingit, temp)

if __name__ == '__main__':

    fedcfg = ConfigParser.SafeConfigParser()
    fedcfg.read('/etc/rpkg/fedpkg.conf')

    fedcli = fedpkg.cli.fedpkgClient(fedcfg, name='fedpkg')
    fedcli.do_imports(site='fedpkg')


    if sys.argv[1] != None:
        info = get_build_info(sys.argv[1], True)
    else:

        config = fedmsg.config.load_config([], None)
        fedmsg.meta.make_processors(**config)

        for name, endpoint, topic, msg in fedmsg.tail_messages(**config):
            info = None
            if "buildsys.build.state.change" in topic:
                info = check_pkg(msg['msg'])

            if info is None:
                continue

    create_tree(fedcli, info)
#			if "kernel" in msg['msg']['name']:
#			if msg['msg']['instance'] == "primary":
#				if msg['msg']['new'] == 1:
#					print msg['msg']['name']
#					print msg['msg']['build_id']
