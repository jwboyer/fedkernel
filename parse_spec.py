#!/usr/bin/python

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
        if var == "released_kernel":
            specv['released_kernel'] = match.group('val')
            continue
        elif var == "base_sublevel":
            specv['base_sublevel'] = match.group('val')
            continue
        elif var == "rcrev":
            specv['rcrev'] = match.group('val')
            continue
        elif var == "gitrev":
            specv['gitrev'] = match.group('val')
            continue
        elif var == "stable_update":
            specv['stable_update'] = match.group('val')
            continue
        else:
            continue

    print specv['released_kernel']
    print specv['base_sublevel']
    print specv['rcrev']
    print specv['gitrev']
    print specv['stable_update']

    return specv

if __name__ == "__main__":
    parse_spec(spec_filename)
