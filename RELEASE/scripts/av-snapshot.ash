script "av-snapshot.ash";
notify aventuristo;
since r20632;

#	This is a fork of cheesecookie's snapshot script, which is itself
#   a fork of bumcheekcity's snapshot script.
#	Like choosecookie's script, code comes straight from the predecessor,
#	website layout is copied from it, and things are then hacked onto it 
#   in order to increase support. So... yeah.

////////////////////////////

record bitarray {
    int size;
    int eltsize;
    int[int] elts;
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
    for i from 0 to (size-1) {
        b.elts[i] = 0;
    }
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

///////////////////////////////

boolean DEBUG = (get_property('avSnapshotDebug') == 'j');
void debug(string s)
	{
		if (DEBUG) { print(s, "blue"); }
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

ItemImage [int] ASCREWARDS, BOOZE, CONCOCKTAIL, CONFOOD, CONMEAT, CONMISC, CONSMITH, 
	COOLITEMS, FAMILIARS, FOOD, HOBOPOLIS, MANUEL, MRITEMS, ROGUEPROGRAM, SKILLS,
    SLIMETUBE, TATTOOS, TROPHIES, WARMEDALS, TRACKED; 
int[int] LEVELS = {};

void set_level_counter(int i, int value)
{
	if (LEVELS.count() == 0) {
		for j from 0 to 20 {
			LEVELS[j] = 0;
		}
	}
	LEVELS[i] = value;
}

string BASE36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";
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
    print("Updating map files...", "olive");
	load_current_map("cc_snapshot_skills", SKILLS);
	load_current_map("cc_snapshot_tattoos", TATTOOS);
	load_current_map("cc_snapshot_trophies", TROPHIES);
	load_current_map("cc_snapshot_familiars", FAMILIARS);
	load_current_map("cc_snapshot_mritems", MRITEMS);
	load_current_map("cc_snapshot_coolitems", COOLITEMS);
}

boolean isIn(string name, string html)
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

// There has to be a better way to do this since the keys are incrementing, yes?
string extract_data_from_mritem(ItemImage mritem, int offset)
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

void set_elemental_always(string prop, string name)
{
	set_property(prop, user_confirm("Mafia does not think you have " + name 
		+ " but it appears that you might. Select Yes to confirm that you have it."
		+ " Select No to indicate that you do not have it.", 15000, false));
}

string check_mritems(string bookshelfHtml, string familiarNamesHtml) 
{
	string html;

    bitarray b = new_bitarray(300, 1);
	print("Checking for Mr. Items", "olive");

	if(!get_property("spookyAirportAlways").to_boolean() 
		|| !get_property("sleazeAirportAlways").to_boolean() 
		|| !get_property("stenchAirportAlways").to_boolean() 
		|| !get_property("coldAirportAlways").to_boolean() 
		|| !get_property("hotAirportAlways").to_boolean())
	{
		html = visit_url("place.php?whichplace=airport");
		if(!get_property("spookyAirportAlways").to_boolean() && contains_text(html, "airport_spooky"))
		{
			set_elemental_always("spookyAirportAlways", "Conspiracy Island" );
		}
		if(!get_property("sleazeAirportAlways").to_boolean() && contains_text(html, "airport_sleaze"))
		{
			set_elemental_always("sleazeAirportAlways", "Spring Break Beach");
		}
		if(!get_property("stenchAirportAlways").to_boolean() && contains_text(html, "airport_stench"))
		{
			set_elemental_always("stenchAirportAlways", "Disneylandfill");
		}
		if(!get_property("hotAirportAlways").to_boolean() && contains_text(html, "airport_hot"))
		{
			set_elemental_always("hotAirportAlways", "That 70s Volcano");
		}
		if(!get_property("coldAirportAlways").to_boolean() && contains_text(html, "airport_cold"))
		{
			set_elemental_always("coldAirportAlways", "The Glaciest");
		}
	}

	html = familiarNamesHtml + bookshelfHtml;
	foreach x in mritems {
		string categoryFlags = mritems[x].itemname;
		item baseItem = to_item(mritems[x].gifname);
		int itemAmount = num_items(baseItem);

		foreach index, category in split_string(categoryFlags, "")	{
			string data = extract_data_from_mritem(mritems[x], index);
			switch(category)
			{
	            case "e":               // This only exists because florist_available() exists instead of a setting (124)
					// This does not check if you have one installed if you have any of the tradable item.
					// Do not use this with other flags, this is a edge scenario
					if((itemAmount == 0) && 
					   (contains_text(visit_url(data), extract_data_from_mritem(mritems[x], index + 1)))) {
						itemAmount += 1;
					}
					break;

				case "f":				//Familiars, any of, comma separated (no whitespace)
					foreach index, it in split_string(data, ",") {
						if(have_familiar(to_familiar(it))) {
							itemAmount += 1;
						}
					}
					break;

				case "i":				//Items, any of, comma separated (no whitespace)
					foreach index, it in split_string(data, ",") {
						itemAmount += num_items(it);
					}
					break;

				case "p":				//Correspondences (Pen Pal, Game Magazine, etc)
					if(contains_text(visit_url("account.php?tab=correspondence"), ">" + data +"</option>"))	{
						itemAmount += 1;
					}
					break;

				case "s":				//Check mafia setting
					if(get_property(data).to_boolean())	{
						itemAmount += 1;
					}
					break;

				//Gardens would ideally by a campground check (just num_items)
				//but the data in mritems would need to include the harvestable since that is what mafia reports instead of the garden itself.
				case "t":				//Tome, Libram, Grimore, Garden
					if(index_of(html, data) > 0) {
						itemAmount += 1;
					}
					break;
			}
		}
		// TODO do something with itemAmount;  isn't this just a table of booleans?
	}
	return "&mritems=" + b.base64_encode();
}

# Is the skill permed or hardcore permed?
int skillLevel(string name, string html, string overwrite)
{
	if(overwrite == "-") {
		overwrite = "";
	}
	if(index_of(html, ">"+name+"</a> (<b>HP</b>)") != -1) {
        return 2;
	}
	else if((length(overwrite) > 0) && (index_of(html, overwrite) > 0)) {   
        #print(`overwrite for {name} is {overwrite}`);
		return 2;
	}
	else if(index_of(html, ">"+name+"</a> (P)") != -1) {
        return 1;
	}
	else if((name == "Toggle Optimality") && have_skill(to_skill(name))) {
		return 1;
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

string check_trophies()
{
    bitarray b = new_bitarray(TROPHIES.count()+1, 1);
    print("Checking trophies...", "olive");
	buffer html = visit_url("trophies.php");
	foreach x in TROPHIES
	{
		if (isIn("/" + TROPHIES[x].itemname, html))
            b.set(x, 1);
	}
    return "&trophies=" + b.base64_encode();
}

int famCheck(string name, string gifname, string hatchling, 
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
	if (num_items(hatchling) > 0) {
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
		b.set(x, famCheck(FAMILIARS[x].itemname, FAMILIARS[x].gifname, 
		                 FAMILIARS[x].a, familiarNamesHtml, koldbHtml));
	}
	return "&familiars=" + b.base64_encode();
}

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

	string yourUrl;
	if (get_property("avSnapshotLocal") == "j") {
    	yourUrl = `http://localhost/cgi-bin/av-snapshot.py?u={my_name()}`;
	} else {
		yourUrl = `https://g1wjmf0i0h.execute-api.us-east-2.amazonaws.com/default/av-snapshot?u={my_name()}`;
	}
	string url = yourUrl + "&update=j";
    url = url + check_skills(bookshelfHtml);
    url = url + check_trophies();
	url = url + check_familiars(familiarNamesHtml);
	// return skills and levels (sinew, synapse, shoulder, belch, bellow, fun,
	//							 carrot, bear, numberology, safari, implode)
	string[int] levelmap = {
		0:"46", 1:"47", 2:"48", 3:"117", 4:"118", 5:"121", 6:"128", 7:"134", 
		8:"144", 9:"180", 10:"188"
	};
	foreach i, sknum in levelmap {
		set_level_counter(i, get_property("skillLevel" + sknum).to_int());
	}
	url = url + "&levels=" + levels_string();
	if (get_property("avSnapshotNosave") == "j") {
    	print(url);
	} else {
		buffer b = visit_url(url, false);
		if (b.index_of("Record added") >= 0) {
			print("Database updated", "green");
			print(`You can visit your profile at {yourUrl}`);
		} else {
			print("Some error occurred", "red");
		}
	}
}