#!/usr/bin/env python

# Copyright 2015 Red Hat Inc.
# Author(s): Josh Boyer <jwboyer@fedoraproject.org>
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation; version 2 of the License.
# See http://www.gnu.org/copyleft/gpl.html for the full text of the license.

import os
import string
import time
import thread
import sys
import tempfile

from koji_cli import *

import logging
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

    lingit = prep_exp_tree(pkg_git_dir, linux_git_dir, branch, specv)

    build_exp_tree(lingit, temp, tag)

if __name__ == '__main__':

    fedcfg = ConfigParser.SafeConfigParser()
    fedcfg.read('/etc/rpkg/fedpkg.conf')

    fedcli = fedpkg.cli.fedpkgClient(fedcfg, name='fedpkg')
    fedcli.do_imports(site='fedpkg')


    if len(sys.argv) != 1:
        info = get_build_info(sys.argv[1], True)
    else:
        logging.basicConfig()

        config = fedmsg.config.load_config([], None)
        fedmsg.meta.make_processors(**config)

        for name, endpoint, topic, msg in fedmsg.tail_messages(**config):
            info = None
            if "buildsys.build.state.change" in topic:
                info = check_pkg(msg['msg'])

            if info is None:
                continue
            else:
                create_tree(fedcli, info)


    create_tree(fedcli, info)
#			if "kernel" in msg['msg']['name']:
#			if msg['msg']['instance'] == "primary":
#				if msg['msg']['new'] == 1:
#					print msg['msg']['name']
#					print msg['msg']['build_id']
