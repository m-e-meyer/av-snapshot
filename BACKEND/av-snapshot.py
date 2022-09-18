#!/usr/bin/python
# -*- coding: UTF-8 -*-

# enable debugging
import cgitb
cgitb.enable()

# Import these packages at a minimum
import cgi
import os
import logging
import signal
import math
import traceback
from urllib.parse import urlparse, parse_qs
# End of mandatory packages
import base64
from datetime import datetime

NUM_LEVELS = 32
IMAGES = 'https://d2uyhvukfffg5a.cloudfront.net'

# Set this to the CGI location of all files this application will read
CGI_TASK_ROOT = "/home/markmeyer/kol/data"


def on_aws():
	return ("LAMBDA_TASK_ROOT" in os.environ)

def arg_to_bytes(state, argv, key, eltsize):
	if key in argv:
		size = len(state[key])
	else:
		size = 500	# way too big, but big enough
	bits = (size+1)*eltsize	# pad a little
	tgtlen = round(bits/24.0 + 0.51) * 4  # 24 bits = 4 base 64 characters
	if key in argv:
		b64 = argv[key].replace('=','A')
		if len(b64) < tgtlen:
			b64 = b64 + ('A'*(tgtlen - len(b64)))
		return base64.b64decode(b64, altchars='-_')
	return base64.b64decode('A'*tgtlen, altchars='-_')

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
	while (len(result) < size):	
		result.append(0)	# make sure list is as big as the datafiles expect
	return result


# This function is to handle opening files in CGI or in AWS
def open_file_for_reading(filename):
	if on_aws():
		return open(os.environ["LAMBDA_TASK_ROOT"]+"/"+filename, "r")
	else:
		return open(CGI_TASK_ROOT+"/"+filename, 'r')


# Accumulate HTML output
OUTPUT = []
def o(str):
	OUTPUT.append(str)
def o_split(state):
	state["o-pre-toc"] = OUTPUT[:]
	OUTPUT.clear()


def split_param_string(pstring):
	result = {}
	params = pstring.split('&')
	for pv in params:
		i = pv.find('=')
		result[pv[0:i]] = pv[i+1:]
	return result

def form_param_string(dic):
	prefix = ''
	result = ''
	for p in dic:
		if (p == 'name') or (p == 'update'):
			continue
		result = result + prefix + p + '=' + dic[p]
		prefix = '&'
	return result


def nowstring():
	return datetime.today().strftime('%Y-%m-%d %H:%M:%S')


if on_aws():
	import boto3
	from boto3.dynamodb.conditions import Key, Attr
	def log_error(err, msg):
	    resp = err.response['Error']
	    logger.error(msg + f": {err['Code']}: {err['Message']}")
	def lookup(name, on_or_before='9999-99-99 99:99:99'):
		db = boto3.resource('dynamodb', region_name='us-east-1')
		table = db.Table('av_snapshot')
		name = name.lower()
		try:
			response = table.query(KeyConditionExpression=Key('name').eq(name))
			result = {}
			last_time = '0000-00-00 00:00:00'
			for rec in response['Items']:
				tstamp = rec['tstamp']
				if (tstamp < on_or_before) and (last_time < tstamp):
					result = split_param_string(rec['state'])
					result["tstamp"] = tstamp
			return result
		except ClientError as err:
		    log_error("Fetch failed", err)
		    raise
	def save(name, state):
		db = boto3.resource('dynamodb', region_name='us-east-1')
		table = db.Table('av_snapshot')
		try:
		    table.put_item(
		        Item = {
		            'name': name.lower(),
		            'tstamp': nowstring(),
		            'state': form_param_string(state)
		        })
		except ClientError as err:
		    log_error("Fetch failed", err)
		    raise
else:
	import mysql.connector
	def lookup(name, on_or_before='9999-99-99 99:99:99'):
		name = name.lower()
		last_time = '0000-00-00 00:00:00'
		cnx = mysql.connector.connect(user='mmeyer', password='', host='localhost', database='m')
		cursor = cnx.cursor()
		cursor.execute(f"SELECT * FROM av_snapshot WHERE name='{name}'")
		result = {}
		for (name, tstamp, state) in cursor:
			if (tstamp < on_or_before) and (last_time < tstamp):
				result = split_param_string(state)
				result["tstamp"] = tstamp
		cursor.close()
		cnx.close()
		return result
	def save(name, state):
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
	"""
	return f'<a href="http://kol.coldfront.net/thekolwiki/index.php/{link}">{text}</a>'


def getbits(byts, index, eltsize):
	loc = index * eltsize;
	bytloc = loc >> 3;
	bytoffs = loc % 8;
	mask = (1 << eltsize) - 1
	if (bytoffs+eltsize) > 8:
		bb = byts[bytloc]*256+byts[bytloc+1]
		return (bb >> (16-bytoffs-eltsize)) & mask    
	else:
		return (byts[bytloc] >> (8-bytoffs-eltsize)) & mask

def load_data_file(filename):
	map = {}
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
			map[maxx] = l;
	return map

def load_data(state):
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

def hx(tag, text, link):
	o(f"<table class='nobord' cellspacing=0 cellpadding=0><tr><td class='noshrink'>"
	  f"<{tag} id='{link}'>{text}</{tag}></td>"
	  "<td>[<a href='#top'>back to top</a>]</td></tr></table>")

def h1(state, text, link):
	hx('h1', text, link)
	state['toc'].append([text, link, []])

def h2(state, text, link):
	hx('h2', text, link)
	last = state['toc'][len(state['toc'])-1]
	last[2].append((text, link))


###########################################################################

def print_beginning(state, name, argv, fetched_argv, colorblind):
	tstamp = fetched_argv['tstamp']
	o("<!DOCTYPE html>\n")
	o("<html><head><style>")
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
	o(f"<div class='header'>Snapshot for <b>{name}</b> taken {tstamp} using av-snapshot.ash v{av_version} running on KoLmafia revision r{mafia}.<br/>")
	query = f"?u={name}"
	if 'on_or_before' in argv:
		query = query + '&on_or_before=' + argv['on_or_before']
	if colorblind:
		switch = 'off'
	else:
		switch = 'on'
		query = query + '&colorblind=1'
	if on_aws():
		suffix = ''
	else:
		suffix = '.py' 
	o(f"Please click <a href='av-snapshot{suffix}{query}'>here</a> to turn {switch} colorblind mode.</div>\n")
	o("<p></p><table class='nobord' cellspacing=0 cellpadding=0><tr><td class='nobord'><button onclick='toggle_toc();' id='showhide'>Hide</b></td>"
	  "<td class='nobord' style='font-size:1.5em;' valign='center'><b>Table of Contents</b></td></tr></table><div id='toc'>")
	o_split(state)
	o("</div>")


###########################################################################

def class_for_perm(skill_bytes, skill_num):
	lvl = getbits(skill_bytes, skill_num, 2)
	if lvl == 0:
		return ''
	elif lvl == 1:
		return "class='perm'"
	else:
		return "class='hcperm'"

def print_skill_cell(skills, skill_bytes, skill_num, suffix=''):
	if skill_num == 0:
		o("<td></td>")
		return
	skil = skills[skill_num]
	clas = class_for_perm(skill_bytes, skill_num)
	if skil[2] != '' and skil[2] != 'none' and skil[2] != '-':
		desc = "<br/>" + skil[2]
	else:
		desc = "" 
	name = skil[1]
	flags = skil[4]
	if 'p' in flags:
		ibeg, iend = "<i>", "</i>"
	else:
		ibeg, iend = '', ''
	if 'c' in flags:
		classist = '&copy;'
	else:
		classist = ''
	if 'b' in flags:
		usedbook = '&marker;'
	else:
		usedbook = ''
	o(f"<td {clas}>{ibeg}{wikilink(name, name+suffix)} {classist}{usedbook}"
		f"<small>{desc}</small>{iend}</td>")

# Map av-snapshot skill numbers to positions in levels string
LEVELED_SKILLS = {315:3, 316:4, 322:5, 326:6, 329:7, 343:8, 389:9, 402:10}
def gen_suffix(skill, levels):
	if skill in LEVELED_SKILLS:
		lv = levels[LEVELED_SKILLS[skill]:LEVELED_SKILLS[skill]+1]
		lv = str(int(lv, 36))
		if skill == 315:	# belch the rainbow
			return f' {lv}/11'
		else:
			return f': Level {lv}'
	return ''

def print_skill_row(state, header, skill_list, levels=''):
	skills = state['skills']
	skill_bytes = state['skill-bytes']
	o(f"<tr><th>{header}</th>")
	for s in skill_list:
		print_skill_cell(skills, skill_bytes, s, gen_suffix(s, levels))
	o("</tr>\n")

def print_slime_row(state, levels):
	skills = state['skills']
	skill_bytes = state['skill-bytes']
	o("<tr><th>The Slime Tube</th>")
	for i in range(0, 3):
		suffix = f" ({levels[i:i+1]}/10)"
		print_skill_cell(skills, skill_bytes, 139+i, suffix)
	print_skill_cell(skills, skill_bytes, 0)
	print_skill_cell(skills, skill_bytes, 0)
	print_skill_cell(skills, skill_bytes, 0)
	o("</tr>\n")

def print_skill_multirow(state, header, skill_list_list, levels=''):
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

def print_skill_table(state, levels):
	o(f'<table cellspacing="0">')
	o('<tr><th>Level</th><th>Seal Clubber</th><th>Turtle Tamer</th><th>Pastamancer</th>'
		  '<th>Sauceror</th><th>Disco Bandit</th><th>Accordion Thief</th></tr>')
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
	o('<tr><th colspan="7" class="miniheader">Other Standard Class Skills</th><tr>')
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
                                          (316, 232, 343, 355, 389, 0)), levels)
	print_slime_row(state, levels)
	print_skill_row(state, "Misc", (309, 142, 143, 200, 145, 146))
	o('<tr><th colspan="7" class="miniheader">Other Nonstandard Class Skills</th><tr>')
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
	print_skill_row(state, 'Crimbo 2022<br/>Crimbotatogoogoneathon', 
					(419,0,0,0,0,0))
	o('<tr><th colspan="7" class="miniheader">Other</th><tr>')
	print_skill_row(state, 'Trader 2008', (144,0,0,0,0,0))
	print_skill_row(state, 'The Suburbs of Dis', (187,188,189,0,0,0))
	print_skill_row(state, 'Silent Invasion', (194,195,196,0,0,0))
	print_skill_row(state, 'Ascension', (183,192,334,315,0,0), levels)
	print_skill_multirow(state, 'Elemental Planes', 
						((312,313,317,320,321,330), (331,332,333,340,341,342), 
						 (346,347,344,345,0,0)))
	print_skill_row(state, 'LT&T', (352,353,354,0,0,0))
	print_skill_row(state, 'Twitch', (314,0,0,0,0,0))
	print_skill_row(state, 'Waffle House', (356,357,0,0,0,0))
	print_skill_row(state, 'Deck of Every Card', (335,336,337,338,339,0))
	print_skill_row(state, 'Snojo', (349,350,351,0,0,0))
	print_skill_row(state, 'Eldritch Love', (359,366,371,418,0,0))
	print_skill_row(state, 'Gingerbread', (365,362,364,363,0,0))
	print_skill_row(state, 'Spacegate', (367,368,369,370,0,0))
	print_skill_row(state, 'PirateRealm', (400,401,0,0,0,0))
	print_skill_row(state, 'Drippy', (406,407,408,0,0,0))
	print_skill_multirow(state, 'Misc', 
						((147,185,162,170,171,181), (193,327,358,372,386,387), 
						 (388,390,402,404,405,409), (410,417,0,0,0,373)), levels)
	o('<tr><th colspan="7" class="miniheader">Mystical Bookshelf</th><tr>')
	print_skill_row(state, 'Tomes', (154, 155, 156, 182, 308, 319))
	print_skill_multirow(state, 'Librams', ((157, 158, 159, 165, 184, 186),
												(201, 0, 0, 0, 0, 0)))
	print_skill_row(state, 'Grimoires', (160, 161, 180, 245, 318, 0))
	o('</table>\n')

def print_skills(state, levels):
	h1(state, "Skills", "a_skills")
	tally = [0, 0, 0]
	skill_bytes = state['skill-bytes']
	for i in range(len(state['skills'])):
		x = getbits(skill_bytes, i+1, 2)
		tally[x] = tally[x] + 1
	o(f"<p class='subheader'>You have {tally[2]} skills Hardcore permed,"
	  f" {tally[1]} skills Softcore permed, and {tally[0]} missing.</p>\n"
	  "<p>Explanation of symbols: <i>Italicized</i> skills are Passive;"
	  " &copy; marks skills really useful only to their classes;"
	  " &marker; marks skills that can be relearned from a used skillbook or such</p>")
	print_skill_table(state, levels)


###########################################################################

def print_tattoo_cell(tattoos, tattoo_bytes, tat, levels=""):
	if tat == 0:
		o("<td></td>")
	elif tat == -1:		# Hobo tattoo
		lv = int(levels[11:12], 36)	# base-36 digit
		clas = ""
		if lv > 0:
			if lv >= 19:
				clas = "class='hcperm'"
			else:
				clas = "class='perm'"
		img = ""
		if lv > 0:
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
		o(f"<td {clas}><img src='{IMAGES}/otherimages/sigils/{t[2]}.gif'><br/>{t[1]}</td>")

def print_tattoo_table(state, tattoos, tattoo_bytes, header, rows, levels=""):
	h2(state, header, "a_"+header)
	o('<table cellspacing="0">')
	for row in rows:
		o("<tr>")
		for tat in row:
			print_tattoo_cell(tattoos, tattoo_bytes, tat, levels)
		o("</tr>")
	o("</table>")

def print_tattoos(state, levels):
	tattoos = state['tattoos']
	tattoo_bytes = state['tattoo-bytes']
	h1(state, "Tattoos", "a_tattoos")
	tally = [0, 0, 0]
	for i in range(len(tattoos)):
		x = getbits(tattoo_bytes, i+1, 2)
		tally[x] = tally[x] + 1
	tally[0] = tally[0] - 8		# sneaky pete xxix and awol each have 4 redundant 
	if levels[11:12] != '0':
		tally[0] = tally[0] - 1		# hobo tattoo of any level counts
		tally[1] = tally[1] + 1
	o(f"<p class='subheader'>You have {tally[1]} tattoos and {tally[2]} outfits for which"
	  f" you don't have the corresponding tattoo, and are missing {tally[0]} tattoos.</p>\n")
	print_tattoo_table(state, tattoos, tattoo_bytes, "Class", 
		((1, 2, 3, 108),
		 (4, 5, 6, 109),
		 (7, 8, 9, 110),
		 (10, 11, 12, 111),
		 (13, 14, 15, 112),
		 (16, 17, 18, 113),
		 (144, 145, 149, 150),
		 (155, 156, 179, 180),
		 (194, 195, 211, 212),
		 (213, 214, 215, 216),
		 (228, 229, 257, 258),
		 (268, 269, 281, 0)))
	print_tattoo_table(state, tattoos, tattoo_bytes, "Ascension", 
		((19, 20, 21, 22, 23, 24),
		 (25, 26, 27, 28, 29, 30),
		 (31, 32, 33, 34, 35, 36),
		 (37, 38, 39, 40, 41, 42),
		 (43, 44, 45, 0, 0, 0)))
	# do outfit table - we assume any tattoo with a component is an outfit
	h2(state, "Outfits", "a_outfits")
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
		print_tattoo_cell(tattoos, tattoo_bytes, t+1)
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
	print_tattoo_table(state, tattoos, tattoo_bytes, "Other", 
		((126, 130, 131, 139, 142, 0),
		 (132, 133, 134, 135, 136, 0),
		 (103, 104, 118, 106, 127, 128),
		 (125, 140, 148, 178, 193, 192),
		 (172, 173, 174, 175, 176, 177),
		 (196, 203, 205, 209, 208, -1),
		 (217, 278, 219, 220, 221, 227),
		 (224, 231, 232, 233, 242, 246),
		 (247, 248, 254, 260, 271, 273),
		 (274, 275, 276, 0, 0, 0)), levels)
	return tally[1]


###########################################################################

def print_trophy_cell(clas, imgname, trophy, desc):
	imgname = imgname.replace('_thumb', '')
	if (imgname == 'nopic'):
		imgname = 'itemimages/' + imgname
	else:
		imgname = 'otherimages/trophy/' + imgname
	o(f"<td {clas}'>"
				+f"<img src='{IMAGES}/{imgname}.gif' style='width:50px; height:50px;'><br>"
				+f"{wikilink(trophy, desc)}</td>")

def print_trophies(state):
	trophy_bytes = state['trophy-bytes']
	h1(state, "Trophies", "a_trophies")
	o("<table cellspacing='0'><tr>")
	tally = [0, 0]
	trophies = state['trophies']
	for i in range(len(trophies)):
		x = getbits(trophy_bytes, i+1, 1)
		tally[x] = tally[x] + 1
	o(f"<p class='subheader'>You have {tally[1]} trophies and are missing {tally[0]} trophies.</p>\n")
	ct = 1
	for i in range(1, len(trophies)+1):
		t = trophies[i]
		clas = ""
		if (i == 13):
			print_trophy_cell('', 'nopic', 'Noble Ascetic', 'Have Less Than 10,000 Meat')
			ct = ct + 1
		elif (i == 144):
			o("<td></td>")
			ct = ct + 1
		if (getbits(trophy_bytes, i, 1)):
			clas = 'class="hcperm"'
		print_trophy_cell(clas, t[1], t[2], t[3])
		if (ct % 10 == 0):
			o("</tr><tr>")
		ct = ct + 1
	while ((ct % 10) != 1):
		o("<td></td>")
		ct = ct + 1
	o("</tr></table>\n")
	return tally[1]


###########################################################################

def print_familiar_cell(clas, imgname, name):
	if (clas != ''):
		clas = "class='" + clas + "'"
	if imgname.find('otherimages') < 0:
		imgname = 'itemimages/' + imgname + '.gif'
	elif imgname.find('camelfam') >= 0:
		# Melodramedary is a special case, need 2 images
		imgname = f"{imgname}'><img src='{IMAGES}/otherimages/camelfam_right.gif"
	wikitext = f"<img src='{IMAGES}/{imgname}'><br/>{name}"
	o(f"<td {clas}>{wikilink(name, wikitext)}</td>")

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
# TODO: fix below with new values
FAM_STYLES = { 0:"", 1:"fam_have", 2:"fam_have_hatch", 3:"fam_run_100", 4:"fam_run_90", 
			5:"fam_run_100", 6:"fam_run_100", 7:"fam_run_90", 8:"fam_run_90" }

def print_familiars(state):
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
	h1(state, "Familiars", "a_familiars")
	o(f"<p class='subheader'>You have {have} familiars (missing {lack}), have done {tour} tourguide runs and {hundred} 100% runs.</p>")
	o("<table cellspacing='0'><tr>")
	# First, regular familiars
	ct = 1
	for i in range(1, len(state['familiars'])+1):
		f = familiars[i]
		fnum = int(f[0])
		if ((fnum >= 201) and (fnum <=245)) or (f[3] == '-'):
			# Skip if Pokefam or no hatchling (April Foolmiliar)
			continue
		style = FAM_STYLES[getbits(familiar_bytes, i, 4)]
		print_familiar_cell(style, f[2], f[1])
		if (ct % 10 == 0):
			o("</tr><tr>")
		ct = ct + 1
	while ((ct % 10) != 1):
		o("<td></td>")
		ct = ct + 1
	# Next, legend
	o("</tr></table><b>Legend</b><br/><table cellspacing='0'><tr>"
		+'<td class="fam_run_100">100% Run Done</td>'
	    +'<td class="fam_run_90">90% Run Done</td>'
	    +'<td class="fam_have">Have Familiar</td>'
	    +'<td class="fam_have_hatch">Have Familiar Hatchling</td>'
	    +"<td class='fam_missing'>Don't have Familiar</td>")
	# Next, Pokefams
	o("</tr></table>")
	h2(state, "Pocket Familiars", "a_pokefam")
	o("<table cellspacing='0'><tr>\n")
	ct = 1
	for i in range(201, 246):
		f = familiars[i]
		style = FAM_STYLES[getbits(familiar_bytes, i, 4)]
		print_familiar_cell(style, f[2], f[1])
		if (ct % 10 == 0):
			o("</tr><tr>")
		ct = ct + 1
	while ((ct % 10) != 1):
		o("<td></td>")
		ct = ct + 1
	# Finally, April Foolmiliars
	o("</tr></table>")
	h2(state, "April Foolmiliars", "a_foolmiliars")
	o("<table cellspacing='0'><tr>\n")
	for i in range(270, 279):
		f = familiars[i]
		style = FAM_STYLES[getbits(familiar_bytes, i, 4)]
		print_familiar_cell(style, f[2], f[1])
	o("</tr></table>")
	return have


###########################################################################

def print_item_link_cell(name, is_owned):
	clas = ''
	if is_owned:
		clas = " class='hcperm'"
	o(f"<td style='margin: 5px' {clas}>{wikilink(name, name)}</td>")

def print_mritem_cell(state, it, subtable=False):
	if it == 0:
		o("<td></td>")
	elif type(it) is tuple:
		o("<td style='margin:0;padding:0'><table height='100%' cellspacing='0'><tr>")
		print_mritem_cell(state, it[0], True)
		print_mritem_cell(state, it[1], True)
		o("</tr></table></td>")
	else:
		mritems = state['mritems']
		counts = state['mritem-counts']
		name = mritems[it][2]		
		clas = ''
		if counts[it-1] > 0:			
			if subtable:
				clas = " class='hcperm noshrink'"
			else:
				clas = " class='hcperm'"
		elif subtable:
			clas = " class='noshrink'"
		o(f"<td style='margin: 5px' {clas}>{wikilink(name, name)}</td>")

def print_coolitem_cell(state, it, print_image=True):
	if type(it) == tuple:
		colspan = " colspan=" + str(it[1])
		it = it[0]
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
		o(f"<td style='margin: 5px' {clas}{colspan}>{wikilink(name, lbody)}</td>")

def print_header_cell(header):
	o(f"<th>{header}</th>")

def print_coolitem_row(state, its, print_image=True):
	o("<tr>")
	for it in its:
		if type(it) != str:
			print_coolitem_cell(state, it, print_image)
		else:
			print_header_cell(it)
	o("</tr>")

def print_coolitem_table(state, headers, rows):
	o("<table cellspacing='0'>")
	if headers:
		o("<tr>")
		for h in headers:
			print_header_cell(h)
		o("</tr>")
	for r in rows:
		print_coolitem_row(state, r)
	o("</table>\n")

def print_mritem_row(state, header, items):
	o("<tr>")
	print_header_cell(header)
	for it in items:
		print_mritem_cell(state, it)
	o("</tr>")

def print_mritem_table(state, yr, headers, rows):
	o("<table class='morepad' cellspacing='0'><tr>")
	for h in headers:
		print_header_cell(h)
	o("</tr>")
	for row in rows:
		print_mritem_row(state, yr, row)
		yr = yr + 1
	o("</table>")

def print_mritems(state):
	h1(state, "Mr. Items", "a_mritems")
	print_mritem_table(state, 2004, 
		('', 'January', 'February', 'March', 'April', 'May', 'June',
			'July', 'August', 'September', 'October', 'November', 'December'),
		((0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 2, 3),
		(4, 5, 6, (7, 8), 9, 10, 11, 12, 13, 14, 15, 16),
		(17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28),
		(29, 30, 21, 32, 33, 34, 35, 36, 37, 38, 39, 40),
		(41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52),
		(53, 54, 55, (66, 56), 57, 58, 59, 60, 61, 62, 63, 64),
		(65, 79, 57, 80, 81, 82, 83, 84, 85, 86, 89, 90),
		(91, 94, 95, 57, 96, 97, 98, 99, 100, 101, 102, 103),
		(104, 107, 108, 109, 57, 111, 112, 113, 114, 115, 116, 117),
		(118, 121, 122, 123, 124, 125, 57, 127, 128, 129, 130, 131),
		(132, 135, 136, 137, 138, 139, 57, 140, 141, 142, 143, 144),
		(145, 148, 148, 149, 150, (152, 153), 154, 155, 156, 157, 158, 159),
		(160, 162, 163, 57, 164, 165, 166, 167, 168, 172, 173, 174),
		(175, 177, 178, 179, 180, 181, 182, 183, 185, 186, 187, 188),
		(189, 57, 191, 192, 193, 194, 195, 196, 197, 198, 199, 200),
		(202, 203, 204, 205, 206, 207, 208, 209, 210, 211, 212, 213),
		(215, 216, 217, 218, 219, 220, 221, 222, 223, 224, 225, 226),
		(228, 229, 230, 231, 232, 233, 57, 234, 235, 236, 237, 238),
		(240, 241, 242, 243, 244, 245, 246, 247, 248, 0, 0, 0) ))
	h2(state, "Mr. Yearly Items", "a_mryearly")
	print_mritem_table(state, 2005, 
		('', 'Volleychaun', 'Fairychaun', 'Fairyball', 'FairyWhelp', 'Equipment'),
		((67, 68, 0, 0, 0),
		(75, 76, 0, 0, 0),
		(73, 74, 0, 0, 0),
		(71, 72, 0, 0, 0),
		(69, 70, 0, 0, 0),
		(77, 78, 0, 0, 0),
		(88, 87, 0, 0, 0),
		(105, 106, 0, 0, 0),
		(119, 120, 0, 0, 0),
		(133, 134, 0, 0, 0),
		(146, 147, 0, 0, 0),
		(0, 0, 161, 0, 0),
		(0, 0, 176, 0, 0),
		(0, 0, 0, 190, 0),
		(0, 0, 201, 0, 0),
		(0, 0, 0, 0, 214),
		(0, 0, 0, 0, 227),
		(0, 0, 0, 0, 239)))
	# This is a weird case, a mix of Mr. Items and Cool items
	h2(state, "Jick's Mom and Janet's Merchandise Table", "a_merch")
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
	o("<td></td><td></td><td></td><td></td><td></td></tr><tr>")
	print_mritem_cell(state, 184)
	o("<td></td><td></td><td></td><td></td><td></td></tr></table>")
	#for i in range(len(mritem_counts)):
	#	o(f'{i+1}:{mritem_counts[i]} ')


###########################################################################

def print_loot_row(state, header, items, pad=0):
	o("<tr>")
	if header != '':
		o(f"<th>{header}</th>")
	for it in items:
		print_coolitem_cell(state, it)
	if pad > 0:
		o("<td></td>"*pad)
	o("</tr>")

def print_basement(state):
	h1(state, "Basement", "a_basement")
	h2(state, "Hobopolis", "a_hobopolis")
	o("<table cellspacing='0'><tr><th>Boss</th><th colspan='3'>Outfit Pieces</th><th colspan='3'>Other Pieces</th></tr>")
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
	h2(state, "Hobo Code Binder", "a_hobocode")
	o("<p>Coming soon!</p>")
	h2(state, "Hobo (and other) Equipment", "a_hobocode")
	print_coolitem_table(state, ('', 'Hat', 'Pants', 'Accessories'),
							(('150 Nickels', 27, 30, 34),
							 ('200 Nickels', 28, 29, 33),
							 ('250 Nickels', 26, 31, 32)))
	h2(state, "Hobo Instruments", "a_hobocode")
	print_coolitem_table(state, ('Seal Clubber', 'Turtle Tamer', 'Pastamancer', 'Sauceror', 'Disco Bandit', 'Accordion Thief'),
						(range(1, 7),))
	h2(state, "Slime Tube", "a_tube")
	o("<table cellspacing='0'>")
	print_loot_row(state, "", range(516, 522))
	print_loot_row(state, "", range(522, 528))
	print_loot_row(state, "", range(528, 532), 2)
	print_loot_row(state, "", range(532, 537), 1)
	o("</table>")
	h2(state, "Dreadsylvania", "a_dread")
	o("<table cellspacing='0'><tr><th>Boss</th><th colspan='3'>Outfit Pieces</th><th colspan='3'>Other Pieces</th></tr>")
	print_loot_row(state, "Great Wolf", range(84, 90))
	print_loot_row(state, "Falls-From-Sky", range(90, 96))
	print_loot_row(state, "Mayor Ghost", range(96, 102))
	print_loot_row(state, "Zombie", range(102, 108))
	print_loot_row(state, "Unkillable Skeleton", range(108, 114))
	print_loot_row(state, "Count Drunkula", range(114, 120))
	o("</table>")
	#for i in range(len(coolitem_counts)):
	#	o(f'{i+1}:{coolitem_counts[i]} ')


###########################################################################

def print_ascension_rewards(state):
	h2(state, "Ascension Rewards", "a_ascension")
	rewards = (range(555, 561), 
		range(561, 567),
		range(567, 573),
		range(573, 579),
		range(579, 585),
		range(585, 591),
		range(591, 597),
		range(597, 603),
		range(603, 609),
		range(609, 615),
		range(615, 621),
		range(621, 627),
		range(627, 633),
		range(633, 639),
		range(639, 645),
		range(645, 651),
		range(651, 657),
		range(657, 663),
		range(663, 669),
		range(669, 675))
	have = 0
	havent = 0
	counts = state['coolitem-counts']
	for row in rewards:
		for it in row:
			if counts[it-1] == 0:
				havent = havent + 1
			else:
				have = have + 1
	o(f"<p>You have {have} and are missing {havent}.</p>")
	print_coolitem_table(state, None, rewards)

def print_looking_glass_table(state):
	o("<table cellspacing='0'>")
	print_coolitem_row(state, range(180, 186))
	o("<tr>")
	print_coolitem_cell(state, 186)
	print_coolitem_cell(state, 187)
	levels = state['levels']
	chess = int(levels[26:28], 36)
	if chess == 0:
		clas = ''
	elif chess == 50:
		clas = " class='hcperm'"
	else:
		clas = " class='perm'"
	chesstext = f"<img src='{IMAGES}/itemimages/chesscookie.gif'><br/>Chess Boards Completed {chess}/50"
	o(f"<td{clas}>{wikilink('The_Great_Big_Chessboard',chesstext)}</a></td>"
		"<td></td><td></td><td></td></tr></table>\n")

def print_coolitems(state):
	h1(state, "Cool Items", "a_coolitems")
	h2(state, "Ultrarares", "a_ultra")
	print_coolitem_table(state, None, ((38, 39, 40, 41, 42, 137, 43, 44),
									(45, 46, 47, 178, 48, 409, 0, 0)))
	print_ascension_rewards(state)
	h2(state, "Swagger Stuff", "a_pvp")
	print_coolitem_table(state, None, (range(207, 213),
									(213, 214, 215, 335, 450, 0)))
	h2(state, "Thwaitgold", "a_thwait")
	print_coolitem_table(state, None, ((54, 55, 56, 57, 60, 61),
									(62, 82, 83, 135, 136, 173),
									(174, 175, 176, 177, 179, 252),
									(291, 297, 313, 353, 360, 362),
									(382, 390, 391, 415, 421, 425),
									(442, 446, 447, 452, 453, 454),
									(537, 538, 539, 0, 0, 0)))
	h2(state, "War Medals", "a_medals")
	print_coolitem_table(state, ('Sidequests', '0', '1', '2', '3', '4', '5', '6'), 
		(('Hippy', 540, 541, 542, 543, 544, 545, 546),
		('Frat', 547, 548, 549, 550, 551, 552, 553),
		('All', (554, 7))))
	h2(state, "Sea Stuff", "a_sea")
	print_coolitem_table(state, None, (range(63, 69), range(69, 75), range(75, 82)))
	h2(state, "Chefstaves", "a_staves")
	print_coolitem_table(state, None, (range(13, 19),
									(19, 58, 20, 21, 22, 23),
									(24, 25, 53, 59, 172, 272),
									(386, 401, 441, 0, 0, 0)))
	#
	h2(state, "Marty's Quest", "a_marty")
	print_coolitem_table(state, None, (range(216, 220),))
	h2(state, "Secrets from the Future (2009)", "a_secrets")
	print_coolitem_table(state, ('Seal Clubber', 'Turtle Tamer', 'Pastamancer', 'Sauceror', 'Disco Bandit', 'Accordion Thief'),
						(range(7, 13),))
	h2(state, "Underworld (2009)", "a_underworld")
	print_coolitem_table(state, None, (range(35, 38),))
	h2(state, "A Moment of Reflection (2010)", "a_reflection")
	print_looking_glass_table(state)
	h2(state, "Arcade Games (2010)", "a_arcade")
	print_coolitem_table(state, None, (range(410, 415),))
	h2(state, "Necbromancer (2011)", "a_necbro")
	print_coolitem_table(state, None, (range(50, 53),))
	h2(state, "Raiments of the Final Boss (2013)", "a_raiments")
	print_coolitem_table(state, None, (range(120, 128),))
	h2(state, "Psychoanalysis (2013)", "a_psycho")
	print_coolitem_table(state, None, (range(128, 135),))
	h2(state, "Warbear Crimbo (2013)", "a_warbear")
	print_coolitem_table(state, None, 
		(range(138, 147), range(147, 156), range(156, 165), (165, 166, 0, 0, 0, 0, 0, 0, 0))) 
	h2(state, "We All Wear Masks (2014)", "a_masks")
	print_coolitem_table(state, None, (range(167, 172),))
	h2(state, "Conspiracy Island (2014)", "a_conspiracy")
	print_coolitem_table(state, None, (range(200, 207),))
	h2(state, "Dinseylandfill (2015)", "a_dinsey")
	print_coolitem_table(state, None, (range(188, 194), range(194, 200)))
	h2(state, "That 70s Volcano (2015)", "a_volcano")
	print_coolitem_table(state, None, 
		((248, 249, 250, 253, 254, 255), 
		 range(257, 263),
		 (263, 264, 265, 0, 0, 0)))
	h2(state, "The Glaciest (2015)", "a_glaciest")
	print_coolitem_table(state, None, (range(266, 272),))
	h2(state, "Gotpork (2016)", "a_gotpork")
	print_coolitem_table(state, None, (range(285, 289),))
	h2(state, "LT&T Telegraph Office (2016)", "a_ltt")
	print_coolitem_table(state, None, (range(274, 280), (280, 281, 282, 283, 284, 289)))
	h2(state, "Fishin' Gear (2016)", "a_fishin")
	print_coolitem_table(state, None, ((293, 294),))
	h2(state, "The Precinct (2016)", "a_precinct")
	print_coolitem_table(state, None, ((298, 299, 300),))
	h2(state, "Busting Makes You Feel Good (2016)", "a_busting")
	print_coolitem_table(state, None, (range(301, 307), range(307, 313)))
	h2(state, "Twitchery (most recent 2016)", "a_twitch")
	print_coolitem_table(state, None, 
		((225, 320, 322, 317, 228, 318), 
		 (230, 229, 227, 315, 316, 319),
		 (220, 321, 221, 222, 223, 323),
		 (224, 226, 231, 232, 233, 314)))
	h2(state, "Gingerbread City (2016)", "a_ginger")
	print_coolitem_table(state, None, 
		((347, 345, 348, 349, 350, 352), 
		 (351, 346, 344, 0, 0, 0)))
	h2(state, "Chakra Crimbo (2016)", "a_chakra")
	print_coolitem_table(state, None, ((337, 338, 342, 339, 340, 341, 343),))
	h2(state, "Spacegate (2017)", "a_spacegate")
	print_coolitem_table(state, None, (range(376, 381),))
	h2(state, "Silent Crombotato (2017)", "a_scrimbo")
	print_coolitem_table(state, None, (range(365, 371), (371, 372, 373, 374, 375, 0)))
	h2(state, "FantasyRealm (2018)", "a_fantasy")
	print_coolitem_table(state, None, (range(387, 390),))
	h2(state, "Neverending Party (2018)", "a_party")
	print_coolitem_table(state, None, (range(393, 397), range(397, 401)))
	h2(state, "PirateRealm (2019)", "a_pirate")
	print_coolitem_table(state, None, (range(416, 421),))
	h2(state, "Underwater Crimbo (2019)", "a_uwcrimbo")
	print_coolitem_table(state, None, 
		((429, 430, 439, 440, 437, 427), 
		 (433, 434, 428, 436, 438, 431),
		 (426, 432, 435, 0, 0, 0)))
	h2(state, "Gooified Crimbo (2021)", "a_gcrimbo")
	print_coolitem_table(state, None, (range(455, 461), range(461, 467)))
	h2(state, "Hair Club for Loathers", "a_hairclub")
	print_coolitem_table(state, None, 
		((383, 384, 385, 256, 290, 273), 
		 (292, 295, 296, 336, 354, 355),
		 (356, 357, 358, 359, 361, 363),
		 (364, 381, 392, 422, 423, 424),
		 (443, 444, 445, 451, 0, 0)))
	#for i in range(len(coolitem_counts)):
	#	o(f'{i+1}:{coolitem_counts[i]} ')


###########################################################################

def print_summary(data, bytes):
	have = 0
	havent = 0
	for i in range(1, len(data)+1):
		name = data[i][1]
		if name == "" or name == "-":	# some data entries are empty, don't know why
			continue
		if getbits(bytes, i, 1) > 0:
			have = have + 1
		else:
			havent = havent + 1
	o(f"<p>You have found {have} of these discoveries and are missing {havent}.<br/>"
	  "Are some discoveries not showing up? Turn Inventory Images ON and one-click"
	  " crafting OFF and try again - it has a higher success rate.</p>")

def print_sorted_list(data, bytes):
	print_summary(data, bytes)
	col = 1
	data = list(data.values())
	data = sorted(data, key=lambda d: d[1].upper())
	o("<table cellspacing=0 cellpadding=0><tr>")
	for i in range(0, len(data)):
		name = data[i][1]
		if name == "" or name == "-":	# some data entries are empty, don't know why
			continue
		if name.find('[') >= 0:
			link = name.replace('[', '').replace(']', '')
		else:
			link = name
		x = int(data[i][0])
		clas = ''
		if getbits(bytes, x, 1) > 0:
			clas = ' class="hcperm"'
		o(f"<td{clas}>{wikilink(link, name)}</td>")
		col = col+1
		if col > 6:
			o("</tr><tr>")
			col = 1
	if col > 1:
		while col <= 6:
			o("<td></td>")
			col = col + 1
	o("</tr></table>")


def print_discoveries(state):
	h1(state, "Discoveries", "a_disc")
	h2(state, "Cocktailcrafting", "a_disc_cock")
	print_sorted_list(state['concocktail'], state['concocktail-bytes'])
	h2(state, "Cooking", "a_disc_cook")
	print_sorted_list(state['confood'], state['confood-bytes'])
	h2(state, "Meatpasting", "a_disc_paste")
	print_sorted_list(state['conmeat'], state['conmeat-bytes'])
	h2(state, "Smithing", "a_disc_smith")
	print_sorted_list(state['consmith'], state['consmith-bytes'])
	h2(state, "Miscellaneous Discoveries", "a_disc_misc")
	print_sorted_list(state['conmisc'], state['conmisc-bytes'])

def print_consumption(state):
	h1(state, "Consumption", "a_consum")
	h2(state, "Food", "a_consum_food")
	print_sorted_list(state['food'], state['food-bytes'])
	h2(state, "Booze", "a_consum_booze")
	print_sorted_list(state['booze'], state['booze-bytes'])


###########################################################################

def print_end(state, tats, trophs, fams, levels):
	h1(state, "Miscellaneous Accomplishments", "a_misc")
	o("<h3>Telescope</h3>")
	scope_lvl = levels[25:26]
	if scope_lvl == "0":
		o("<p>You don't have aTelescope in your Campground.</p>")
	else:
		o(f"<p>You have a Telescope in your Campground, and it's level <b>{levels[25:26]}</b>!</p>")
	o("<h3>Karma</h3>")
	o(f"<p>You have <b>{int(levels[12:16], 36)}</b> unspent Karma.</p>")
	o("<h3>Monster Manuel</h3>")
	if (levels[16:25] == "000000000"):
		o("<p>You probably don't have a Monster Manuel.</p>")
	else:
		o(f"<p>You have casually researched <b>{int(levels[16:19], 36)}</b> creatures.<br/>")
		o(f"You have thoroughly researched <b>{int(levels[19:22], 36)}</b> creatures.<br/>")
		o(f"You have exhaustively researched <b>{int(levels[22:25], 36)}</b> creatures.</p>")
	o("<h3>Demon Names</h3>")
	o("<p>Coming soon!</p>")
	o(f"<a name='collectorscore'><h3>Collector's Score: {tats+trophs+fams}"
	  f" (Tattoo: {tats}, Trophy: {trophs}, Familiar: {fams})</a></h3>")
	o("</body></html>\n")


###########################################################################

def generate_toc(entries):
	# First, count how many entries we have
	NUM_COLUMNS = 3
	num_entries = 0
	for entry in entries:
		num_entries = num_entries + 1 + len(entry[2])
	COLSIZE = num_entries//NUM_COLUMNS + 1
	# Now put entries in multicolumn display
	result = []
	e = 0
	result.append("<table class='nobord toc' cellspacing=0 cellpadding=0><tr><td class='toc'>")
	for entry in entries:
		result.append(f"<a href='#{entry[1]}'>{entry[0]}</a><br/>")
		e = e+1
		if (e >= COLSIZE):
			result.append("</td><td class='toc'>")
			e = 0
		for subentry in entry[2]:
			result.append(f"&nbsp;&bull;&nbsp;<a href='#{subentry[1]}'>{subentry[0]}</a><br/>")
			e = e+1
			if (e >= COLSIZE):
				result.append("</td><td class='toc'>")
				e = 0
	result.append("</td></tr></table>")
	return result
	

###########################################################################


def prepareResponse(argv, context):
	'''
	prepareResponse returns the HTML string to send to the browser.
	Call your HTML-generating functions from here.
	'''
	state = {}	# used to capture state of user, instead of globals
	state['toc'] = []
	 
	if 'u' not in argv:
		argv['u'] = 'Aventuristo'	# for local testing
	name = argv['u'].lower()
	if 'colorblind' in argv:
		colorblind = (int(argv['colorblind']) != 0)
	else:
		colorblind = False
	# If updating, just store the state and return
	if ("update" in argv) and (argv["update"] == 'j'):
		save(name, argv)
		return f'<html><head></head><body>Record added for {name}</body></html>'
	#
	if "on_or_before" in argv:
		when = argv["on_or_before"]
	else:
		when = nowstring()
	fetched_argv = lookup(name, when)
	# If lookup failed, report and return
	if len(fetched_argv) == 0:
		return f"<html><head></head><body>Record for user {name} at time {when} not found</body></html>"
	#
	load_data(state)
	print_beginning(state, name, argv, fetched_argv, colorblind)
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
	if "levels" in fetched_argv:
		levels = fetched_argv["levels"]
		if len(levels) < NUM_LEVELS:
			levels = levels + ("0"*(NUM_LEVELS-len(levels)))
	else:
		levels = "0"*NUM_LEVELS
	state['levels'] = levels
	#
	print_skills(state, levels)
	tats = print_tattoos(state, levels)
	trophs = print_trophies(state)
	fams = print_familiars(state)
	print_mritems(state)
	print_basement(state)
	print_coolitems(state)
	print_discoveries(state)
	print_consumption(state)
	#
	print_end(state, tats, trophs, fams, levels)
	pre_toc = ''.join(state["o-pre-toc"])
	toc = ''.join(generate_toc(state['toc']))
	post_toc = ''.join(OUTPUT)
	return pre_toc + toc + post_toc


###########################################################################
######################## BEGIN AWS/CGI BOILERPLATE ########################
###########################################################################

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def respond(err, on_edge, response=None):
	if on_edge:
		headers = {	'content-type': [{ 'key': 'Content-Type', 
								'value': 'text/html; charset=UTF-8' }]}
		statcode = 'status'
	else:
		headers = { 'Content-Type': 'text/html; charset=UTF-8' }
		statcode = 'statusCode'
	return {
		statcode: '400' if err else '200',
		'body': err.message if err else response,
		'headers': headers
	}

def exceptionInfo(trace, event):
	result = trace.replace("\n", "<br/>")
	params = event['queryStringParameters']
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
<p>The page timed out while {}.  Please try reloading the page.
<p>- Aventuristo
</body></html>
'''

class MyTimeout(BaseException):
	pass

def timeout_handler(_signal, _frame):
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
		argv = event['queryStringParameters']
		operation = event['httpMethod']
	if operation == 'GET':
		html = "What happened?"
		try:
			signal.signal(signal.SIGALRM, timeout_handler)
			when = math.floor(context.get_remaining_time_in_millis() / 1000) - 1
			signal.alarm(when)
			html = prepareResponse(argv, context)
			logger.info(f"## RESPONSE GENERATED, length {len(html)}")
		except MyTimeout as e:
			logger.info("## TIMEOUT HANDLED")
			html = timeoutResponse.format(state)
		except Exception as e:
			logger.info("## OTHER EXCEPTION " + traceback.format_exc())
			html = exceptionInfo(traceback.format_exc(), event)
		finally:
			signal.alarm(0)
			return respond(None, on_edge, html)
	else:
		logger.info(f'NOT A GET, but a {operation}')
		return respond(ValueError(f'Unsupported method "{operation}"'), on_edge)

class FakeContext:
	'''
	For CGI, just enough context for lambda_handler
	'''
	def get_remaining_time_in_millis(self):
		return 300000

# If CGI, create event and context to pass to lambda_handler
if not on_aws():
	event = {}
	event['httpMethod'] = "GET"
	event['queryStringParameters'] = {}
	arguments = cgi.FieldStorage()
	for arg in arguments:
		event['queryStringParameters'][arg] = arguments[arg].value
	event['requestContext'] = {}
	event['requestContext']['domainName'] = "fedora2"
	event['requestContext']['path'] = "/right.here/"
	response = lambda_handler(event, FakeContext())
	print(f'Content-Type: {response["headers"]["Content-Type"]}')
	print()
	print(response['body'])