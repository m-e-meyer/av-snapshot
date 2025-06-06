#!/usr/bin/python
# -*- coding: UTF-8 -*-
#

# Import these packages at a minimum
import os
import logging
import signal
import math
import traceback
from urllib.parse import urlparse, parse_qs, quote_plus
from html import escape
# End of mandatory packages
import base64
from datetime import datetime
import re


IMAGES = 'https://d2uyhvukfffg5a.cloudfront.net'

# Set this to the dev CGI location of all files this application will read
CGI_TASK_ROOT = "/home/markmeyer/kol/data"


class MyException(BaseException):
	"""TODO"""


# Accumulate HTML output
OUTPUT = []
def o(strng):
	"""TODO"""
	OUTPUT.append(strng)
def o_split(state):
	"""TODO"""
	state["o-pre-toc"] = OUTPUT[:]
	OUTPUT.clear()


class Section:
	"""Represents a section of the snapshot, with title, body, and subsections"""
	def __init__(self, level, title, anchor, textfn, subsections = []):
		self.level = level
		self.title = title
		self.anchor = anchor
		self.textfn = textfn
		self.subsections = subsections
		self.enabled = True
	def out(self, state):
		if self.level == 0 or self.enabled:
			if self.level > 0:
				o(f"<table class='nobord' cellspacing=0 cellpadding=0><tr><td class='noshrink'>"
					f"<h{self.level} id='{self.anchor}'>{self.title}</h{self.level}></td>"
					"<td>[<a href='#top' target='_self'>back to top</a>]</td></tr></table>")
			self.textfn(state)
			for ss in self.subsections:
				ss.out(state)
	def disable_all(self):
		self.enabled = False
		for ss in self.subsections:
			ss.disable_all()
	def enable_subsections(self):
		for ss in self.subsections:
			ss.enabled = True
			ss.enable_subsections()
	def enable_only(self, sections):
		"""Only mark requested sections (supplied as tuple of lowercase strs) as enabled"""
		if self.title.lower().startswith(sections):
			self.enabled = True
			self.enable_subsections()
			return True
		result = False
		for ss in self.subsections:
			result = ss.enable_only(sections) or result
		self.enabled = result
		return result
	def toc_entry(self):
		if self.level == 0 or not self.enabled:
			return ""
		prefix = "&nbsp;&bull;&nbsp;" * (self.level - 1)
		return f"{prefix}<a href='#{self.anchor}' target='_self'>{self.title}</a><br/>"
	def toc_entries(self):
		if not self.enabled:
			return []
		if self.level == 0:
			result = []
		else:
			result = [self.toc_entry()]
		for ss in self.subsections:
			result = result + ss.toc_entries()
		return result
	def out_toc(self):
		"""Output table of contents"""
		if self.level != 0:
			return
		o("<p></p><table class='nobord' cellspacing=0 cellpadding=0><tr><td class='nobord'>"
			"<button onclick='toggle_toc();' id='showhide'>Hide</b></td>"
			"<td class='nobord' style='font-size:1.5em;' valign='center'>"
			"<b>Table of Contents</b></td></tr></table>"
			"<div id='toc'>")
		entries = self.toc_entries()
		num_entries = len(entries)
		o(f"\n<!--DEBUG{num_entries}-->")
		if num_entries <= 28:
			num_columns = 1
		elif num_entries <= 56:
			num_columns = 2
		else:
			num_columns = 3
		num_rows = (num_entries // num_columns) + 1
		y = 0
		o("<table class='nobord toc' cellspacing=0 cellpadding=0><tr><td class='toc'>")
		for e in entries:
			o(e)
			y = y+1
			if y >= num_rows:
				o("</td><td class='toc'>")
				y = 0
		o("</td></tr>\n</table></div>\n")


def on_aws():
	"""Return whether running as AWS Lambda"""
	return "LAMBDA_TASK_ROOT" in os.environ

def arg_to_bytes(state, argv, key, eltsize):
	"""Convert coded argument string into bytes of data"""
	# How many bits data do we expect from the profile?
	size = len(state[key]) + 1	# if key not in state, that's an error
	bits = size * eltsize
	# How many base64 characters is that?
	chars = round(bits/24.0 + 0.49) * 4	 # 4 chars for 24 bits
	if key in argv:
		b64 = argv[key].replace('=','A')	# replace padding with 0
		if len(b64) < chars:				# add chars if not enough in profile
			b64 = b64 + ('A'*(chars - len(b64)))
		# decode the chars
		return base64.b64decode(b64, altchars='-_')
	# if key not in profile, generate empty bytes
	return base64.b64decode('A'*chars, altchars='-_')

def arg_to_counts(state, argv, key):
	"""
	Looks up the specified key in argv, and decodes the resulting base64 string into
	a series of bytes (pairs of nybbles), and in turn decodes those nybbles into a list
	of numbers: Each nybble is treated as a octal digit, with the high bit set if and
	only if that octal digit is the last digit of the encoded number.  For example,
	0010 0100 1011 will decode into 163 (2*64+4*8+3).
	"""
	if key in argv:
		size = len(state[key])
		b64 = argv[key].replace('=','A')
	else:
		size = 500	# way too big, but big enough
		b64 = "iIiI"*round((size/4)+1)
	byts = base64.b64decode(b64, altchars='-_')
	result = []
	val = 0
	for b in byts:
		nyb = b >> 4
		val = val*8 + (nyb & 7)
		if nyb >= 8:
			result.append(val)
			val = 0
		nyb = b & 15
		val = val*8 + (nyb & 7)
		if nyb >= 8:
			result.append(val)
			val = 0
	while len(result) < size:
		result.append(0)	# make sure list is as big as the datafiles expect
	return result


def open_file_for_reading(filename):
	"""Handle the opening of files in either CGI or AWS"""
	if on_aws():
		return open(os.environ["LAMBDA_TASK_ROOT"]+"/"+filename, "r", encoding="utf-8")
	return open(CGI_TASK_ROOT+"/"+filename, 'r', encoding="utf-8")


def split_param_string(pstring):
	"""TODO"""
	result = {}
	params = pstring.split('&')
	for pv in params:
		i = pv.find('=')
		result[pv[0:i]] = pv[i+1:]
	return result

def form_param_string(dic):
	"""TODO"""
	prefix = ''
	result = ''
	for p in dic:
		if p in ('name', 'update'):
			continue
		if p == 'demonnames':
			if not re.match("[a-zA-Z0-9 '_|-]+$", dic[p]):
				raise MyException(f'Invalid demon name(s) {escape(dic[p])}')
		result = result + prefix + p + '=' + dic[p]
		prefix = '&'
	return result


def tzname():
	"""TODO"""
	now = datetime.now()
	return now.astimezone().tzinfo.tzname(now)

def nowstring():
	"""TODO"""
	now = datetime.now()
	return now.strftime('%Y-%m-%d %H:%M:%S') + ' ' + tzname()

def normalize_datetime(dt):	 # pylint: disable=too-many-return-statements
	"""TODO"""
	nums = re.findall("[0-9]+", dt)
	if len(nums) == 0:
		return nowstring()
	ns = [int(n) for n in nums]
	if ns[0] < 100:
		ns[0] = ns[0] + 2000
	tz = tzname()
	if len(ns) == 1:
		return f"{ns[0]:04}-12-31 23:59:59 {tz}"
	if len(ns) == 2:
		return f"{ns[0]:04}-{ns[1]:02}-31 23:59:59 {tz}"
	if len(ns) == 3:
		return f"{ns[0]:04}-{ns[1]:02}-{ns[2]:02} 23:59:59 {tz}"
	if len(ns) == 4:
		return f"{ns[0]:04}-{ns[1]:02}-{ns[2]:02} {ns[3]:02}:59:59 {tz}"
	if len(ns) == 5:
		return f"{ns[0]:04}-{ns[1]:02}-{ns[2]:02} {ns[3]:02}:{ns[4]:02}:59 {tz}"
	return f"{ns[0]:04}-{ns[1]:02}-{ns[2]:02} {ns[3]:02}:{ns[4]:02}:{ns[5]:02} {tz}"

if on_aws():
	#### Code for Amazon Web Services
	import boto3	# pylint: disable=import-error
	import botocore # pylint: disable=import-error
	from boto3.dynamodb.conditions import Key   # pylint: disable=import-error
	def log_error(err, msg):
		"""TODO"""
		resp = err.response['Error']
		logger.error(msg + f": {resp['Code']}: {resp['Message']}")
	def lookup(name, on_or_before):
		"""TODO"""
		db = boto3.resource('dynamodb', region_name='us-east-2')
		table = db.Table('av_snapshot')
		name = name.lower()
		try:
			resp = table.query(
				KeyConditionExpression=Key('name').eq(name) & Key('tstamp').lte(on_or_before),
				ScanIndexForward = False,
				Limit = 1)
			if len(resp['Items']) < 1:
				return {}
			rec = resp['Items'][0]
			result = split_param_string(rec['state'])
			result['tstamp'] = rec['tstamp']
			return result
		except botocore.exceptions.ClientError as err:
			log_error("Fetch failed", err)
			raise
	def save(name, state):
		"""TODO"""
		db = boto3.resource('dynamodb', region_name='us-east-2')
		table = db.Table('av_snapshot')
		try:
			table.put_item(
				Item = {
					'name': name.lower(),
					'tstamp': nowstring(),
					'state': form_param_string(state)
				})
		except botocore.exceptions.ClientError as err:
			log_error("Fetch failed", err)
			raise
else:
	#### Code for my laptop running Fedora Linux
	import mysql.connector
	def lookup(name, on_or_before):
		"""TODO"""
		name = name.lower()
		last_time = '0000-00-00 00:00:00'
		cnx = mysql.connector.connect(user='mmeyer', password='', host='localhost', database='m')
		cursor = cnx.cursor()
		cursor.execute(f"SELECT * FROM av_snapshot WHERE name='{name}'")
		result = {}
		for (nm, tstamp, state) in cursor:  # pylint: disable=unused-variable
			if last_time < tstamp <= on_or_before:
				result = split_param_string(state)
				result["tstamp"] = tstamp
		cursor.close()
		cnx.close()
		return result
	def save(name, state):
		"""TODO"""
		cnx = mysql.connector.connect(user='mmeyer', password='', host='localhost', database='m')
		cursor = cnx.cursor()
		cursor.execute("INSERT INTO av_snapshot (name, tstamp, state) VALUES (%s, %s, %s)",
					   (name, nowstring(), form_param_string(state)))
		cnx.commit()
		cursor.close()
		cnx.close()


def wikilink(link, text):
	"""
	Return a hyperlink to output into the HTML stream.
	NOTE: link must not contain double-quotes, must use "&quot;" instead
	link can have square brackets, which will be removed
	"""
	# Remove square brackets
	link = link.replace('[', '').replace(']', '') if (link.find('[') >= 0) else link
	return f'<a href="http://kol.coldfront.net/thekolwiki/index.php/{link}" rel="noreferrer">{text}</a>'


def getbits(byts, index, eltsize):
	"""TODO"""
	loc = index * eltsize
	bytloc = loc >> 3
	bytoffs = loc % 8
	mask = (1 << eltsize) - 1
	if (bytoffs+eltsize) > 8:
		bb = byts[bytloc]*256+byts[bytloc+1]
		return (bb >> (16-bytoffs-eltsize)) & mask
	return (byts[bytloc] >> (8-bytoffs-eltsize)) & mask

def load_data_file(filename):
	"""TODO"""
	themap = {}
	with open_file_for_reading(filename+'.txt') as fil:
		maxx = 0
		while True:
			l = fil.readline().rstrip('\n')
			if not l:
				break
			l = l.split('\t')
			if l[0]=='':
				continue
			maxx = int(l[0])
			themap[maxx] = l
	return themap

def load_info_file(filename):
	themap = {}
	with open_file_for_reading(filename+'.txt') as fil:
		while True:
			l = fil.readline().rstrip('\n')
			if not l:
				break
			l = l.split('\t')
			themap[l[0]] = l[1]
	return themap

def load_data(state):
	"""TODO"""
	state['skills'] = load_data_file('av-snapshot-skills')
	state['trophies'] = load_data_file('av-snapshot-trophies')
	state['familiars'] = load_data_file('av-snapshot-familiars')
	state['tattoos'] = load_data_file("av-snapshot-tattoos")
	state['mritems'] = load_data_file("av-snapshot-mritems")
	state['coolitems'] = load_data_file("av-snapshot-coolitems")
	state['concocktail'] = load_data_file("av-snapshot-disc-cocktail")
	state['confood'] = load_data_file("av-snapshot-disc-food")
	state['conmeat'] = load_data_file("av-snapshot-disc-meat")
	state['conmisc'] = load_data_file("av-snapshot-disc-misc")
	state['consmith'] = load_data_file("av-snapshot-disc-smith")
	state['booze'] = load_data_file("av-snapshot-booze")
	state['food'] = load_data_file("av-snapshot-food")
	state['hobocodes'] = load_data_file("av-snapshot-hobocodes")
	state['info'] = load_info_file("av-snapshot-info")

def hx(tag, text, link):
	"""TODO"""
	o(f"<table class='nobord' cellspacing=0 cellpadding=0><tr><td class='noshrink'>"
	  f"<{tag} id='{link}'>{text}</{tag}></td>"
	  "<td>[<a href='#top' target='_self'>back to top</a>]</td></tr></table>")

def h1(state, text, link):
	"""TODO"""
	hx('h1', text, link)
	state['toc'].append([text, link, []])

def h2(state, text, link):
	"""TODO"""
	hx('h2', text, link)
	last = state['toc'][len(state['toc'])-1]
	last[2].append((text, link))


###########################################################################

def print_beginning(state, name, argv, fetched_argv, colorblind): # pylint: disable=unused-argument
	"""TODO"""
	tstamp = fetched_argv['tstamp']
	o("<!DOCTYPE html>\n")
	o("<html><head><base target='_blank'/><style>")
	with open_file_for_reading('av-snapshot-style.css') as fil:
		o(fil.read())
	bclas = ''
	if colorblind:
		bclas = "class='cb'"
	o(f"</style></head><body {bclas}>\n")
	o("""<script>
	function toggle_toc() {
		b = document.getElementById('showhide');
		toc = document.getElementById('toc');
		if (b.value == 'Show') {
			b.value = 'Hide';
			toc.style.display = 'block';
		} else {
			b.value = 'Show';
			toc.style.display = 'none';
		}
	}
	</script>""")
	if 'mafiarevision' in fetched_argv:
		mafia = fetched_argv['mafiarevision']
	else:
		mafia = "(unknown)"
	if 'snapshotversion' in fetched_argv:
		av_version = fetched_argv['snapshotversion']
	else:
		av_version = '(unknown)'
	o(f"<div class='header'><p>Snapshot for <b>{escape(name)}</b> taken {tstamp} using"
	  f" av-snapshot.ash v{av_version} run on KoLmafia revision r{mafia}, rendered by"
	  f" av-snapshot.py v{state['info']['VERSION']}.  If you'd like to use this yourself,"
	  f" check out the Kingdom of Loathing forum link"
	  f" <a href='http://forums.kingdomofloathing.com/vb/showthread.php?t=250707' rel='noreferrer'>here</a>.</p>")
	o("<p>av-snapshot is a fork of the cc_snapshot project by Cheesecookie,"
	  " whom I thank for his work."
	  f"  <a href='http://cheesellc.com/kol/profile.php?u={quote_plus(name)}' rel='noreferrer'>Here</a> is the"
	  " cc_snapshot equivalent of your query.</p>")
	query = f"?u={escape(name)}"
	if 'oob' in argv:
		query = query + '&oob=' + argv['oob']
	if colorblind:
		switch = 'off'
	else:
		switch = 'on'
		query = query + '&colorblind=1'
	suffix = '' if on_aws() else '.py'
	o(f"<p>Please click <a href='av-snapshot{suffix}{query}' target='_self'>here</a> to turn {switch}"
	  " colorblind mode.</p></div>\n")


###########################################################################

def class_for_perm(skill_bytes, skill_num):
	"""TODO"""
	lvl = getbits(skill_bytes, skill_num, 2)
	if lvl == 0:
		return ''
	if lvl == 1:
		return "class='perm'"
	return "class='hcperm'"

def print_skill_cell(skills, skill_bytes, skill_num, suffix=''):
	"""TODO"""
	# if skill_num is a tuple, find the one we have
	if isinstance(skill_num, tuple):
		for sn in skill_num:
			clas = class_for_perm(skill_bytes, sn)
			if clas != '':
				skill_num = sn
				break
	if isinstance(skill_num, tuple):
		# if we don't have a skill, show something
		if skill_num[0] == 406:
			o(f"<td>Drippy Eye{wikilink('Drippy Eye-Beetle','-Beetle')}, {wikilink('Drippy Eye-Sprout', '-Sprout')}, or {wikilink('Drippy Eye-Stone', '-Stone')}</td>")
			return
		else:
			skill_num = 0
	if skill_num == 0:
		o("<td></td>")
		return
	skil = skills[skill_num]
	clas = class_for_perm(skill_bytes, skill_num)
	desc = skil[2]
	desc = desc = "<br/>" + desc if desc not in ('', 'none', '-') else ""
	name = skil[1]
	flags = skil[4]
	if 'p' in flags:
		ibeg, iend, psv = "<i>", "</i>", "&#x2119;"
	else:
		ibeg, iend, psv = '', '', ''
	classist = '&copy;' if ('c' in flags) else ''
	usedbook = '&marker;' if ('b' in flags) else ''
	hcperm = '&#9405;' if ('h' in flags) else ''
	o(f"<td {clas}>{ibeg}{wikilink(name, name+suffix)} {psv}{classist}{usedbook}{hcperm}"
		f"<small>{desc}</small>{iend}</td>")

# Map av-snapshot skill numbers to positions in levels string
LEVELED_SKILLS = {315:3, 316:4, 322:5, 326:6, 329:7, 343:8, 355:32, 389:9, 402:10, 433:33}

def gen_suffix(skill, levels):
	"""TODO"""
	if skill in LEVELED_SKILLS:
		lv = levels[LEVELED_SKILLS[skill]:LEVELED_SKILLS[skill]+1]
		lv = str(int(lv, 36))
		if skill == 315:	# belch the rainbow
			return f' {lv}/11'
		return f': Level&nbsp;{lv}'
	return ''

def print_skill_row(state, header, skill_list, levels=''):
	"""TODO"""
	skills = state['skills']
	skill_bytes = state['skill-bytes']
	o(f"<tr><th>{header}</th>")
	for s in skill_list:
		print_skill_cell(skills, skill_bytes, s, gen_suffix(s, levels))
	o("</tr>\n")

def print_slime_row(state, levels):
	"""TODO"""
	skills = state['skills']
	skill_bytes = state['skill-bytes']
	o("<tr><th>The Slime Tube</th>")
	for i in range(0, 3):
		suffix = f" ({int(levels[i:i+1], 36)}/10)"
		print_skill_cell(skills, skill_bytes, 139+i, suffix)
	print_skill_cell(skills, skill_bytes, 0)
	print_skill_cell(skills, skill_bytes, 0)
	print_skill_cell(skills, skill_bytes, 0)
	o("</tr>\n")

def print_skill_multirow(state, header, skill_list_list, levels=''):
	"""TODO"""
	skills = state['skills']
	skill_bytes = state['skill-bytes']
	tr = ""
	o(f"<tr><th rowspan='{len(skill_list_list)}'>{header}</th>")
	for sl in skill_list_list:
		o(tr)
		tr = "<tr>"
		for s in sl:
			print_skill_cell(skills, skill_bytes, s, gen_suffix(s, levels))
		o('</tr>\n')

def o_class_row(col1):
	o(f"<tr><th>{col1}</th><th>Seal Clubber</th><th>Turtle Tamer</th><th>Pastamancer</th>"
		  '<th>Sauceror</th><th>Disco Bandit</th><th>Accordion Thief</th></tr>')
	
def o_guildskills(state):
	levels = state['levels']
	o("Skills innate to your class or buyable from your class's Guild.")
	o('<table cellspacing="0">')
	o_class_row('Level')
	o('<tr><th colspan="7" class="miniheader">Class (Original)</th></tr>')
	print_skill_row(state, '0 buff', (1, 2, 3, 4, 5, 6))
	print_skill_row(state, '0 combat', (7, 8, 9, 10, 11, 12))
	print_skill_row(state, '1', (217, 14, 15, 293, 17, 18))
	print_skill_row(state, '2', (19, 20, 21, 22, 23, 24))
	print_skill_row(state, '3', (25, 26, 27, 28, 29, 30))
	print_skill_row(state, '4', (31, 32, 33, 34, 35, 36))
	print_skill_row(state, '5', (37, 38, 39, 40, 41, 42))
	print_skill_row(state, '6', (227, 44, 45, 297, 47, 48))
	print_skill_row(state, '7', (49, 50, 51, 52, 53, 54))
	print_skill_row(state, '8', (55, 56, 57, 299, 59, 60))
	print_skill_row(state, '9', (61, 272, 63, 64, 65, 66))
	print_skill_row(state, '10', (67, 68, 69, 70, 71, 72))
	print_skill_row(state, '11', (73, 74, 75, 76, 77, 78))
	print_skill_row(state, '12', (79, 80, 81, 82, 83, 84))
	print_skill_row(state, '13', (85, 86, 87, 88, 89, 90))
	print_skill_row(state, '14', (91, 92, 93, 94, 95, 96))
	print_skill_row(state, '15', (97, 98, 99, 100, 101, 102))
	o('<tr><th colspan="7" class="miniheader">Class (Revamp 2013)</th><tr>')
	print_skill_row(state, '1', (13, 263, 278, 294, 231, 248))
	print_skill_row(state, '2', (218, 264, 279, 16, 247, 249))
	print_skill_row(state, '3', (219, 265, 280, 295, 233, 250))
	print_skill_row(state, '4', (220, 266, 281, 296, 234, 251))
	print_skill_row(state, '5', (221, 267, 282, 46, 235, 252))
	print_skill_row(state, '6', (222, 268, 283, 298, 246, 253))
	print_skill_row(state, '7', (223, 269, 284, 58, 236, 254))
	print_skill_row(state, '8', (224, 270, 285, 300, 237, 255))
	print_skill_row(state, '9', (225, 271, 286, 301, 238, 256))
	print_skill_row(state, '10', (226, 62, 287, 302, 239, 257))
	print_skill_row(state, '11', (43, 273, 288, 303, 240, 258))
	print_skill_row(state, '12', (228, 274, 289, 304, 241, 262))
	print_skill_row(state, '13', (229, 275, 290, 305, 242, 259))
	print_skill_row(state, '14', (230, 276, 291, 306, 243, 260))
	print_skill_row(state, '15', (163, 277, 292, 307, 244, 261))
	o('</table>\n')
	
def o_stdskills(state):
	levels = state['levels']
	o("Other skills that are permanently Standard.")
	o('<table cellspacing="0">')
	o_class_row('')
	print_skill_row(state, 'Spookyraven', (103, 104, 105, 106, 107, 108))
	print_skill_row(state, 'The Sea', (109, 110, 111, 112, 113, 114))
	o('<tr><th colspan="7" class="miniheader">Dreadsylvania</th><tr>')
	print_skill_row(state, 'Dread (SC)', (0, 202, 203, 204, 205, 206))
	print_skill_row(state, 'Dread (TT)', (0, 0, 207, 208, 209, 210))
	print_skill_row(state, 'Dread (PM)', (0, 0, 0, 211, 212, 213))
	print_skill_row(state, 'Dread (SA)', (0, 0, 0, 0, 214, 215))
	print_skill_row(state, 'Dread (DB)', (0, 0, 0, 0, 0, 216))
	o('<tr><th colspan="7" class="miniheader">Hobopolis</th><tr>')
	print_skill_row(state, 'Hodgman', (125, 126, 127, 128, 0, 0))
	print_skill_row(state, '30MP Elemental', (115, 116, 117, 118, 119, 177))
	print_skill_row(state, '120MP Elemental', (120, 121, 122, 123, 124, 178))
	print_skill_row(state, 'Accordion Thief', (129, 130, 131, 132, 133, 0))
	o('<tr><th colspan="7" class="miniheader">Other Standard Skills</th><tr>')
	print_skill_row(state, 'Gnomish', (134, 135, 136, 137, 138, 0))
	print_skill_row(state, 'Daily Dungeon', (197, 198, 199, 0, 0, 0))
	print_skill_multirow(state, 'PVP', ((190, 191, 322, 326, 328, 329),
										  (316, 232, 343, 355, 389, 449)), levels)
	print_slime_row(state, levels)
	print_skill_row(state, 'Waffle House', (356,357,0,0,0,0))
	print_skill_row(state, "Misc", (309, 142, 143, 200, 145, 146))
	o('</table>\n')
	
def o_nonstdskills(state):
	o("Skills that are no longer Standard or will someday leave Standard.")
	levels = state['levels']
	o('<table cellspacing="0">')
	o('<tr><th colspan="7" class="miniheader">Nonstandard Class Skills</th><tr>')
	o_class_row('')
	print_skill_row(state, 'Crimbo 2009', (148, 149, 150, 151, 152, 153))
	print_skill_row(state, 'Trader 2010', (169, 167, 168, 164, 179, 166))
	print_skill_row(state, 'Crimbo 2017<br/>Crimbotatoyotathon',
					(374, 375, 376, 377, 378, 379))
	print_skill_row(state, 'Madame Zatara', (380, 381, 382, 383, 384, 385))
	print_skill_row(state, 'Vampyre', (394, 395, 396, 397, 398, 399))
	o('<tr><th colspan="7" class="miniheader">Crimbo</th><tr>')
	print_skill_row(state, 'Crimbo 2010', (172, 173, 174, 175, 176, 0))
	print_skill_row(state, 'Crimbo 2013', (310, 311, 0, 0, 0, 0))
	print_skill_row(state, 'Crimbo 2014', (323, 324, 325, 0, 0, 0))
	print_skill_row(state, 'Crimbo 2015', (348,0,0,0,0,0))
	print_skill_row(state, 'Crimbo 2016', (360,361,0,0,0,0))
	print_skill_row(state, 'Crimbo 2018', (391,392,393,0,0,0))
	print_skill_row(state, 'Crimbo 2019', (403,0,0,0,0,0))
	print_skill_row(state, 'Crimbo 2020<br/>Crimbotatodonatothon',
					(411, 412, 413, 414, 415, 416))
	print_skill_row(state, 'Crimbo 2021<br/>Crimbotatogoogoneathon',
					(419,0,0,0,0,0))
	print_skill_multirow(state, 'Crimbo 2022<br/>Crimbotrainathon',
						 ((420, 421, 422, 423, 424, 425),
						  (426, 427, 428, 429, 430, 0)))
	print_skill_row(state, 'Crimbo 2023<br/>Crimbuccaneerathon',
					(435, 436, 437, 438, 439, 0))
	print_skill_row(state, 'Crimbo 2024<br/>Crrrrimbo', (441, 442, 443, 444, 445, 0))
	o('<tr><th colspan="7" class="miniheader">Other</th><tr>')
	print_skill_row(state, 'Trader 2008', (144,0,0,0,0,0))
	print_skill_row(state, 'The Suburbs of Dis', (187,188,189,0,0,0))
	print_skill_row(state, 'Silent Invasion', (194,195,196,0,0,0))
	print_skill_row(state, 'Ascension', (183,192,334,315,402,433), levels)
	print_skill_multirow(state, 'Elemental Planes',
						((312,313,317,320,321,330), (331,332,333,340,341,342),
						 (346,347,344,345,0,0)))
	print_skill_row(state, 'LT&T', (352,353,354,0,0,0))
	print_skill_row(state, 'Crash Site', (314,0,0,0,0,0))
	print_skill_row(state, 'Deck of Every Card', (335,336,337,338,339,0))
	print_skill_row(state, 'Snojo', (349,350,351,0,0,0))
	print_skill_row(state, 'Bookmobile', (359,371,418,432,440,0))
	print_skill_row(state, 'Gingerbread', (365,362,364,363,0,0))
	print_skill_row(state, 'Spacegate', (367,368,369,370,0,0))
	print_skill_row(state, 'PirateRealm', (400,401,0,0,0,0))
	print_skill_row(state, 'Drippy', ((406,407,408),0,0,0,0,0))
	print_skill_row(state, 'CyberRealm', (446, 447, 448, 0, 0, 0))
	print_skill_multirow(state, 'Misc',
						((147,185,162,170,171,181), (193,327,358,366,372,386),
						 (387,388,390,404,405,409), (410,417,431,434,0,0)), levels)
	o('<tr><th colspan="7" class="miniheader">Mystical Bookshelf</th><tr>')
	print_skill_row(state, 'Tomes', (154, 155, 156, 182, 308, 319))
	print_skill_multirow(state, 'Librams', ((157, 158, 159, 165, 184, 186),
												(201, 0, 0, 0, 0, 0)))
	print_skill_row(state, 'Grimoires', (160, 161, 180, 245, 318, 0))
	o('</table>\n')

def o_skills(state):
	"""TODO"""
	#h1(state, "Skills", "a_skills")
	levels = state['levels']
	tally = [0, 0, 0]
	autohc = 0
	skill_bytes = state['skill-bytes']
	for i in range(len(state['skills'])):
		x = getbits(skill_bytes, i+1, 2)
		tally[x] = tally[x] + 1
		if ((x == 2) and ('h' in state['skills'][i+1][4])):
			autohc = autohc + 1
	o(f"<p class='subheader'>You have <b>{tally[2]}</b> skills Hardcore permed"
      f" (<b>{autohc}</b> were automatic),"
	  f" <b>{tally[1]}</b> skills Softcore permed, and <b>{tally[0]-3}</b> missing.</p>\n"
	  f"You have <b>{int(levels[12:16], 36)}</b> unspent Karma.</p>"
	  "<p>Explanation of symbols: <br/>"
	  "<i>Italicized</i> skills marked with a <i>&#x2119</i> are Passive;<br/>"
	  "&copy; marks skills really useful only to their classes;<br/>"
	  "&marker; marks skills that can be relearned from a used skillbook or such;<br/>"
	  "&#9405; marks skills automatically marked Hardcore Permanent when acquired</p>")


###########################################################################

def print_tattoo_cell(tattoos, tattoo_bytes, tat, doimages, 
					  levels="", colspan=1, printlink=False):
	"""TODO"""
	# if multiple tats, pick the one we have, if any
	if isinstance(tat, tuple):
		for t in tat:
			x = getbits(tattoo_bytes, t, 2)
			if x > 0:
				tat = t
				break
	if isinstance(tat, tuple):
		tat = tat[0]	# or pick the lowest one that we don't have 
	# set colspan html
	if colspan != 1:
		colspanstr = f" colspan='{colspan}'"
	else:
		colspanstr = ''
	if tat == 0:
		o("<td></td>")
	elif tat == -1:		# Hobo tattoo
		lv = int(levels[11:12], 36)	# base-36 digit
		clas = ""
		if lv > 0:
			clas = "class='hcperm'" if (lv >= 19) else "class='perm'"
		img = ""
		if doimages and lv > 0:
			img = f"<img src='{IMAGES}/otherimages/sigils/hobotat{lv}.gif'><br/>"
		linktext = f"{img}Hobo Tattoo {lv}/19"
		o(f"<td {clas}>{wikilink('Hobo_Tattoo', linktext)}</td>")
	else:
		t = tattoos[tat]
		clas = ""
		x = getbits(tattoo_bytes, tat, 2)
		if x == 1:
			clas = "class='hcperm'"
		elif x == 2:
			clas = "class='perm'"
		img = f"<img src='{IMAGES}/otherimages/sigils/{t[2]}.gif'><br/>" if doimages else ''
		txt = wikilink(t[1], t[1]) if printlink else t[1]
		o(f"<td {clas}{colspanstr}>{img}{txt}</td>")

def print_tattoo_table(state, rows, levels=""):
	"""TODO"""
	tattoos = state['tattoos']
	tattoo_bytes = state['tattoo-bytes']
	o('<table cellspacing="0">')
	for row in rows:
		o("<tr>")
		for tat in row:
			# Legendary Regalia tats span 3 columns and link to wiki
			if tat in range(108,114):
				colspan = 3
				printlink = True
			else:
				colspan = 1
				printlink = False
			print_tattoo_cell(tattoos, tattoo_bytes, tat, state['doimages'], 
							  levels, colspan, printlink)
		o("</tr>")
	o("</table>")

def score_tattoos(state):
	tattoos = state['tattoos']
	levels = state['levels']
	tattoo_bytes = state['tattoo-bytes']
	tally = [0, 0, 0]
	for i in range(len(tattoos)):
		x = getbits(tattoo_bytes, i+1, 2)
		tally[x] = tally[x] + 1
	tally[0] = tally[0] - 8		# sneaky pete xxix and awol each have 4 redundant
	if levels[11:12] != '0':
		tally[0] = tally[0] - 1		# hobo tattoo of any level counts
		tally[1] = tally[1] + 1
	state["score_tats"] = tally[1]
	return tally

def o_tattoos(state):
	"""TODO"""
	tally = score_tattoos(state)
	o(f"<p class='subheader'>You have <b>{tally[1]}</b> tattoos and <b>{tally[2]}</b> outfits"
	  " for which you don't"
	  f" have the corresponding tattoo, and are missing <b>{tally[0]}</b> tattoos.</p>\n")

def o_class(state):
	print_tattoo_table(state,
		((1, 2, 3, 108),
		 (4, 5, 6, 109),
		 (7, 8, 9, 110),
		 (10, 11, 12, 111),
		 (13, 14, 15, 112),
		 (16, 17, 18, 113),
		 (144, 145, 149, 150, 155, 156),
		 (179, 180, 194, 195, 211, 212),
		 (213, 214, 215, 216, 228, 229),
		 (257, 258, 268, 269, 281, 304), 
		 (285, 286, 287, 288, 289, 290),
		 (301, 302, 311, 312, 0, 0)))

def o_ascension(state):
	print_tattoo_table(state,
		((19, 20, 21, 22, 23, 24),
		 (25, 26, 27, 28, 29, 30),
		 (31, 32, 33, 34, 35, 36),
		 (37, 38, 39, 40, 41, 42),
		 (43, 44, 45, 0, 0, 0)))

def o_outfits(state):
	"""do outfit table - we assume any tattoo with a component is an outfit"""
	tattoos = state['tattoos']
	tattoo_bytes = state['tattoo-bytes']
	o('<table cellspacing="0">')
	x = 0
	for t in range(len(tattoos)):
		tat = tattoos[t+1]
		if tat[3] == '-':
			continue
		if tat[1].find("Legendary Regalia") >= 0:
			continue	# we did the legendary regalia in the Class section
		if x == 0:
			o("<tr>")
		print_tattoo_cell(tattoos, tattoo_bytes, t+1, state['doimages'], printlink=True)
		x = x+1
		if x == 10:
			o("</tr>")
			x = 0
	if x > 0:
		while x < 10:
			o("<td></td>")
			x = x + 1
		o("</tr>")
	o("</table>")

def o_other(state):
	levels = state['levels']
	print_tattoo_table(state,
		(((126, 130, 131, 139, 142), 
		  (132, 133, 134, 135, 136), -1, 103, 104, 118), 
		 (106, 127, 128, 125, 140, 148), 
		 (172, 173, 174, 175, 176, 177), 
		 (178, 193, 192, 196, 203, 205),
		 (209, 208, 217, 218, 219, 220), 
		 (221, 227, 224, 231, 232, 233), 
		 (242, 246, 247, 248, 254, 260), 
		 (271, 273, 274, 275, 276, 292),
		 (294, 297, 298, 303, 306, 307),
		 (308, 313, 0, 0, 0, 0)), levels)


###########################################################################

def print_trophy_cell(clas, imgname, trophy, desc, doimages):
	"""TODO"""
	img = ''
	if doimages:
		imgname = imgname.replace('_thumb', '')
		imgname = ('itemimages/' if (imgname == 'nopic') else 'otherimages/trophy/') + imgname
		img = f"<img src='{IMAGES}/{imgname}.gif' style='width:50px; height:50px;'><br>"
	o(f"<td {clas}'>{img}{wikilink(trophy, desc)}</td>")

def score_trophies(state):
	tally = [0, 0]
	trophies = state['trophies']
	trophy_bytes = state['trophy-bytes']
	for i in range(len(trophies)):
		x = getbits(trophy_bytes, i+1, 1)
		tally[x] = tally[x] + 1
	state['score_trophs'] = tally[1]
	return tally

def o_trophies(state):
	"""TODO"""
	trophies = state['trophies']
	trophy_bytes = state['trophy-bytes']
	tally = score_trophies(state)
	o("<table cellspacing='0'><tr>")
	o(f"<p class='subheader'>You have <b>{tally[1]}</b> trophies"
	  f" and are missing <b>{tally[0]}</b> trophies.</p>\n")
	ct = 1
	doimages = state['doimages']
	for i in range(1, len(trophies)+1):
		t = trophies[i]
		clas = ""
		if i == 13:
			print_trophy_cell('', 'nopic', 'Noble Ascetic', 'Have Less Than 10,000 Meat', doimages)
			ct = ct + 1
		elif i == 144:
			o("<td></td>")
			ct = ct + 1
		if getbits(trophy_bytes, i, 1):
			clas = 'class="hcperm"'
		print_trophy_cell(clas, t[1], t[2], t[3], doimages)
		if ct % 10 == 0:
			o("</tr><tr>")
		ct = ct + 1
	while (ct % 10) != 1:
		o("<td></td>")
		ct = ct + 1
	o("</tr></table>\n")


###########################################################################

def print_familiar_cell(clas, imgname, name, doimages, april=False):
	"""TODO"""
	if clas != '':
		clas = "class='" + clas + "'"
	img = ''
	if doimages:
		if imgname.find('otherimages') < 0:
			imgname = 'itemimages/' + imgname + '.gif'
		elif imgname.find('camelfam') >= 0:
			# Melodramedary is a special case, need 2 images
			imgname = f"{imgname}'><img src='{IMAGES}/otherimages/camelfam_right.gif"
		img = f"<img src='{IMAGES}/{imgname}'><br/>"
	wikitext = f"{img}{name}"
	link = name if not april else f"April Fools' Familiars#{name.replace(' ','_')}"
	o(f"<td {clas}>{wikilink(link, wikitext)}</td>")

# Pre Quantum:
# 0: No familiar, in any capacity
# 1: Have familiar
# 2: Have hatchling, but not familiar
# 3: Have familiar, 100% run
# 4: Have familiar, 90% run
# ---- Post-Quantum
# 3: 100% run, have familiar
# 4: 90% run, have familiar
# 5: 100% run, no familiar
# 6: 100% run, hatching, no familiar.
# 7: 90% run, no familiar
# 8: 90% run, hatchling, no familiar.
# 5, 6, 7, and 8 should only be "possible" with April Foolmiliars... not sure if I
#   want to try to set up separate backgrounds for something that might not happen
FAM_STYLES = { 0:"", 1:"fam_have", 2:"fam_have_hatch", 
	3:"fam_run_100", 4:"fam_run_90",
	5:"fam_run_100_u", 6:"fam_run_100_h", 
	7:"fam_run_90_u", 8:"fam_run_90_h" 
}

def score_familiars(state):
	have, lack, tour, hundred = (0, 0, 0, 0)
	familiars = state['familiars']
	familiar_bytes = state['familiar-bytes']
	for i in range(len(familiars)):
		x = getbits(familiar_bytes, i+1, 4)
		if x in (1, 3, 4):
			have = have + 1
		else:
			lack = lack + 1
		if x >= 3:
			tour = tour + 1
			if x in (3, 5, 6):
				hundred = hundred + 1
	lack = lack - 9		# we won't count the April Foolmiliars
	state['score_fams'] = have
	return (have, lack, tour, hundred)

def o_familiar_table(state, famtype, msg):
	familiars = state['familiars']
	familiar_bytes = state['familiar-bytes']
	o(f"{msg}<br/>")
	o("<table cellspacing='0'><tr>")
	ct = 1
	doimages = state['doimages']
	for i in range(1, len(state['familiars'])+1):
		f = familiars[i]
		fnum = int(f[0])
		if (f[4] != famtype):
			# Skip if not the famtype we're looking for
			continue
		style = FAM_STYLES[getbits(familiar_bytes, i, 4)]
		print_familiar_cell(style, f[2], f[1], doimages, famtype=='a')
		if ct % 10 == 0:
			o("</tr><tr>")
		ct = ct + 1
	if (ct > 10):
		while (ct % 10) != 1:
			o("<td></td>")
			ct = ct + 1
	o("</tr></table>")
	
def o_familiars(state): # pylint: disable=too-many-branches
	"""TODO"""
	have, lack, tour, hundred = score_familiars(state)
	o(f"<p class='subheader'>You have <b>{have}</b> familiars (missing <b>{lack}</b>), "
	  f"have done <b>{tour}</b> tourguide runs and <b>{hundred}</b> 100% runs.</p>")
	# Next, legend
	o("<b>Legend</b><br/><table cellspacing='0'><tr>"
		+"<td class='fam_missing'>Don't have<br/>Familiar</td>"
		+'<td class="fam_have">Have Familiar</td>'
		+'<td class="fam_have_hatch">Have Familiar<br/>Hatchling</td>'
		+'<td class="fam_run_90">90% Run Done</td>'
		+'<td class="fam_run_100">100% Run Done</td>'
		+'<td class="fam_run_90_u">90% Run Done<br/>with unowned<br/>familiar</td>'
		+'<td class="fam_run_100_u">100% Run Done<br/>with unowned<br/>familiar</td>'
		+'<td class="fam_run_90_h">90% Run Done<br/>unowned fam,<br/>have hatchling</td>'
		+'<td class="fam_run_100_h">100% Run Done<br/>unowned fam,<br/>have hatchling</td>'
		)
	o("</tr></table>\n")

def o_purchasedfams(state):
	o_familiar_table(state, "p", "The hatchlings for these familiars were directly purchasable from Mr. Store.  The latest few may still be in Standard.")
	
def o_standardfams(state):
	o_familiar_table(state, "s", "These familiars are expected to be forever Standard.")

def o_derivedfams(state):
	o_familiar_table(state, "d", "The hatchlings for these familiars are assembled from parts, derived from an IotM, obtainable during a Crimbo or other special event, or acquired some other way.  The latest few may still be in Standard.")
	
def o_pocket(state):
	o_familiar_table(state, "k", "These familiars can be used only in the Pocket Familiars challenge path.") 

def o_april(state):
	o_familiar_table(state, "a", "These familiars only appear in the Quantum Terrarium challenge path or as foes in the Pocket Familiars path (before that, only on April Fool's Day, 2010), and can't be owned.  I think.")

###########################################################################

def print_item_link_cell(name, is_owned):
	"""TODO"""
	clas = ''
	if is_owned:
		clas = " class='hcperm'"
	o(f"<td style='margin: 5px' {clas}>{wikilink(name, name)}</td>")

def print_mritem_cell(state, it, subtable=False):
	"""TODO"""
	if it == 0:
		o("<td></td>")
	elif isinstance(it, tuple):
		o("<td style='margin:0;padding:0'><table height='100%' cellspacing='0'><tr>")
		print_mritem_cell(state, it[0], True)
		print_mritem_cell(state, it[1], True)
		o("</tr></table></td>")
	elif isinstance(it, str):
		o(f"<td>{it}</td>")
	else:
		mritems = state['mritems']
		counts = state['mritem-counts']
		name = mritems[it][2]
		clas = ''
		if counts[it-1] > 0:
			clas = " class='hcperm noshrink'" if subtable else " class='hcperm'"
		elif subtable:
			clas = " class='noshrink'"
		o(f"<td style='margin: 5px' {clas}>{wikilink(name, name)}</td>")

def print_coolitem_cell(state, it, print_image=True):
	"""TODO"""
	# if tuple of items, find the first one we have
	if isinstance(it, tuple):
		for i in it:
			n = state['coolitem-counts'][i-1]
			if n > 0:
				it = i
				break
	if isinstance(it, tuple):
		it = it[0]	# or the first one we don't have
		if it == 321:
			# Time bandit/lord badge is a special case
			tbbc = 'Time Bandit Badge of Courage'
			tlbh = 'Time Lord Badge of Honor'
			o(f"<td style='margin: 5px'>{wikilink(tbbc, tbbc)}<br/>or<br/>{wikilink(tlbh, tlbh)}</td>")
			return
	# silver wossname gets 7 columns
	if it == 554:
		colspan = " colspan=7"
	else:
		colspan = ''
	if it == 0:
		o(f"<td{colspan}></td>")
	else:
		coolitems = state['coolitems']
		count = state['coolitem-counts'][it-1]
		coolitem = coolitems[it]
		name = coolitem[1]
		clas = ''
		countstr = ''
		if count > 0:
			clas = " class='hcperm'"
			if count > 1:
				countstr = f' x{count}'
		if print_image:
			lbody = f"<img src='{IMAGES}/itemimages/{coolitem[2]}.gif'><br/>{name}{countstr}"
		else:
			lbody = f"{name}{countstr}"
		# item #214 is stuffed L, which needs two rows to display well
		rowspan = " rowspan='2'" if it == 214 else ""
		o(f"<td style='margin: 5px' {clas}{colspan}{rowspan}>{wikilink(name, lbody)}</td>")

def print_header_cell(header):
	"""TODO"""
	o(f"<th>{header}</th>")

def print_coolitem_row(state, its, print_image=True):
	"""TODO"""
	o("<tr>")
	for it in its:
		# strings are headers, numbers and tuples are cool items
		if not isinstance(it, str):
			print_coolitem_cell(state, it, print_image)
		else:
			print_header_cell(it)
	o("</tr>")

def print_coolitem_table(state, headers, rows):
	"""TODO"""
	o("<table cellspacing='0'>")
	if headers:
		o("<tr>")
		for h in headers:
			print_header_cell(h)
		o("</tr>")
	for r in rows:
		print_coolitem_row(state, r, state['doimages'])
	o("</table>\n")

def print_mritem_row(state, header, items):
	"""TODO"""
	o("<tr>")
	print_header_cell(header)
	for it in items:
		print_mritem_cell(state, it)
	o("</tr>")

def print_mritem_table(state, yr, headers, rows):
	"""TODO"""
	o("<table class='morepad' cellspacing='0'><tr>")
	for h in headers:
		print_header_cell(h)
	o("</tr>")
	for row in rows:
		print_mritem_row(state, yr, row)
		yr = yr + 1
	o("</table>")

def o_mritems(state):
	"""TODO"""
	print_mritem_table(state, 2004,
		('', 'January', 'February', 'March', 'April', 'May', 'June',
			'July', 'August', 'September', 'October', 'November', 'December'),
		((0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 2, 3),
		(4, 5, (6, 259), (7, 8), 9, 10, 11, 12, 13, 14, 15, 16),
		(17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28),
		(29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40),
		(41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52),
		(53, 54, 55, (66, 56), 57, 58, 59, 60, 61, 62, 63, 64),
		(65, 79, 57, 80, 81, 82, 83, 84, 85, 86, 89, 90),
		(91, 94, 95, 57, 96, 97, 98, 99, 100, 101, 102, 103),
		(104, 107, 108, 109, 57, 111, 112, 113, 114, 115, 116, 117),
		(118, 121, 122, 123, 124, 125, 57, 127, 128, 129, 130, 131),
		(132, 135, 136, 137, 138, 139, 57, 140, 141, 142, 143, 144),
		(145, 148, 149, 150, 151, (152, 153), 154, 155, 156, 157, 158, 159),
		(160, 162, 163, 57, 164, 165, 166, 167, 168, 172, 173, 174),
		(175, 177, 178, 179, 180, 181, 182, 183, 185, 186, 187, 188),
		(189, 57, 191, 192, 193, 194, 195, 196, 197, 198, 199, 200),
		(202, 203, 204, 205, 206, 207, 208, 209, 210, 211, 212, 213),
		(215, 216, 217, 218, 219, 220, 221, 222, 223, 224, 225, 226),
		(228, 229, 230, 231, 232, 233, 57, 234, 235, 236, 237, 238),
		(240, 241, 242, 243, 244, 245, 246, 247, 248, 249, 250, 252),
		(254, 255, 256, 257, 258, 260, 261, 262, 263, 264, 265, 266),
		(268, 270, 271, 272, 273, 274, 275, 276, 277, (278, 57), 279, 280),
		(281, 283, 284, 285, 286, 287, 0, 0, 0, 0, 0, 0) ))

def o_yearly(state):
	print_mritem_table(state, 2005,
		('', 'Volleychaun', 'Fairychaun'),
		((67, 68),
		(75, 76),
		(73, 74),
		(71, 72),
		(69, 70),
		(77, 78),
		(88, 87),
		(105, 106),
		(119, 120),
		(133, 134),
		(146, 147)))
	o('<p/>')
	print_mritem_table(state, 2016,
		('', 'Item', 'Type'),
		((161, 'Fairyball'),
		(176, 'Fairyball'),
		(190, 'Fairywhelp'),
		(201, 'Fairyball'),
		(214, 'Accessory'),
		(227, 'Shirt'),
		(239, 'Off-hand'),
		(253, 'Fairyball'),
		(269, 'Eudora'),
		(282, 'Content unlocker')))

def o_jicks_mom(state):
	"""This is a weird case, a mix of Mr. Items and Cool items"""
	o("<table class='morepad' cellspacing='0'>")
	for r in ((325, 326, 327, 328, 329, 330),
			(331, 332, 333, 334, 0, 0)):
		o("<tr>")
		for i in r:
			print_coolitem_cell(state, i, False)
		o("</tr>")
	o("<tr>")
	print_item_link_cell("Hippo tutu", (getbits(state['familiar-bytes'], 127, 4) > 0))
	print_item_link_cell("Gygaxian Libram", (getbits(state['skill-bytes'], 184, 2) > 0))
	print_item_link_cell("Tome of Rad Libs", (getbits(state['skill-bytes'], 308, 2) > 0))
	print_mritem_cell(state, 169)
	print_mritem_cell(state, 170)
	print_mritem_cell(state, 171)
	o("</tr><tr>")
	print_coolitem_cell(state, 324, False)
	print_mritem_cell(state, 267)
	o("<td></td><td></td><td></td><td></td></tr><tr>")
	print_mritem_cell(state, 184)
	print_mritem_cell(state, 251)
	o("<td></td><td></td><td></td><td></td></tr></table>")


###########################################################################

def print_loot_row(state, header, items, pad=0):
	"""TODO"""
	o("<tr>")
	if header != '':
		o(f"<th>{header}</th>")
	for it in items:
		print_coolitem_cell(state, it, state['doimages'])
	if pad > 0:
		o("<td></td>"*pad)
	o("</tr>")

def o_hobopolis(state):
	o("<table cellspacing='0'><tr><th>Boss</th><th colspan='3'>Outfit Pieces</th>"
	  "<th colspan='3'>Other Pieces</th></tr>")
	print_loot_row(state, "Frosty", range(467, 473))
	print_loot_row(state, "Zombo", range(473, 479))
	print_loot_row(state, "Chester", range(479, 485))
	print_loot_row(state, "Ol' Scratch", range(485, 491))
	print_loot_row(state, "Oscus", range(491, 497))
	print_loot_row(state, "Uncle Hobo", range(510, 516))
	print_loot_row(state, "Hodgman", range(497, 501), 2)
	print_loot_row(state, "Hodgman Offhands", range(501, 507))
	print_loot_row(state, "Hodgman Speed", range(507, 510), 3)
	o("</table>")

def o_code_binder(state):
	o("<table cellspacing=0>")
	hobocodes = state['hobocodes']
	col = 1
	mask = 1 << 19
	found = int(state['levels'][28:32], 36)
	for x in hobocodes:
		if col == 1:
			o("<tr>")
		clas = " class='hcperm'" if (found & mask != 0) else ''
		o(f"<td{clas}>{hobocodes[x][1]}</td>")
		col = col + 1
		mask = mask >> 1
		if col == 6:
			col = 1
			o("</tr>")
	o("</table>")

def o_equipment(state):
	print_coolitem_table(state, ('', 'Hat', 'Pants', 'Accessories'),
							(('150 Nickels', 27, 30, 34),
							 ('200 Nickels', 28, 29, 33),
							 ('250 Nickels', 26, 31, 32),
							 ('260 Nickels', 0, 0, 709)))

def o_instruments(state):
	print_coolitem_table(state, ('Seal Clubber', 'Turtle Tamer', 'Pastamancer',
								 'Sauceror', 'Disco Bandit', 'Accordion Thief'),
						(range(1, 7),))

def o_slime_tube(state):
	o("<table cellspacing='0'>")
	print_loot_row(state, "", range(516, 522))
	print_loot_row(state, "", range(522, 528))
	print_loot_row(state, "", range(528, 532), 2)
	print_loot_row(state, "", range(532, 537), 1)
	o("</table>")

def o_dreadsylvania(state):
	o("<table cellspacing='0'><tr><th>Boss</th><th colspan='3'>Outfit Pieces</th>"
	  "<th colspan='3'>Other Pieces</th></tr>")
	print_loot_row(state, "Great Wolf", range(84, 90))
	print_loot_row(state, "Falls-From-Sky", range(90, 96))
	print_loot_row(state, "Mayor Ghost", range(96, 102))
	print_loot_row(state, "Zombie", range(102, 108))
	print_loot_row(state, "Unkillable Skeleton", range(108, 114))
	print_loot_row(state, "Count Drunkula", range(114, 120))
	o("</table>")


###########################################################################

def o_cool_ultrarares(state):
	print_coolitem_table(state, None, ((38, 39, 40, 41, 42, 137, 43, 44),
									(45, 46, 47, 178, 48, 409, 0, 0)))

def o_cool_ascension(state):
	rewards = (range(555, 561),
		range(561, 567),
		range(567, 573),
		range(573, 579),
		range(579, 585),
		(585, 586, 588, 587, 589, 590),
		range(591, 597),
		range(597, 603),
		range(603, 609),
		range(609, 615),
		range(615, 621),
		range(621, 627),
		range(627, 633),
		range(633, 639),
		range(645, 651),
		range(639, 645),
		range(657, 663),
		range(651, 657),
		range(663, 669),
		range(669, 675),
		range(691, 697),
		range(685, 691),
		range(734, 740),
		range(740, 746),
		range(763, 769),
		range(769, 775))
	have = 0
	havent = 0
	counts = state['coolitem-counts']
	for row in rewards:
		for it in row:
			if counts[it-1] == 0:
				havent = havent + 1
			else:
				have = have + 1
	o(f"<p>You have <b>{have}</b> and are missing <b>{havent}</b>.</p>")
	print_coolitem_table(state, None, rewards)

def o_cool_swagger(state):
	print_coolitem_table(state, None, ((207, 208, 209, 210, 211, 212, 214),
									(213, 215, 335, 450, 705, 706)))

def o_cool_thwaitgold(state):
	print_coolitem_table(state, None, ((54, 55, 56, 57, 60, 61),
									(62, 82, 83, 135, 136, 173),
									(174, 175, 176, 177, 179, 252),
									(291, 297, 313, 353, 360, 362),
									(382, 390, 391, 415, 421, 425),
									(442, 446, 447, 452, 453, 454),
									(537, 538, 539, 704, 707, 708),
									(746, 747, 750, 775, 776, 0)))

def o_cool_medals(state):
	print_coolitem_table(state, ('Sidequests', '0', '1', '2', '3', '4', '5', '6'),
		(('Hippy', 540, 541, 542, 543, 544, 545, 546),
		('Frat', 547, 548, 549, 550, 551, 552, 553),
		('All', 554)))

def o_cool_sea(state):
	print_coolitem_table(state, None, (range(63, 69), range(69, 75), range(75, 82)))

def o_cool_chefstaves(state):
	print_coolitem_table(state, None, (range(13, 19),
									(19, 58, 20, 21, 22, 23),
									(24, 25, 53, 59, 172, 272),
									(386, 401, 441, 0, 0, 0)))
	#
def o_cool_marty(state):
	print_coolitem_table(state, None, (range(216, 220),))

def o_cool_secrets(state):
	print_coolitem_table(state, ('Seal Clubber', 'Turtle Tamer', 'Pastamancer',
								 'Sauceror', 'Disco Bandit', 'Accordion Thief'),
						(range(7, 13),))

def o_cool_underworld(state):
	print_coolitem_table(state, None, (range(35, 38),))

def o_cool_reflection(state):
	doimages = state['doimages']
	o("<table cellspacing='0'>")
	print_coolitem_row(state, range(180, 186), doimages)
	o("<tr>")
	print_coolitem_cell(state, 186, doimages)
	print_coolitem_cell(state, 187, doimages)
	levels = state['levels']
	chess = int(levels[26:28], 36)
	if chess == 0:
		clas = ''
	elif chess == 50:
		clas = " class='hcperm'"
	else:
		clas = " class='perm'"
	img = f"<img src='{IMAGES}/itemimages/chesscookie.gif'><br/>" if doimages else ''
	chesstext = f"{img}Chess Boards Completed {chess}/50"
	o(f"<td{clas}>{wikilink('The_Great_Big_Chessboard',chesstext)}</a></td>"
		"<td></td><td></td><td></td></tr></table>\n")

def o_cool_arcade(state):
	print_coolitem_table(state, None, (range(410, 415),))

def o_cool_necbromancer(state):
	print_coolitem_table(state, None, (range(50, 53),))

def o_cool_raiments(state):
	print_coolitem_table(state, None, (range(120, 128),))

def o_cool_psychoanalysis(state):
	print_coolitem_table(state, None, (range(128, 135),))

def o_cool_warbear(state):
	print_coolitem_table(state, None,
		(range(138, 147), range(147, 156), range(156, 165), (165, 166, 0, 0, 0, 0, 0, 0, 0)))

def o_cool_masks(state):
	print_coolitem_table(state, None, (range(167, 172),))

def o_cool_conspiracy(state):
	print_coolitem_table(state, None, (range(200, 207),))

def o_cool_dinseylandfill(state):
	print_coolitem_table(state, None, (range(188, 194), range(194, 200)))

def o_cool_volcano(state):
	print_coolitem_table(state, None,
		((248, 249, 250, 253, 254, 255),
		 range(257, 263),
		 (263, 264, 265, 0, 0, 0)))

def o_cool_glaciest(state):
	print_coolitem_table(state, None, (range(266, 272),))

def o_cool_gotpork(state):
	print_coolitem_table(state, None, (range(285, 289),))

def o_cool_telegraph(state):
	print_coolitem_table(state, None, (range(274, 280), (280, 281, 282, 283, 284, 289)))

def o_cool_fishin(state):
	print_coolitem_table(state, None, ((293, 294),))

def o_cool_precinct(state):
	print_coolitem_table(state, None, ((298, 299, 300),))

def o_cool_busting(state):
	print_coolitem_table(state, None, (range(301, 307), range(307, 313)))

def o_cool_gingerbread(state):
	print_coolitem_table(state, None,
		((347, 345, 348, 349, 350, 352),
		 (351, 346, 344, 0, 0, 0)))

def o_cool_chakra(state):
	print_coolitem_table(state, None, ((337, 338, 342, 339, 340, 341, 343),))

def o_cool_spacegate(state):
	print_coolitem_table(state, None, (range(376, 381),))

def o_cool_silent(state):
	print_coolitem_table(state, None, (range(365, 371), (371, 372, 373, 374, 375, 0)))

def o_cool_fantasyrealm(state):
	print_coolitem_table(state, None, (range(387, 390),))

def o_cool_party(state):
	print_coolitem_table(state, None, (range(393, 397), range(397, 401)))

def o_cool_piraterealm(state):
	print_coolitem_table(state, None, (range(416, 421),))

def o_cool_underwater(state):
	print_coolitem_table(state, None,
		((429, 430, (439, 440), 437, 427, 433, 434), 
		 (428, 436, 438, 431, 426, 432, 435)))

def o_cool_gooified(state):
	print_coolitem_table(state, None,
		((456, 457, 458, 460, 462, 463, 465, 466), ))

def o_cool_twitchery(state):
	print_coolitem_table(state, None,
		((225, 320, 322, 749, 317, 228),
		 (318, 230, 229, 748, 227, 315),
		 (316, 319, 220, (321, 323), 221, 222),
		 (224, 223, 226, 231, 232, 233),
		 (314, 0, 0, 0, 0, 0)))

def o_cool_hairclub(state):
	print_coolitem_table(state, None,
		((383, 384, 385, 256, 290, 273),
		 (292, 295, 296, 336, 354, (355, 356, 357, 358, 359)),
		 (361, 363, 364, 392, 422, 423), 
		 (424, (443, 444), 445, 451, 710, 0)))

def o_cool_oliver(state):
	print_coolitem_table(state, None, ((675, 676, 677, 678),))

def o_cool_train(state):
	print_coolitem_table(state, None, ((697, 701, 679, 680, 681, 703),
									   (682, 683, 698, 699, 700, 702)))

def o_cool_crimbuc(state):
	print_coolitem_table(state, None, ((711, 712, 713, 714, 715, 716),
									   (717, 718, 719, 720, 721, 722),
									   (723, 724, 725, 726, 727, 728),
									   (729, 730, 731, 732, 733, 0)))
	
def o_cool_crrrrimbo(state):
	print_coolitem_table(state, None, ((751, 762, 752, 753, 754, 755),
									   (756, 757, 758, 759, 760, 761)))


###########################################################################

def print_summary(data, bytess, recipes=True):
	"""TODO"""
	have = 0
	havent = 0
	for i in range(1, len(data)+1):
		name = data[i][1]
		if name in ("", "-"):	# some data entries are empty, don't know why
			continue
		if getbits(bytess, i, 1) > 0:
			have = have + 1
		else:
			havent = havent + 1
	if recipes:
		o(f"<p>You have found <b>{have}</b> of these discoveries"
		  f" and are missing <b>{havent}</b>.<br/>"
		  "Are some discoveries not showing up? Turn Inventory Images ON and one-click"
		  " crafting OFF and try again - it has a higher success rate.</p>")
	else:
		o(f"<p>You have consumed <b>{have}</b> of these items"
		  f" and have not yet tried <b>{havent}</b>.</p>")

def print_sorted_list(data, bytess, recipes=True):
	"""TODO"""
	print_summary(data, bytess, recipes)
	col = 1
	data = list(data.values())
	data = sorted(data, key=lambda d: d[1].upper())
	subtype_matcher = re.compile(r"(.*?) *[(]([^)]*)[)]$")
	o("<table cellspacing=0 cellpadding=0><tr>")
	for i, datum in enumerate(data):	# pylint: disable=unused-variable
		name = datum[1]
		if name in ("", "-"):	# some data entries are empty, don't know why
			continue
		# Remove square brackets
		link = name.replace('[', '').replace(']', '') if (name.find('[') >= 0) else name
		# HTML-encode percent signs
		link = link.replace('%', '%25') if link.find('%') >= 0 else link
		x = int(datum[0])
		clas = ' class="hcperm"' if (getbits(bytess, x, 1) > 0) else ''
		if name.find('(') < 0:
			o(f"<td{clas}>{wikilink(link, name)}</td>")
		else:
			m = subtype_matcher.match(name)
			subtype = m.group(2)
			if subtype in ("crumpled", "rusted", "shredded", "used"):
				o(f"<td{clas}>{wikilink(link, name)}</td>")
			else:
				name2 = m.group(1)
				link2 = name2.replace('[', '').replace(']', '') if (name2.find('[') >= 0) else name2
				o(f"<td{clas}>{wikilink(link2, name2)} ({m.group(2)})</td>")
		col = col+1
		if col > 6:
			o("</tr><tr>")
			col = 1
	if col > 1:
		while col <= 6:
			o("<td></td>")
			col = col + 1
	o("</tr></table>")

def o_disc_cocktailcrafting(state):
	print_sorted_list(state['concocktail'], state['concocktail-bytes'])

def o_disc_cooking(state):
	print_sorted_list(state['confood'], state['confood-bytes'])

def o_disc_meatpasting(state):
	print_sorted_list(state['conmeat'], state['conmeat-bytes'])

def o_disc_smithing(state):
	print_sorted_list(state['consmith'], state['consmith-bytes'])

def o_disc_misc(state):
	print_sorted_list(state['conmisc'], state['conmisc-bytes'])

def o_consumption_food(state):
	print_sorted_list(state['food'], state['food-bytes'], False)

def o_consumption_booze(state):
	print_sorted_list(state['booze'], state['booze-bytes'], False)

###########################################################################

def o_various(state):
	"""TODO"""
	demonnames = list(map(escape, state['demonnames']+[""]))  # old versions had fewer demon names
	levels = state['levels']
	o("<h3>Telescope</h3>")
	scope_lvl = levels[25:26]
	if scope_lvl == "0":
		o("<p>You don't have a Telescope in your Campground.</p>")
	else:
		o(f"<p>You have a Telescope in your Campground, and it's level <b>{levels[25:26]}</b>!</p>")
	o("<h3>Monster Manuel</h3>")
	if levels[16:25] == "000000000":
		o("<p>You probably don't have a Monster Manuel.</p>")
	else:
		o(f"<p>You have casually researched <b>{int(levels[16:19], 36)}</b> creatures.<br/>")
		o(f"You have thoroughly researched <b>{int(levels[19:22], 36)}</b> creatures.<br/>")
		o(f"You have exhaustively researched <b>{int(levels[22:25], 36)}</b> creatures.</p>")
	o("<h3>Demon Names</h3>")
	o("<table cellspacing=0>")
	o(f"<tr><td>1) Pies</td><td>{demonnames[0]}</td></tr>")
	o(f"<tr><td>2) Preternatural Greed<br/>Spooky Forest</td><td>{demonnames[1]}</td></tr>")
	o(f"<tr><td>3) Fit To Be Tide<br/>Sonofa Beach</td><td>{demonnames[2]}</td></tr>")
	o(f"<tr><td>4) Big Flaming Whip<br/>Friar's Gate</td><td>{demonnames[3]}</td></tr>")
	o(f"<tr><td>5) Demonic Taint<br/>Haunted Bathroom</td><td>{demonnames[4]}</td></tr>")
	o(f"<tr><td>6) Ragamuffin Imp</td><td>{demonnames[5]}</td></tr>")
	o(f"<tr><td>7) Drinks</td><td>{demonnames[6]}</td></tr>")
	o(f"<tr><td>8) Existential Torment<br/>Nemesis Lair</td><td>{demonnames[7]}</td></tr>")
	o(f"<tr><td>9) Burning, Man<br/>Sinister Ancient Tablet</td><td>{demonnames[8]}</td></tr>")
	o(f"<tr><td>10) The Pleasures of the Flesh<br/>Strange Cube</td><td>{demonnames[9]}</td></tr>")
	o("<tr><td>11) Friend of Gary</br>The Cola Wars Battlefield</td>"
	  f"<td>{demonnames[10]}</td></tr>")
	o(f"<tr><td>12) Neil the Sofa Sloth<br/>Intergnat</td><td>{demonnames[11]}</td></tr>")
	o(f"<tr><td>13) Herald of Yeg<br/>Cargo Cultist Shorts</td><td>{demonnames[12]}</td></tr>")
	o("</table>")
	tats, trophs, fams = state['score_tats'], state['score_trophs'], state['score_fams']
	o(f"<a name='collectorscore'><h3>Collector's Score: {tats+trophs+fams}"
	  f" (Tattoo: {tats}, Trophy: {trophs}, Familiar: {fams})</a></h3>")
	o("</body></html>\n")


###########################################################################

def o_pass(state): # pylint: disable=unused-argument
	pass

###########################################################################


def prepareResponse(argv, context):	 # pylint: disable=unused-argument
	'''
	prepareResponse returns the HTML string to send to the browser.
	Call your HTML-generating functions from here.
	'''
	state = {}	# used to capture state of user, instead of globals
	state['toc'] = []
	if argv is None or 'u' not in argv or argv['u'].strip() == '':
		if on_aws():
			return ('<html><head></head><body>Player name query parameter'
					' ("u=&lt;name&gt;") missing.</body></html>')
		name = 'test guy'
	else:
		name = argv['u'].lower()
	# Validate user name
	if (30 < len(name)) or (not re.match("[a-zA-Z0-9 _]+$", name)):
		return f'<html><head></head><body>Invalid user name {escape(name)}</body></html>'
	# If updating, just store the state and return
	if ("update" in argv) and (argv["update"] == 'j'):
		try:
			# Check human-readable parameters
			mafiarevision = argv['mafiarevision']
			if (6 < len(mafiarevision) or (not re.match("[0-9]*$", mafiarevision))):
				return f'<html><head></head><body>Invalid Mafia revision: {escape(mafiarevision)}</body></html>'
			snapshotversion = argv['snapshotversion']
			if (12 < len(snapshotversion) or (not re.match("[0-9a-zA-Z.]*$", snapshotversion))):
				return f'<html><head></head><body>Invalid snapshot version: {escape(snapshotversion)}</body></html>'
			demonnames = argv['demonnames']
			if (200 < len(demonnames) or (not re.match("[a-zA-Z0-9 '_|-]+$", demonnames))):
				return f'<html><head></head><body>Invalid demon name list: {escape(demonnames)}</body></html>'
			# Save if all is well
			save(name, argv)
		except MyException as e:
			return f'<html><head></head><body>{e.args[0]}</body></html>'
		return f'<html><head></head><body>Record added for {name}</body></html>'
	#
	colorblind = ('colorblind' in argv) and (int(argv['colorblind']) != 0)
	noimages = ('noimages' in argv) and (int(argv['noimages']) != 0)
	when = argv["oob"] if ("oob" in argv) else ''
	when = normalize_datetime(when)
	fetched_argv = lookup(name, when)
	# If lookup failed, report and return
	if len(fetched_argv) == 0:
		return (f"<html><head></head><body>Record for user {escape(name)} at time {when}"
				" not found</body></html>")
	#
	load_data(state)
	section_tree = Section(0, "", "", o_pass, [
		Section(1, "Skills", "a0", o_skills, [
			Section(2, "Guild Skills", "a0a", o_guildskills),
			Section(2, "Other Standard Skills", "a0b", o_stdskills),
			Section(2, "Nonstandard Skills", "a0c", o_nonstdskills)]),
		Section(1, "Tattoos", "a1", o_tattoos, [
			Section(2, "Class", "a1a", o_class),
			Section(2, "Ascension", "a1b", o_ascension),
			Section(2, "Outfits", "a1c", o_outfits),
			Section(2, "Other", "a1d", o_other)]),
		Section(1, "Trophies", "a2", o_trophies),
		Section(1, "Familiars", "a3", o_familiars, [
			Section(2, "Purchased Familiars", "a3d", o_purchasedfams),
			Section(2, "Standard Familiars", "a3c", o_standardfams),
			Section(2, "Derived Familiars", "a3e", o_derivedfams),
			Section(2, "Pocket Familiars", "a3a", o_pocket),
			Section(2, "April Foolmiliars", "a3b", o_april)]),
		Section(1, "Mr. Items", "a4", o_mritems, [
			Section(2, "Yearly Mr. Items", "a4a", o_yearly),
			Section(2, "Jick's Mom and Janet's Merchandise Table", "a4b", o_jicks_mom)]),
		Section(1, "Basement", "a5", o_pass, [
			Section(2, "Hobopolis", "a5a", o_hobopolis),
			Section(2, "Code Binder", "a5b", o_code_binder),
			Section(2, "Equipment", "a5c", o_equipment),
			Section(2, "Instruments", "a5d", o_instruments),
			Section(2, "Slime Tube", "a5e", o_slime_tube),
			Section(2, "Dreadsylvania", "a5f", o_dreadsylvania)]),
		Section(1, "Cool Items", "a6", o_pass, [
			Section(2, "Ultrarares", "a6a", o_cool_ultrarares),
			Section(2, "Ascension Rewards", "a6b", o_cool_ascension),
			Section(2, "Swagger Stuff", "a6c", o_cool_swagger),
			Section(2, "Thwaitgold", "a6d", o_cool_thwaitgold),
			Section(2, "War Medals", "a6e", o_cool_medals),
			Section(2, "Sea Stuff", "a6f", o_cool_sea),
			Section(2, "Chefstaves", "a6g", o_cool_chefstaves),
			Section(2, "Marty's Quest", "a6h", o_cool_marty),
			Section(2, "Secrets from the Future (2009)", "a6i", o_cool_secrets),
			Section(2, "Underworld (2009)", "a6j", o_cool_underworld),
			Section(2, "Moment of Reflection (2010)", "a6k", o_cool_reflection),
			Section(2, "Arcade Games (2010)", "a6l", o_cool_arcade),
			Section(2, "Necbromancer (2011)", "a6m", o_cool_necbromancer),
			Section(2, "Raiments of the Final Boss (2013)", "a6n", o_cool_raiments),
			Section(2, "Psychoanalysis (2013)", "a6o", o_cool_psychoanalysis),
			Section(2, "Warbear Crimbo (2013)", "a6p", o_cool_warbear),
			Section(2, "We All Wear Masks (2014)", "a6q", o_cool_masks),
			Section(2, "Conspiracy Island (2014)", "a6r", o_cool_conspiracy),
			Section(2, "Dinseylandfill (2015)", "a6s", o_cool_dinseylandfill),
			Section(2, "That 70s Volcano (2015)", "a6t", o_cool_volcano),
			Section(2, "Glaciest (2015)", "a6u", o_cool_glaciest),
			Section(2, "Gotpork (2016)", "a6v", o_cool_gotpork),
			Section(2, "LT&T Telegraph Office (2016)", "a6w", o_cool_telegraph),
			Section(2, "Fishin' Gear (2016)", "a6x", o_cool_fishin),
			Section(2, "Precinct (2016)", "a6y", o_cool_precinct),
			Section(2, "Busting Makes You Feel Good (2016)", "a6z", o_cool_busting),
			Section(2, "Gingerbread City (2016)", "a6za", o_cool_gingerbread),
			Section(2, "Chakra Crimbo (2016)", "a6zb", o_cool_chakra),
			Section(2, "Spacegate (2017)", "a6zc", o_cool_spacegate),
			Section(2, "Silent Crombotato (2017)", "a6zd", o_cool_silent),
			Section(2, "FantasyRealm (2018)", "a6ze", o_cool_fantasyrealm),
			Section(2, "Neverending Party (2018)", "a6zf", o_cool_party),
			Section(2, "PirateRealm (2019)", "a6zg", o_cool_piraterealm),
			Section(2, "Underwater Crimbo (2019)", "a6zh", o_cool_underwater),
			Section(2, "Gooified Crimbo (2021)", "a6zi", o_cool_gooified),
			Section(2, "Oliver's Place (2022)", "a6zk", o_cool_oliver),
			Section(2, "Train Crimbo (2022)", "a6zl", o_cool_train),
			Section(2, "Pirate Crimbo (2023)", "a6zm", o_cool_crimbuc),
			Section(2, "Twitchery (most recent 2024)", "a6zj", o_cool_twitchery),
			Section(2, "Pirate Crrrrimbo (2024)", "a6zn", o_cool_crrrrimbo),
			Section(2, "Hair Club for Loathers", "a6zz", o_cool_hairclub)]),
		Section(1, "Discoveries", "a7", o_pass, [
			Section(2, "Cocktailcrafting", "a7a", o_disc_cocktailcrafting),
			Section(2, "Cooking", "a7b", o_disc_cooking),
			Section(2, "Meatpasting", "a7c", o_disc_meatpasting),
			Section(2, "Smithing", "a7d", o_disc_smithing),
			Section(2, "Miscellaneous Discoveries", "a7e", o_disc_misc)]),
		Section(1, "Consumption", "a8", o_pass, [
			Section(2, "Food", "a8a", o_consumption_food),
			Section(2, "Booze", "a8b", o_consumption_booze)]),
		Section(1, "Various Accomplishments", "a9", o_various)
	])
	sections = argv["sections"] if ("sections" in argv) else ""
	sections = sections.lower().split(",")
	if len(sections) > 0:
		section_tree.disable_all()
		sections = tuple(map(lambda x: x.strip(), sections))
		section_tree.enable_only(sections)
	#
	print_beginning(state, name, argv, fetched_argv, colorblind)
	section_tree.out_toc()
	#
	state['skill-bytes'] = arg_to_bytes(state, fetched_argv, "skills", 2)
	state['tattoo-bytes'] = arg_to_bytes(state, fetched_argv, "tattoos", 2)
	state['trophy-bytes'] = arg_to_bytes(state, fetched_argv, "trophies", 1)
	state['familiar-bytes'] = arg_to_bytes(state, fetched_argv, "familiars", 4)
	state['mritem-counts'] = arg_to_counts(state, fetched_argv, "mritems")
	state['coolitem-counts'] = arg_to_counts(state, fetched_argv, "coolitems")
	state['concocktail-bytes'] = arg_to_bytes(state, fetched_argv, "concocktail", 1)
	state['confood-bytes'] = arg_to_bytes(state, fetched_argv, "confood", 1)
	state['conmeat-bytes'] = arg_to_bytes(state, fetched_argv, "conmeat", 1)
	state['conmisc-bytes'] = arg_to_bytes(state, fetched_argv, "conmisc", 1)
	state['consmith-bytes'] = arg_to_bytes(state, fetched_argv, "consmith", 1)
	state['booze-bytes'] = arg_to_bytes(state, fetched_argv, "booze", 1)
	state['food-bytes'] = arg_to_bytes(state, fetched_argv, "food", 1)
	num_levels = int(state['info']['LEVELS'])
	if "levels" in fetched_argv:
		levels = fetched_argv["levels"]
		if len(levels) < num_levels:
			levels = levels + ("0"*(num_levels-len(levels)))
	else:
		levels = "0"*num_levels
	state['levels'] = levels
	demonnames = fetched_argv['demonnames'].split('|') if (
		"demonnames" in fetched_argv) else ['']*12
	state['demonnames'] = demonnames
	state['doimages'] = not noimages
	# Need to tally the Collector's Score now in case we don't display their sections
	score_tattoos(state)
	score_trophies(state)
	score_familiars(state)
	#
	section_tree.out(state)
	#
	return ''.join(OUTPUT)


###########################################################################
######################## BEGIN AWS/CGI BOILERPLATE ########################
###########################################################################

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def respond(err, on_edge, resp=None):
	"""TODO"""
	if on_edge:
		headers = {	'content-type': [{ 'key': 'Content-Type',
								'value': 'text/html; charset=UTF-8' }]}
		statcode = 'status'
	else:
		headers = { 'Content-Type': 'text/html; charset=UTF-8' }
		statcode = 'statusCode'
	return {
		statcode: '400' if err else '200',
		'body': err.message if err else resp,
		'headers': headers
	}

def exceptionInfo(trace, evt):
	"""TODO"""
	result = trace.replace("\n", "<br/>")
	params = evt['queryStringParameters']
	if params is None:
		result = result + "== No parameters ==<br/>"
	else:
		result = result + "== Parameters ==<br/>"
		for p in params:
			v = params[p]
			result = result + f"{p}: {v}</br>"
	return result

timeoutResponse = '''
<html><head></head>
<body><h1>Sorry</h1>
<p>The page timed out while processing.  Please try reloading the page.
<p>- Aventuristo
</body></html>
'''

class MyTimeout(BaseException):
	"""TODO"""

def timeout_handler(_signal, _frame):
	"""TODO"""
	raise MyTimeout("Time exceeded")

def lambda_handler(event, context):
	'''Demonstrates a simple HTTP endpoint using API Gateway. You have full
	access to the request and response payload, including headers and
	status code.
	'''
	logger.info("## HANDLE LAMBDA")
	on_edge = ('httpMethod' not in event)
	OUTPUT.clear()	# clear that global!
	if 'source' in event and event['source'] == 'aws.events':
		return respond(None, on_edge, 'Ping acknowledged')

	if on_edge:
		request = event['Records'][0]['cf']['request']
		argv = urlparse('?'+request['querystring'])
		argv = parse_qs(argv.query)
		for a in argv:
			argv[a] = argv[a][0]
		operation = request['method']
	else:
		operation = event['httpMethod']
		if operation == 'GET':
			argv = event['queryStringParameters']
		else:	# POST, we expect
			argv = urlparse('?' + event['body'])
			argv = parse_qs(argv.query)
			for a in argv:
				argv[a] = argv[a][0]
	if operation in ('GET', 'POST'):
		html = "What happened?"	# in case of error
		try:
			signal.signal(signal.SIGALRM, timeout_handler)
			when = math.floor(context.get_remaining_time_in_millis() / 1000) - 1
			signal.alarm(when)
			html = prepareResponse(argv, context)
			logger.info("## RESPONSE GENERATED, length %d", len(html))
		except MyTimeout:
			logger.info("## TIMEOUT HANDLED")
			html = timeoutResponse.format(argv)
		except Exception:	# pylint: disable=broad-except
			logger.info("## OTHER EXCEPTION %s", traceback.format_exc())
			html = exceptionInfo(traceback.format_exc(), event)
		finally:
			signal.alarm(0)
		return respond(None, on_edge, html)
	logger.info('NOT A GET OR POST, but a %s', operation)
	return respond(ValueError(f'Unsupported method "{operation}"'), on_edge)

class FakeContext:  # pylint: disable=too-few-public-methods
	'''
	For CGI, just enough context for lambda_handler
	'''
	def get_remaining_time_in_millis(self):
		"""TODO"""
		return 300000

# If CGI, create event and context to pass to lambda_handler
if not on_aws():
	import sys
	import urllib.parse
	my_event = {}
	my_event['httpMethod'] = "GET"  # Do NOT make this POST, even if it's POST
	my_event['queryStringParameters'] = {}
	if len(sys.argv) > 1:
		# command line
		my_event['queryStringParameters']['u'] = sys.argv[1]
		if len(sys.argv) > 2:
			my_event['queryStringParameters']['oob'] = sys.argv[2]
	else:
		# web cgi
		method = os.environ['REQUEST_METHOD']
		if method == 'GET':
			qs = urllib.parse.parse_qs(os.environ['QUERY_STRING'])
		elif method == 'POST':
			ctype = os.environ['CONTENT_TYPE']
			if ctype == 'application/x-www-form-urlencoded':
				qs = urllib.parse.parse_qs(str(sys.stdin.read()))
		for q in qs:
			my_event['queryStringParameters'][q] = qs[q][0]
	my_event['requestContext'] = {}
	my_event['requestContext']['domainName'] = "fedora2"
	my_event['requestContext']['path'] = "/right.here/"
	response = lambda_handler(my_event, FakeContext())
	print(f'Content-Type: {response["headers"]["Content-Type"]}')
	print()
	print(response['body'])
