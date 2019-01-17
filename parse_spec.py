#!/usr/bin/python
# This Python file uses the following encoding: utf-8
# Copyright 2015 Red Hat Inc.
# Author(s): Josh Boyer <jwboyer@fedoraproject.org>
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation; version 2 of the License.
# See http://www.gnu.org/copyleft/gpl.html for the full text of the license.

# Ideas taken from rpmdev-bumpspec script by Michael Schwendt, Ville Skyttä,
# Ralph Bean, et. al

import re
import sys
import os

spec_filename = "/home/jwboyer/kernel/kernel.spec"


def read_spec(filename):
    f = None
    lines = None

    try:
        f = open(filename, "r")
        lines = f.readlines()
    finally:
        f and f.close()

    return lines


def parse_spec(specf):

    spec = read_spec(specf)
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

    print specv['released_kernel']
    print specv['major_version']
    print specv['base_sublevel']
    print specv['rcrev']
    print specv['gitrev']
    print specv['stable_update']

    return specv

if __name__ == "__main__":
    parse_spec(spec_filename)
