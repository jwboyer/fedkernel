#!/usr/bin/env python3

# Copyright 2015 Red Hat Inc.
# Author(s): Josh Boyer <jwboyer@fedoraproject.org>
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation; version 2 of the License.
# See http://www.gnu.org/copyleft/gpl.html for the full text of the license.

from urllib.parse import urlparse
import argparse
import configparser
import logging
import os
import re
import shutil
import sys
import tempfile

from git import Repo
import fedpkg
import koji


_log = logging.getLogger("fedkernel")

pkg_git_dir = '/home/jwboyer/tmp/kernel'
linux_git_dir = '/home/jwboyer/tmp/linux'

KOJI_OPTIONS = {
    "krb_rdns": False,
    "max_retries": 10,
    "retry_internval": 10,
    "offline_retry": True,
    "offline_retry_interval": 10,
    "anon_retry": True,
}
KERBEROS_OPTIONS = {
    "ccache": None,
    "principal": None,
    "keytab": None,
}
HUB = "https://koji.fedoraproject.org/kojihub"

BRANCHES = {
    'f21': 'f21',
    'f22': 'f22',
    'f23': 'f23',
    'f24': 'f24',
    'f25': 'f25',
    'f26': 'f26',
    'f27': 'f27',
    'f28': 'f28',
    'f29': 'f29',
    'f30': 'f30',
    'f31': 'f31',
    'f32': 'f32',
    'f33': 'f33',
    'f34': 'master',
}


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
            tag = 'v{}.{}.{}'.format(
                specv['major_version'], specv['base_sublevel'], specv['stable_update'])
        else:
            tag = 'v%s.%s' % (specv['major_version'], specv['base_sublevel'])
    return tag


def get_base_commit(pkgdir, specv):

    commit = None

    if specv['gitrev'] == '0':
        commit = get_base_tag(specv)
    else:
        if specv['released_kernel'] != '0':
            sys.exit(1)

        # read the file that contains the gitrev commit sha
        with open(os.path.join(pkgdir, "gitrev"), "r") as fd:
            commit = fd.readline().strip()

    if commit is None:
        sys.exit(1)

    return commit


def get_work_dir(specv, tag):

    dist = re.split(r'(fc\d+)', tag)[1]
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
    print(sha)
    lingit.reset('--hard', sha)

    return lingit


def build_exp_tree(lingit, patch, tag, configdir, lindir):
    # Apply the patches
    lingit.am(patch.name)

    # Now add the Fedora config files
    shutil.copytree(configdir, lindir + '/fedora/configs')
    lingit.add('fedora/configs')
    log = ('%s configs' % tag)
    lingit.commit('-a', '-m', log)

    lingit.tag(tag)


def parse_spec(specf):

    with open(specf, "r") as fd:
        spec = fd.readlines()
    specv = {}

    if spec is None:
        sys.exit(0)

    for i in range(len(spec)):
        match = re.match(
            r"^%(global|define)\s+(?P<var>\w+)\s+(?P<val>\d+.*)", spec[i])
        if match is None:
            continue

        var = match.group('var')
        val = match.group('val')
        val = val.strip()
        if var == "released_kernel":
            specv['released_kernel'] = val
            continue
        elif var == "base_sublevel":
            specv['base_sublevel'] = val
            continue
        elif var == "rcrev":
            specv['rcrev'] = val
            continue
        elif var == "gitrev":
            specv['gitrev'] = val
            continue
        elif var == "stable_update":
            specv['stable_update'] = val
            continue
        elif var == "kversion":
            specv['kversion'] = val
            specv['major_version'] = val.split(".")[0]
            bar = val.split("-rc")
            if len(bar) > 1:
                specv['tar_suffix'] = "-rc%s" % specv['rcrev']
            else:
                specv['tar_suffix'] = None
            continue
        else:
            continue

    print(specv['released_kernel'])
    print(specv['major_version'])
    print(specv['base_sublevel'])
    print(specv['rcrev'])
    print(specv['gitrev'])
    print(specv['stable_update'])

    return specv


def get_build_info(build_id, nvr=False):
    """Get the dist-git commit and NVR when given a Koji build ID or NVR."""
    session = koji.ClientSession(HUB, KOJI_OPTIONS)
    if not session.krb_login(**KERBEROS_OPTIONS):
        raise Exception("Failed to log into Koji")


    if nvr is True:
        info = session.getBuild(build_id)
    else:
        info = session.getBuild(int(build_id))

    if info is None:
        raise ValueError("No such build: {}".format(build_id))

    task = None
    if info['task_id']:
        task = session.getTaskInfo(info['task_id'], request=True)

    nvrtag = info["nvr"]
    print(nvrtag)

    if task is None:
        return None

    tasklabel = koji.taskLabel(task)
    print(tasklabel)

    sha = urlparse(info["source"]).fragment
    print(sha)
    return (sha, nvrtag)


def create_tree(sha, tag):
    _log.info("Creating tree for pkg-git commit %s with tag %s", sha, tag)
    dist = re.split(r'.*fc(\d+)', tag)
    if len(dist) == 1:
        _log.info('Not a fedora build.  Skipping')
        return
    b = 'f' + re.split(r'.*fc(\d+)', tag)[1]

    try:
        branch = BRANCHES[b]
    except KeyError:
        _log.error('Could not create tree for branch %s', b)
        return
    if branch == 'f22':
        _log.warning('f22 build.  f22 is old and special.  Skipping.')
        return
    else:
        _log.info('sha %s tag %s branch %s', sha, tag, branch)

    # Get the package git repo and prep the tree from the commit that
    # corresponds to this build
    pkg = Repo(pkg_git_dir)
    pkg_git = pkg.git

    pkg_git.remote('update')
    pkg_git.checkout(branch)
    pkg_git.reset('--hard', '%s' % sha)

    fedcfg = configparser.ConfigParser()
    fedcfg.read('/etc/rpkg/fedpkg.conf')

    fedcli = fedpkg.cli.fedpkgClient(fedcfg, name='fedpkg')
    fedcli.do_imports(site='fedpkg')

    fedcli.args = fedcli.parser.parse_args(['prep'])
    fedcli.args.path = pkg_git_dir

    fedcli.args.arch = None
    fedcli.args.builddir = None

    fedcli.args.command()

    specv = parse_spec(os.path.join(pkg_git_dir, "kernel.spec"))

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

    if specv['stable_update'] != '0':
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

    _log.info(temp.name)
    temp.flush()

    lingit = prep_exp_tree(pkg_git_dir, linux_git_dir, branch, specv)

    build_exp_tree(lingit, temp, tag, wdir + 'configs', linux_git_dir)

    _log.info("Created exploded tree for %s", tag)


def callback(message):
    """
    The message callback for Koji builds.

    This can be run with::

        $ fedora-messaging consume --callback=fedkernel.kernel_git:callback

    The fedora-messaging configuration should set up a queue with bindings
    to the "org.fedoraproject.*.buildsys.build.state.change" topic.

    Message bodies are expected to look like:

      {
        "attribute": "state",
        "build_id": 1355787,
        "epoch": null,
        "instance": "primary",
        "name": "kernel",
        "new": 1,
        "old": 0,
        "owner": "labbott",
        "release": "0.rc4.git1.1.fc32",
        "request": [
          "git+https://src.fedoraproject.org/rpms/kernel.git#9a56544597fb8266578104c842002dec3a5fd483",
          "rawhide",
          {}
        ],
        "task_id": 37038078,
        "version": "5.3.0"
      }

    Args:
        message (fedora_messaging.api.Message): The AMQP message.
    """
    # This is completed undocumented in Koji and when it breaks it's not my
    # fault. There's a "new" field, and if it's 0 it apparently means the build
    # started, and if it's 1 that means the build completed. We're only
    # interested in completed kernel builds.
    if message.body.get("new", 0) != 1 or message.body.get("name") != "kernel":
        return

    try:
        request_url = message.body["request"][0]
    except KeyError:
        _log.error("Koji message format has changed (no 'request' key found); "
                   "dropping %r", message)
        return

    dist_git_sha = urlparse(request_url).fragment
    nvrtag = "{}-{}-{}".format(
        message.body["name"], message.body["version"], message.body["release"])
    create_tree(dist_git_sha, nvrtag)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Produce a Fedora source tree from builds in Koji')
    parser.add_argument(
        "buildid", help="The Koji build ID or NVR to produce a tree for.")
    args = parser.parse_args()

    sha, nvrtag = get_build_info(args.buildid, True)
    create_tree(sha, nvrtag)
