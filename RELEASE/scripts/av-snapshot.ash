script "av-snapshot.ash";
notify aventuristo;
since r20632;

#	This is a fork of cheesecookie's snapshot script, which is itself
#   a fork of bumcheekcity's snapshot script.
#	Like choosecookie's script, code comes straight from the predecessor,
#	website layout is copied from it, and things are then hacked onto it 
#   in order to increase support. So... yeah.

string VERSION = '1.0.5';	# released 2023-03-25

int NUM_LEVELS = 33;


////////////////////////////

boolean DEBUG = (get_property('avSnapshotDebug') == 'j');
void debug(string s)
{
	if (DEBUG) { print(s, "blue"); }
}


///////////////////////////////

record bitarray {
    int size;
    int eltsize;
    int[int] elts;	// 0-based array of values
};

string to_string(bitarray b)
{
    string result = "bitarray[";
    for i from 0 to b.elts.count()-1 {
        int elt = b.elts[i];
        for j from 0 to b.eltsize-1 {
            result = result + ((elt & (1 << (b.eltsize-j-1))) == 0 ? "0" : "1");
        }
        result = result + " ";
    }
    return result+"]";
}

bitarray new_bitarray(int size, int eltsize)
{
    bitarray b;
    b.size = size;
    b.eltsize = eltsize;
	if (size > 0) {
		for i from 0 to (size-1) {
			b.elts[i] = 0;
		}
	}
	debug(`Created with {size} elements`);
    return b;
}

void set(bitarray b, int index, int val)
{
    if ((index < 0) || (index >= b.size)) {
        print(`Index {index} out of bounds`, "red");
        return;
    }
    if ((val < 0) || (val >= (1 << b.eltsize))) {
        print(`Value {val} out of bounds`, "red");
    }
    b.elts[index] = val;
}

int get(bitarray b, int index)
{
    return b.elts[index];
}

string base64_encode(bitarray b)
{
    string TABLE = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
    int buf = 0;
    int bits = 0;
    string result = "";
    for i from 0 to b.size-1 {
        buf <<= b.eltsize;
        buf += b.elts[i];
        bits += b.eltsize;
        while (bits >= 6) {
            int bits6 = buf >> (bits - 6);
            result = result + TABLE.substring(bits6, bits6+1);
            buf = buf & ((1 << bits-6) - 1);
            bits -= 6;
        }
    }
    if (bits > 0) {
        while (bits < 6) {
            buf <<= b.eltsize;
            bits += b.eltsize;
        }
        int bits6 = buf >> (bits - 6);
        result = result + TABLE.substring(bits6, bits6+1);
    }
    while ((result.length() & 3) != 0) {
        result = result + "=";
    }
    return result;
}

void add(bitarray b, int val)
{
	b.elts[b.elts.count()] = val;
	b.size = b.size + 1;
}

void add_nybbles(bitarray b, int val, boolean terminal)
{
	if (val < 8) {
		b.add(terminal ? val + 8 : val);
	} else {
		int digit = val & 7;
		add_nybbles(b, val >> 3, false);
		b.add(terminal ? digit+8 : digit);
	}
}

// This adds a new item count to the given bitarray.  These counts are coded by breaking
// them into octal digits (sets of 3 bits) and adding a nybble for each digit, where the
// high bit of the nybble is set if and only if the octal digit is the last.  For example,
// encoding 163, whose octal representation is 243, will add the nybbles 0010 0100 1011, 
// in that order, to the end of the bitarray's data.  This will later be decoded 
// sequentially by the Python HTML renderer.
void add_item_count(bitarray b, int val)
{
	if (val < 8) {
		b.add(8 + val);		// add terminal bit
	} else {
		b.add_nybbles(val, true);
	}
}


///////////////////////////////

record ItemImage
{
    string itemname;
    string gifname;
    string a;
    string b;
    string c;
    string d;
    string e;
    string f;
    string g;
    string h;
    string i;
};

ItemImage [int] BOOZE, CONCOCKTAIL, CONFOOD, CONMEAT, CONMISC, CONSMITH, 
	COOLITEMS, FAMILIARS, FOOD, HOBOCODES, MRITEMS, SKILLS,
    TATTOOS, TROPHIES; 

int[int] LEVELS = {};

void set_level_counter(int i, int value, int num_digits)
{
	if (LEVELS.count() == 0) {
		for j from 0 to NUM_LEVELS-1 {
			LEVELS[j] = 0;
		}
	}
	while (num_digits > 0) {
		num_digits = num_digits - 1;
		int d = value % 36;
		LEVELS[i+num_digits] = d;
		value = (value-d) / 36; 
	}
}

void set_level_counter(int i, int value)
{
	set_level_counter(i, value, 1);
}


string BASE36 = "0123456789abcdefghijklmnopqrstuvwxyz";
string levels_string() 
{
	string result = "";
	foreach x, val in LEVELS {
		result = result + BASE36.substring(val, val+1);
	}
	return result;
}


boolean load_current_map(string fname, ItemImage[int] map)
{
	file_to_map(fname+".txt", map);
	return true;
}

void load_data()
{
    print("Loading map files...", "olive");
	load_current_map("av-snapshot-skills", SKILLS);
	load_current_map("av-snapshot-tattoos", TATTOOS);
	load_current_map("av-snapshot-trophies", TROPHIES);
	load_current_map("av-snapshot-familiars", FAMILIARS);
	load_current_map("av-snapshot-mritems", MRITEMS);
	load_current_map("av-snapshot-coolitems", COOLITEMS);
	load_current_map("av-snapshot-disc-cocktail", CONCOCKTAIL);
	load_current_map("av-snapshot-disc-food", CONFOOD);
	load_current_map("av-snapshot-disc-meat", CONMEAT);
	load_current_map("av-snapshot-disc-misc", CONMISC);
	load_current_map("av-snapshot-disc-smith", CONSMITH);
	load_current_map("av-snapshot-booze", BOOZE);
	load_current_map("av-snapshot-food", FOOD);
	load_current_map("av-snapshot-hobocodes", HOBOCODES);
}

boolean is_in(string name, string html)
{
	if(length(name) > 7)
	{
		if(index_of(name, "_thumb") >= length(name) - 6)
		{
			name = substring(name, 0, length(name) - 6);
		}
	}

	matcher reg = create_matcher(name, html);
	return reg.find();
}

# NOTE: html must have already been converted to lower case
int has_consumed(string name, string html)
{
	name = to_lower_case(name);
	name = replace_string(name, "(", "\\(");
	name = replace_string(name, ")", "\\)");
	name = replace_string(name, "[", "\\[");
	name = replace_string(name, "]", "\\]");
	name = replace_string(name, "?", "\\?");
	matcher m = create_matcher(">\\s*" + name + "(?:\\s*)</a>", html);
	if (find(m)) {
		return 1;
	} else {
		return 0;
	}
}

int find_regex(string html, string checkthis)
{
	checkthis = replace_string(checkthis, "+", "\\+");
	checkthis = replace_string(checkthis, "(0)", "\\(([0-9]+)\\)");
	checkthis = replace_string(checkthis, "</b>", "(</a>){0,1}</b>");
	checkthis = replace_string(checkthis, "</b> <font", "</b>(\\s){0,1}<font");
	checkthis = replace_string(checkthis, "<font size=1>", "<font size=1>(?:<font size=2>\\[<a href=\"craft.php\\?mode=\\w+&a=\\d+&b=\\d+\">\\w+</a>\\]</font>)?");

	matcher reg = create_matcher(checkthis, html);
	if (reg.find()) {
		debug("YES --- " + checkthis);
		return 1;
	} else {
		debug("NO --- " + checkthis);
		return 0;
	}
}


boolean is_empty(string it)
{
	return ((it == "-") || (it == ""));
}


int is_discovered(string name, string html, string a)
{
	if (a.is_empty()) {
		if (index_of(html, ">"+name+"<") != -1) {
			return 1;
		} else {
			return 0;
		}
	}
	return find_regex(html, a);
}

int num_items(string name)
{
	item i = to_item(name);
	if(i == $item[none]) {
		return 0;
	}

	int amt = item_amount(i) + closet_amount(i) + equipped_amount(i) + storage_amount(i);
	amt += display_amount(i) + shop_amount(i);

	//Make a check for familiar equipment NOT equipped on the current familiar.
	foreach fam in $familiars[] {
		if(have_familiar(fam) && fam != my_familiar()) {
			if(i == familiar_equipped_equipment(fam)) {
				amt += 1;
			}
		}
	}

	//Thanks, Bale!
	if(get_campground() contains i) amt += 1;
	return amt;
}



###########################################################################

# Is the skill permed or hardcore permed?
int skillLevel(string name, string html, string overwrite)
{
	if(overwrite == "-") {
		overwrite = "";
	}
	if (index_of(html, ">"+name+"</a> (<b>HP</b>)") != -1) {
        return 2;
	}
	else if ((length(overwrite) > 0) && (index_of(html, overwrite) > 0)) {   
        #print(`overwrite for {name} is {overwrite}`);
		return 2;
	}
	else if (index_of(html, ">"+name+"</a> (P)") != -1) {
        return 1;
	}
	else if ((name == "Toggle Optimality") && have_skill(to_skill(name))) {
		return 2;	# Treat Optimality as HC Permed
	}
	else {
		return 0;
	}
}

string check_skills(string bookshelfHtml)
{
    bitarray b = new_bitarray(SKILLS.count()+1, 2);
	print("Checking skills...", "olive");
	string html = visit_url("charsheet.php") + bookshelfHtml;
    // Check normal skills
	foreach x in SKILLS {
        b.set(x, skillLevel(SKILLS[x].itemname, html, SKILLS[x].a));
	}

    return "&skills=" + b.base64_encode();
}

###########################################################################

int tattoo_check(string html, string outfit, string gif, string i1, string i2, string i3, 
				string i4, string i5, string i6, string i7, string i8, string i9)
{
	if(last_index_of(html, "/"+gif+".gif") > 0) {
		# If user has the tattoo, we're done
		return 1;
	} 
	# Let's see if the user has the pieces needed to make the outfit for the tattoo
	if (is_empty(i1))	// Return if outfit doesn't exist
		return 0;
	if (num_items(i1) == 0)	// Stop if the player doesn't even have item 1
		return 0;
	if (is_empty(i2))  return 2;	// If we have all previous items, we succeeded
	if (num_items(i2) == 0)  return 0;  // If we lack an item, we failed
	if (is_empty(i3))  return 2;	
	if (num_items(i3) == 0)  return 0;  
	if (is_empty(i4))  return 2;	
	if (num_items(i4) == 0)  return 0;  
	if (is_empty(i5))  return 2;	
	if (num_items(i5) == 0)  return 0;  
	if (is_empty(i6))  return 2;	
	if (num_items(i6) == 0)  return 0;  
	if (is_empty(i7))  return 2;	
	if (num_items(i7) == 0)  return 0;  
	if (is_empty(i8))  return 2;	
	if (num_items(i8) == 0)  return 0;  
	if (is_empty(i9))  return 2;	
	if (num_items(i9) == 0)  return 0;  

	return 2;
}

string check_tattoos()
{
	debug('Tattoos count ' + TATTOOS.count());
	int i = 1;
	while (i < 281) {
		if (! (TATTOOS contains i))
			print(`Aha!  {i}`, 'red');
		i = i+1;
	}
	bitarray b = new_bitarray(TATTOOS.count()+1, 2);
	print("Checking tattoos...", "olive");
	string html = visit_url("account_tattoos.php");
	foreach x in TATTOOS
	{
		ItemImage ii = TATTOOS[x];
		b.set(x, tattoo_check(html, ii.itemname, ii.gifname, ii.a, ii.b, ii.c, ii.d, ii.e, 
							ii.f, ii.g, ii.h, ii.i));
	}

	// What's the level on the Hobo Tattoo?
	for lv from 19 to 1 {
		if (index_of(html, "hobotat"+lv) != -1) {
			set_level_counter(11, lv);
			break;
		}
	}

    return "&tattoos=" + b.base64_encode();
}

###########################################################################

string check_trophies()
{
    bitarray b = new_bitarray(TROPHIES.count()+1, 1);
    print("Checking trophies...", "olive");
	buffer html = visit_url("trophies.php");
	foreach x in TROPHIES
	{
		if (is_in("/" + TROPHIES[x].itemname, html))
            b.set(x, 1);
	}
    return "&trophies=" + b.base64_encode();
}

###########################################################################

int familiar_check(string name, string gifname, string hatchling, 
	string familiarNamesHtml, string koldbHtml)
{
	#print("Looking for familiar: " + name);
	int famCode = 0;

	debug("Looking for familiar: " + name);
	// Pre Quantum:
	// 0: No familiar, in any capacity (retained)
	// 1: Have familiar
	// 2: Have hatchling, but not familiar
	// 3: Have familiar, 100% run
	// 4: Have familiar, 90% run
	// ---- Post-Quantum
	// 3: 100% run, have familiar
	// 4: 90% run, have familiar
	// 5: 100% run, no familiar
	// 6: 100% run, hatching, no familiar.
	// 7: 90% run, no familiar
	// 8: 90% run, hatchling, no familiar.

	boolean haveHatchling = false;
	if ((! hatchling.is_empty()) && num_items(hatchling) > 0) {
		haveHatchling = true;
	}

	boolean haveFamiliar = false;
	if(have_familiar(to_familiar(name))) {
		haveFamiliar = true;
	} else if(index_of(familiarNamesHtml, "the " + name + "</td>") > 0) {
		haveFamiliar = true;
	}

	matcher m = create_matcher("alt=\"" + name + " .([0-9.]+)..", koldbHtml);
	float percent = 0.0;
	while(find(m)) {
		string percentMatch = group(m, 1);
		percent = max(percent, to_float(percentMatch));
	}

	debug("Found max percentage: " + percent);
	if(percent >= 100.0) {
		if(haveFamiliar) {
			return 3;
		} else if(haveHatchling) {
			return 6;
		} else {
			return 5;
		}
	} else if(percent >= 90.0) {
		if(haveFamiliar) {
			return 4;
		} else if(haveHatchling) {
			return 8;
		} else {
			return 7;
		}
	} else if(haveFamiliar) {
		return 1;
	} else if(haveHatchling) {
		return 2;
	}

	return famCode;
}

string check_familiars(string familiarNamesHtml) 
{
	print("Checking familiars...", "olive");
	bitarray b = new_bitarray(FAMILIARS.count()+1, 4);
	string koldbHtml = visit_url("ascensionhistory.php?back=self&who=" +my_id(), false) 
				+ visit_url("ascensionhistory.php?back=self&prens13=1&who=" +my_id(), false);
	foreach x in FAMILIARS {
		b.set(x, familiar_check(FAMILIARS[x].itemname, FAMILIARS[x].gifname, 
		                 FAMILIARS[x].a, familiarNamesHtml, koldbHtml));
	}
	return "&familiars=" + b.base64_encode();
}


###########################################################################

string get(ItemImage mritem, int offset)
{
	switch(offset)
	{
	case 0:	return mritem.a;
	case 1:	return mritem.b;
	case 2:	return mritem.c;
	case 3:	return mritem.d;
	case 4:	return mritem.e;
	case 5:	return mritem.f;
	case 6:	return mritem.g;
	case 7:	return mritem.h;
	case 8:	return mritem.i;
	}
	// This is an error situation, but I guess we will just try to be graceful about it
	return "None";
}

string check_mritems(string bookshelfHtml) 
{
    bitarray b = new_bitarray(0, 4);
	print("Checking for Mr. Items...", "olive");

    // Visit the woods to make sure getawayCampsiteUnlocked is set properly
    buffer buf = visit_url("woods.php");
    
	foreach x in MRITEMS {
		ItemImage mrit = MRITEMS[x];
		string categoryFlags = mrit.itemname;
		item baseItem = to_item(mrit.gifname);
		int amt = num_items(baseItem);

		foreach index, category in split_string(categoryFlags, "")	{
			string data = get(mrit, index);
			switch(category)
			{
	            case "e":  // This only exists because florist_available() exists instead of a setting (124)
					// This does not check if you have one installed if you have any of the tradable item.
					// Do not use this with other flags, this is a edge scenario
					if ((amt == 0) && 
					     (contains_text(visit_url(data), get(mrit, index + 1)))) {
						amt += 1;
					}
					break;

				case "f":	//Familiars, any of, comma separated (no whitespace)
					foreach index, it in split_string(data, ",") {
						if(have_familiar(to_familiar(it))) {
							amt += 1;
						}
					}
					break;

				case "i":	//Items, any of, comma separated (no whitespace)
					foreach index, it in split_string(data, ",") {
						amt += num_items(it);
					}
					break;

				case "p":	//Correspondences (Pen Pal, Game Magazine, etc)
					if(contains_text(visit_url("account.php?tab=correspondence"), ">" + data +"</option>"))	{
						amt += 1;
					}
					break;

				case "s":	//Check mafia setting
					if(get_property(data).to_boolean())	{
						amt += 1;
					}
					break;

				//Gardens would ideally by a campground check (just num_items)
				//but the data in mritems would need to include the harvestable since that is what mafia reports instead of the garden itself.
				case "t":				//Tome, Libram, Grimore, Garden
					if(index_of(bookshelfHtml, data) > 0) {
						amt += 1;
					}
					break;
			}
		}
		b.add_item_count(amt);
		// TODO do something with amt;  isn't this just a table of booleans?
	}
	return "&mritems=" + b.base64_encode();
}


###########################################################################

string check_coolitems()
{
    bitarray b = new_bitarray(0, 4);
	print("Checking for Cool Items...", "olive");
	foreach x in COOLITEMS {
		b.add_item_count(num_items(COOLITEMS[x].itemname));
	}
	return "&coolitems=" + b.base64_encode();
}


###########################################################################

string check_discoveries_class(string what, ItemImage[int] map, string param)
{
	string url = `craft.php?mode=discoveries&what={what}`;
	matcher reg = create_matcher("<font size=2>.*?</font>", visit_url(url));
	string html = replace_all(reg, "");
	bitarray b = new_bitarray(map.count()+1, 1);
	foreach i, rec in map {
		b.set(i, is_discovered(rec.itemname, html, rec.gifname));
	}
	return `&{param}={b.base64_encode()}`;
}

string check_discoveries()
{
	print(`Checking for discoveries...`, "olive");
	return check_discoveries_class('cocktail', CONCOCKTAIL, "concocktail")
		+ check_discoveries_class('cook', CONFOOD, "confood")
		+ check_discoveries_class('combine', CONMEAT, "conmeat")
		+ check_discoveries_class('smith', CONSMITH, "consmith")
		+ check_discoveries_class('multi', CONMISC, "conmisc");
}


###########################################################################

string check_consumption()
{
    bitarray b = new_bitarray(BOOZE.count()+1, 1);
	bitarray f = new_bitarray(FOOD.count()+1, 1);
	print("Checking consumption...", "olive");
	string html = to_lower_case(visit_url("showconsumption.php"));
	foreach i, rec in BOOZE {
		b.set(i, has_consumed(rec.itemname, html));
	}
	foreach i, rec in FOOD {
		f.set(i, has_consumed(rec.itemname, html));
	}
	return "&booze=" + b.base64_encode() + "&food=" + f.base64_encode();
}


###########################################################################

string check_levels()
{
	print("Checking miscellaneous levels...", "olive");
	// return skills and levels ([0] sinew, [1] synapse, [2] shoulder, [3] belch, 
	//		[4] bellow, [5] fun, [6] carrot, [7] bear, [8] numberology, [9] safari, 
	//		[10] implode, [11] hobotat,	[12:16] karma, 
	//		manuel ([16:19] casual, [19:22] thourough, [22:25] exhaustive),
	//		[25] telescope, [26:28] chessboard, [28:32] hobocodes, [32] optimality)
	// hobotat's already been done by this point
	string[int] levelmap = {
		0:"46", 1:"47", 2:"48", 3:"117", 4:"118", 5:"121", 6:"128", 7:"134", 
		8:"144", 9:"180", 10:"188", 32:"7254"
	};
	foreach i, sknum in levelmap {
		set_level_counter(i, get_property("skillLevel" + sknum).to_int());
	}
	// Karma
	string karma = visit_url("questlog.php?which=3");
	matcher m = create_matcher("Your current Karmic balance is ([0-9,]+)", karma);
	int k = 0;
	if (find(m)) {
		k = group(m, 1).to_int();
	}
	debug("You have "+k+" karma");
	set_level_counter(12, k, 4);
	// Manuel
	string manuelHTML = visit_url("questlog.php?which=6&vl=a");
	if(contains_text(manuelHTML, "Monster Manuel")) {
		matcher m = create_matcher("casually(?:.*?)([0-9]+) creature(s?)[.]", manuelHTML);
		if (find(m)) {
			set_level_counter(16, group(m,1).to_int(), 3);
		}
		m = create_matcher("thoroughly(?:.*?)([0-9]+) creature(s?)[.]", manuelHTML);
		if (find(m)) {
			set_level_counter(19, group(m,1).to_int(), 3);
		}
		m = create_matcher("exhaustively(?:.*?)([0-9]+) creature(s?)[.]", manuelHTML);
		if (find(m)) {
			set_level_counter(22, group(m,1).to_int(), 3);
		}
	}
	// Telescope
	set_level_counter(25, get_property("telescopeUpgrades").to_int());
	// Looking Glass chessboards
	set_level_counter(26, get_property("chessboardsCleared").to_int(), 2);
	// Hobo codes
	string html = visit_url("questlog.php?which=5");
	int codes = 0;
	foreach x in HOBOCODES
	{
		codes = codes * 2;
		if (is_in(HOBOCODES[x].itemname, html)) {
			codes = codes + 1;
		}
	}
	set_level_counter(28, codes, 4);
	return "&levels=" + levels_string();
}


###########################################################################

string check_demons()
{
	string result = get_property("demonName1");
	int i = 2;
	while (i <= 12) {	# change this number when number of demons changes
		result = result + "|" + get_property("demonName"+i);
		i = i + 1;
	}
	return "&demonnames=" + result;
}


###########################################################################

void main()
{
	if(!get_property("kingLiberated").to_boolean())
	{
		if(!user_confirm("This script should not be run while you are in-run. It may blank out "
                        + "some of your skills, telescope, bookshelf or some other aspect of your "
                        + "profile until you next run it in aftercore. Are you sure you want to "
                        + "run it (not recommended)?", 15000, false)) {
			abort("User aborted. Beep");
		}
	}

    load_data();
    string bookshelfHtml = visit_url("campground.php?action=bookshelf");
	string familiarNamesHtml = visit_url("familiarnames.php");

    string yourName = my_name();
    string yourUrl;
	if (get_property("avSnapshotLocal") == "j") {
    	yourUrl = `http://localhost/cgi-bin/av-snapshot.py?u={yourName}`;
	} else {
		yourUrl = `https://api.aventuristo.net/av-snapshot?u={yourName}`;
	}
    string yourEncodedUrl = replace_string(yourUrl, " ", "+");
	string url = yourUrl + `&update=j&mafiarevision={get_revision()}&snapshotversion={VERSION}`;
    url = url + check_skills(bookshelfHtml);
	url = url + check_tattoos();
    url = url + check_trophies();
	url = url + check_familiars(familiarNamesHtml);
	url = url + check_mritems(bookshelfHtml);
	url = url + check_coolitems();
	url = url + check_discoveries();
	url = url + check_consumption();
	url = url + check_levels();
	url = url + check_demons();

	if (get_property("avSnapshotNosave") == "j") {
    	print(url);
		print(`URL length = {url.length()}`);
	} else {
		print("Contacting database...");
		buffer b = visit_url(url, true);
		if (b.index_of("Record added") >= 0) {
			print("Database updated", "green");
			print_html(`You can visit your profile at <a href="{yourEncodedUrl}" target="_blank">{yourEncodedUrl}</a>`);
		} else {
			print("Some error occurred", "red");
			print(`URL: {url}`, "red");
			print(`Reponse: {b}`, "red");
		}
		print("");
	}
}
