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
	released_kernel = None
	rcrev = None
	gitrev = None
	base_sublevel = None
	stable_update = None

	if spec is None:
		sys.exit(0)

	for i in range(len(spec)):
		match = re.match(r"^%(global|define)\s+(?P<var>\w+)\s+(?P<val>\d+.*)", spec[i])
		if match is None:
			continue

		var = match.group('var')
		if var == "released_kernel":
			released_kernel = match.group('val')
			continue
		elif var == "base_sublevel":
			base_sublevel = match.group('val')
			continue
		elif var == "rcrev":
			rcrev = match.group('val')
			continue
		elif var == "gitrev":
			gitrev = match.group('val')
			continue
		elif var == "stable_update":
			stable_update = match.group('val')
			continue
		else:
			continue
	
	print released_kernel
	print base_sublevel
	print rcrev
	print gitrev
	print stable_update


if __name__ == "__main__":
	parse_spec(spec_filename)
