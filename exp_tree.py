#! /usr/bin/env/python

import os
import string
import sys

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
        base = '%s' % (int(specv['base_sublevel']) + 1)
        tag = 'v4.%s-rc%s' % (base, rc)
    else:
        if specv['stable_update'] != '0':
            tag = 'v4.%s.%s' % (specv['base_sublevel'], specv['stable_update'])
        else:
            tag = 'v4.%s' % specv['base_sublevel']
    return tag

def get_base_commit(pkgdir, specv):

    commit = None

    if specv['gitrev'] == '0':
        commit = get_base_tag(specv)
    else:
        if specv['released_kernel'] != '0':
            sys.exit(1)

        # read the file that contains the gitrev commit sha
        commit = read_gitrev(pkgdir)

    if commit is None:
        sys.exit(1)

    return commit

def get_work_dir(specv, tag):

    dist = re.split('(fc\d+)', tag)[1]
    maindir = "kernel-4.%s.%s" % (specv['base_sublevel'], dist)

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

def build_exp_tree(lingit, patch, tag):

    lingit.am(patch.name)
    lingit.tag(tag)
