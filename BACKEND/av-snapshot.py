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

# Establish presence of these globals 
MAX_SKILL = 420
MAX_TROPHY = 160
MAX_FAMILIAR = 281
MAX_TATTOO = 200
MAX_MRITEM = 300
MAX_COOLITEM = 500

NUM_LEVELS = 12
IMAGES = 'https://d2uyhvukfffg5a.cloudfront.net'

# Set this to the CGI location of all files this application will read
CGI_TASK_ROOT = "/home/markmeyer/kol/data"


def on_aws():
	return ("LAMBDA_TASK_ROOT" in os.environ)

def arg_to_bytes(argv, key, size, eltsize):
	bits = (size+1)*eltsize
	tgtlen = round(bits/24.0 + 0.49) * 4  # 24 bits = 4 base 64 characters
	if key in argv:
		b64 = argv[key].replace('=','A')
		if len(b64) < tgtlen:
			b64 = b64 + ('A'*(tgtlen - len(b64)))
		return base64.b64decode(b64, altchars='-_')
	return base64.b64decode('A'*tgtlen, altchars='-_')

def arg_to_counts(argv, key, size):
	"""
	Looks up the specified key in argv, and decodes the resulting base64 string into
	a series of bytes (pairs of nybbles), and in turn decodes those nybbles into a list
	of numbers: Each nybble is treated as a octal digit, with the high bit set if and
	only if that octal digit is the last digit of the encoded number.  For example,
	0010 0100 1011 will decode into 163 (2*64+4*8+3).
	"""
	if key in argv:
		b64 = argv[key].replace('=','A')
	else:
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
			l = fil.readline()
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


###########################################################################

def print_beginning(name, argv, fetched_argv, colorblind):
	tstamp = fetched_argv['tstamp']
	o("<!DOCTYPE html>\n")
	o("<html><head><style>")
	with open_file_for_reading('av-snapshot-style.css') as fil:
		o(fil.read())
	bclas = ''
	if colorblind:
		bclas = "class='cb'"
	o(f"</style></head><body {bclas}>\n")
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
DIGITS36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
def gen_suffix(skill, levels):
	if skill in LEVELED_SKILLS:
		lv = levels[LEVELED_SKILLS[skill]:LEVELED_SKILLS[skill]+1]
		lv = DIGITS36.find(lv)
		if skill == 315:	# belch the rainbow
			return f' {lv}/11'
		else:
			return f': Level {lv}'
	return ''

def print_skill_row(state, header, skill_list, levels=''):
	skills = state['skills']
	skill_bytes = state['skill_bytes']
	o(f"<tr><th>{header}</th>")
	for s in skill_list:
		print_skill_cell(skills, skill_bytes, s, gen_suffix(s, levels))
	o("</tr>\n")

def print_slime_row(state, levels):
	skills = state['skills']
	skill_bytes = state['skill_bytes']
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
	skill_bytes = state['skill_bytes']
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
	o("<h1>Skills</h1>")
	tally = [0, 0, 0]
	skill_bytes = state['skill_bytes']
	for i in range(len(state['skills'])):
		x = getbits(skill_bytes, i+1, 2)
		tally[x] = tally[x] + 1
	o(f"<p class='subheader'>You have {tally[2]} skills Hardcore permed, {tally[1]} skills Softcore permed, and {tally[0]} missing.</p>\n")
	print_skill_table(state, levels)


###########################################################################

def print_tattoo_cell(tattoos, tattoo_bytes, tat, levels=""):
	if tat == 0:
		o("<td></td>")
	elif tat == -1:		# Hobo tattoo
		lv = DIGITS36.find(levels[11:12])
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

def print_tattoo_table(tattoos, tattoo_bytes, header, rows, levels=""):
	o(f'<h2>{header}</h2><table cellspacing="0">')
	for row in rows:
		o("<tr>")
		for tat in row:
			print_tattoo_cell(tattoos, tattoo_bytes, tat, levels)
		o("</tr>")
	o("</table>")

def print_tattoos(state, levels):
	tattoos = state['tattoos']
	tattoo_bytes = state['tattoo_bytes']
	o("<h1>Tattoos</h1>")
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
	print_tattoo_table(tattoos, tattoo_bytes, "Class", 
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
		 (268, 269, 0, 0)))
	print_tattoo_table(tattoos, tattoo_bytes, "Ascension", 
		((19, 20, 21, 22, 23, 24),
		 (25, 26, 27, 28, 29, 30),
		 (31, 32, 33, 34, 35, 36),
		 (37, 38, 39, 40, 41, 42),
		 (43, 44, 45, 0, 0, 0)))
	# do outfit table - we assume any tattoo with a component is an outfit
	o(f'<h2>Outfits</h2><table cellspacing="0">')
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
	print_tattoo_table(tattoos, tattoo_bytes, "Other", 
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
	trophy_bytes = state['trophy_bytes']
	o("<h1>Trophies</h1><table cellspacing='0'><tr>")
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
	familiar_bytes = state['familiar_bytes']
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
	o("<h1>Familiars</h1>")
	o(f"<p class='subheader'>You have {have} familiars (missing {lack}), have done {tour} tourguide runs and {hundred} 100% runs.</p>")
	o("<table cellspacing='0'><tr>")
	# First, regular familiars
	ct = 1
	for i in range(1, MAX_FAMILIAR+1):
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
	o("</tr></table><h2>Pocket Familiars</h2><table cellspacing='0'><tr>\n")
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
	o("</tr></table><h2>April Foolmiliars</h2><table cellspacing='0'><tr>\n")
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
		counts = state['mritem_counts']
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
	if it == 0:
		o("<td></td>")
	else:
		coolitems = state['coolitems']
		counts = state['coolitem_counts']
		coolitem = coolitems[it]
		name = coolitem[1]		
		clas = ''
		if counts[it-1] > 0:			
			clas = " class='hcperm'"
		if print_image:
			lbody = f"<img src='{IMAGES}/itemimages/{coolitem[2]}.gif'><br/>{name}"
		else:
			lbody = name
		o(f"<td style='margin: 5px' {clas}>{wikilink(name, lbody)}</td>")

def print_mritem_header(header):
	o(f"<th>{header}</th>")

def print_mritem_row(state, header, items):
	o("<tr>")
	print_mritem_header(header)
	for it in items:
		print_mritem_cell(state, it)
	o("</tr>")

def print_mritem_table(state, yr, headers, rows):
	o("<table class='morepad' cellspacing='0'><tr>")
	for h in headers:
		print_mritem_header(h)
	o("</tr>")
	for row in rows:
		print_mritem_row(state, yr, row)
		yr = yr + 1
	o("</table>")

def print_mritems(state):
	o("<h1>Mr. Items</h1>")
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
	o("<h1>Mr. Yearly Items</h1>")
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
	o("<h1>Jick's Mom and Janet's Merchandise Table</h1><table class='morepad' cellspacing='0'>")
	for r in ((325, 326, 327, 328, 329, 330),
			(331, 332, 333, 334, 0, 0)):
		o("<tr>")
		for i in r:
			print_coolitem_cell(state, i, False)
		o("</tr>")
	o("<tr>")
	print_item_link_cell("Hippo tutu", (getbits(state['familiar_bytes'], 127, 4) > 0))
	print_item_link_cell("Gygaxian Libram", (getbits(state['skill_bytes'], 184, 2) > 0))
	print_item_link_cell("Tome of Rad Libs", (getbits(state['skill_bytes'], 308, 2) > 0))
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

def print_coolitems(state):
	o("<h1>Cool Items</h1>")
	#for i in range(len(coolitem_counts)):
	#	o(f'{i+1}:{coolitem_counts[i]} ')


###########################################################################

def print_end(tats, trophs, fams):
	o(f"<a name='collectorscore'><h2>Collector's Score: {tats+trophs+fams}"
	  f" (Tattoo: {tats}, Trophy: {trophs}, Familiar: {fams})</a></h2>")
	o("</body></html>\n")


	
###########################################################################


def prepareResponse(argv, context):
	'''
	prepareResponse returns the HTML string to send to the browser.
	Call your HTML-generating functions from here.
	'''
	state = {}	# used to capture state of user, instead of globals
	 
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
	print_beginning(name, argv, fetched_argv, colorblind)
	#
	state['skill_bytes'] = arg_to_bytes(fetched_argv, "skills", MAX_SKILL, 2)
	state['tattoo_bytes'] = arg_to_bytes(fetched_argv, "tattoos", MAX_TATTOO, 2)
	state['trophy_bytes'] = arg_to_bytes(fetched_argv, "trophies", MAX_TROPHY, 1)
	state['familiar_bytes'] = arg_to_bytes(fetched_argv, "familiars", MAX_FAMILIAR, 4)
	state['mritem_counts'] = arg_to_counts(fetched_argv, "mritems", MAX_MRITEM)
	state['coolitem_counts'] = arg_to_counts(fetched_argv, "coolitems", MAX_COOLITEM)
	if "levels" in fetched_argv:
		levels = fetched_argv["levels"]
		if len(levels) < NUM_LEVELS:
			levels = levels + ("0"*(NUM_LEVELS-len(levels)))
	else:
		levels = "0"*NUM_LEVELS
	#
	print_skills(state, levels)
	tats = print_tattoos(state, levels)
	trophs = print_trophies(state)
	fams = print_familiars(state)
	print_mritems(state)
	print_coolitems(state)
	#
	print_end(tats, trophs, fams)
	return ''.join(OUTPUT)

###########################################################################
######################## BEGIN AWS/CGI BOILERPLATE ########################
###########################################################################

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def respond(err, on_edge, response=None):
	if on_edge:
		headers = {	'content-type': [{ 'key': 'Content-Type', 'value': 'text/html' }]}
		statcode = 'status'
	else:
		headers = { 'Content-Type': 'text/html' }
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