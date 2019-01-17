#! /usr/bin/env/python

# Copyright 2015 Red Hat Inc.
# Author(s): Josh Boyer <jwboyer@fedoraproject.org>
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation; version 2 of the License.
# See http://www.gnu.org/copyleft/gpl.html for the full text of the license.

import os
import string
import sys
import shutil

from git import Repo

from parse_spec import *

def read_gitrev(dr):
    f = None
    sha = None

    try:
        f = open(dr + '/gitrev', "r")
        sha = f.readline()
        # Make sure to get rid of the newline.  Sigh, so tedious.
        sha = sha.strip()
    finally:
        f and f.close()

    return sha

def get_base_tag(specv):
    if specv['released_kernel'] == '0':
        if specv['rcrev'] == '0':
            # This should be a merge window kernel, which means gitrev
            # shouldn't be 0.  Since we only call this if gitrev is 0, we have
            # a problem
            sys.exit(1)
        rc = specv['rcrev']
        # Trivia time: If we're doing a major new release, we use RC
        # *tarballs*, not patches.  So here, we have an unreleased
        # kernel that has special rules.  We look to see if parse_spec
        # returned a tar_suffix value.  If it did, we don't do the
        # bump-by-one dance like we would if we're using a prior
        # release tarball and then applying an RC patch on top of it.
        #
        # This is all a house of cards.
        if specv['tar_suffix']:
            base = '%s' % specv['base_sublevel']
        else:
            base = '%s' % (int(specv['base_sublevel']) + 1)
        major = specv['major_version']
        tag = 'v%s.%s-rc%s' % (major, base, rc)
    else:
        if specv['stable_update'] != '0':
            tag = 'v%s.%s.%s' % (spevc['major_version'], specv['base_sublevel'], specv['stable_update'])
        else:
            tag = 'v%s.%s' % (specv['major_version'], specv['base_sublevel'])
    return tag

def get_base_commit(pkgdir, specv):

    commit = None

    if specv['gitrev'] == '0':
        commit = get_base_tag(specv)
    else:
        if specv['released_kernel'] != '0':
#            commit = get_base_tag(specv)
#            return commit
            sys.exit(1)

        # read the file that contains the gitrev commit sha
        commit = read_gitrev(pkgdir)

    if commit is None:
        sys.exit(1)

    return commit

def get_work_dir(specv, tag):

    dist = re.split('(fc\d+)', tag)[1]
    maindir = "kernel-%s.%s" % (specv['major_version'], specv['base_sublevel'])
    # If we have a tar_suffix (e.g. kernel-5.0-rc1) we need to use that for
    # the main working dir.  This is a result of using RC tarballs instead
    # of prior release tarballs+rc patches.
    if specv['tar_suffix']:
        maindir = maindir + specv['tar_suffix']
    maindir = maindir + ".%s" % dist

    # Using uname here is probably hacky, particularly since we tell fedpkg
    # that arch is noarch, but that isn't how the kernel works.  It always
    # preps for the local arch, so if this is ever different then something
    # weird happened.
    lindir = re.sub('kernel-', 'linux-', tag) + ".%s" % os.uname()[4]

    return maindir + "/" + lindir + "/"

def prep_exp_tree(pkgdir, lindr, branch, specv):

    lin = Repo(lindr)
    lingit = lin.git

    lingit.remote('update')

    if branch == "master":
        branch = "rawhide"

    lingit.checkout(branch)

    sha = get_base_commit(pkgdir, specv)
    print sha
    lingit.reset('--hard', sha)

    return lingit

def build_exp_tree(lingit, patch, tag, configdir, lindir):

    #Apply the patches
    lingit.am(patch.name)

    # Now add the Fedora config files
    shutil.copytree(configdir, lindir + '/fedora/configs')
    lingit.add('fedora/configs')
    log = ('%s configs' % tag)
    lingit.commit('-a', '-m', log)

    lingit.tag(tag)
