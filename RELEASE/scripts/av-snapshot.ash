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

ItemImage [int] ascrewards, booze, concocktail, confood, conmeat, conmisc, consmith, 
    coolitems, familiars, food, hobopolis, rogueprogram, manuel, mritems, skills, 
    slimetube, tattoos, trophies, warmedals, tracked;

boolean load_current_map(string fname, ItemImage[int] map)
{
	file_to_map(fname+".txt", map);
	return true;
}

void load_data()
{
    print("Updating map files...", "olive");
	load_current_map("cc_snapshot_skills", skills);
	load_current_map("cc_snapshot_tattoos", tattoos);
	load_current_map("cc_snapshot_trophies", trophies);
	load_current_map("cc_snapshot_familiars", familiars);
	load_current_map("cc_snapshot_mritems", mritems);
	load_current_map("cc_snapshot_coolitems", coolitems);
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

int i_a(string name)
{
	item i = to_item(name);
	if(i == $item[none])
	{
		return 0;
	}

	int amt = item_amount(i) + closet_amount(i) + equipped_amount(i) + storage_amount(i);
	amt += display_amount(i) + shop_amount(i);

	//Make a check for familiar equipment NOT equipped on the current familiar.
	foreach fam in $familiars[]
	{
		if(have_familiar(fam) && fam != my_familiar())
		{
			if(i == familiar_equipped_equipment(fam))
			{
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
		int itemAmount = i_a(baseItem);

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
						itemAmount += i_a(it);
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

				//Gardens would ideally by a campground check (just i_a)
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
    bitarray b = new_bitarray(440, 2);
	print("Checking skills...", "olive");
	string html = visit_url("charsheet.php") + bookshelfHtml;
    // Check normal skills
	foreach x in skills {
        b.set(x, skillLevel(skills[x].itemname, html, skills[x].a));
	}

    // return skills and levels (sinew, synapse, shoulder, belch, bellow, fun,
	//							 carrot, bear, numberology, safari, implode)
	string levels = "";
	foreach sk in $strings[46, 47, 48, 117, 118, 121, 
	                       128, 134, 144, 180, 188] {
		string l = get_property("skillLevel" + sk);
		if (l == "10") {
			l = "A";
		} else if (l == "11") {
			l = "B";
		}
		levels = levels + l;
	}
    return "&skills=" + b.base64_encode() 
        + "&levels=" + levels;
}

string check_trophies()
{
    bitarray b = new_bitarray(200, 1);
    print("Checking trophies...", "olive");
	buffer html = visit_url("trophies.php");
	foreach x in trophies
	{
		if (isIn("/" + trophies[x].itemname, html))
            b.set(x, 1);
	}
    return "&trophies=" + b.base64_encode();
}

void main()
{
	if(!get_property("kingLiberated").to_boolean())
	{
		if(!user_confirm("This script should not be run while you are in-run. It may blank out "
                        + "some of your skills, telescope, bookshelf or some other aspect of your "
                        + "profile until you next run it in aftercore. Are you sure you want to "
                        + "run it (not recommended)?", 15000, false))
		{
			abort("User aborted. Beep");
		}
	}

    load_data();
    string bookshelfHtml = visit_url("campground.php?action=bookshelf");
	string familiarNamesHtml = visit_url("familiarnames.php");

    #string yourUrl = `http://localhost/cgi-bin/av-snapshot.py?name={my_name()}`;
	string yourUrl = `https://g1wjmf0i0h.execute-api.us-east-2.amazonaws.com/default/av-snapshot?name={my_name()}`;
    string url = yourUrl + "&update=j";
    url = url + check_skills(bookshelfHtml);
    url = url + check_trophies();
	buffer b = visit_url(url, false);
    #print(url);
	if (b.index_of("Record added") >= 0) {
		print("Database updated", "green");
		print(`You can visit your profile at {yourUrl}`);
	} else {
		print("Some error occurred", "red");
	}
}
