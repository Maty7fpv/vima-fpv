#!/usr/bin/env python3
# Vima: prida do IQ souboru SC3336 LSC (stinovani objektivu) pro rozliseni 1152x648.
# Binning 2x2 snima stejnou plochu cipu jako 2304x1296 -> stejne koeficienty 17x17,
# jen polovicni velikosti sektoru (x 16*72 = 1152, y 8*40 + 8*41 = 648, stridani jako
# vendor u 1080 radku: 67/68). Soubor se meni jen textove (CRLF, taby zustanou).
import json, sys
src, dst = sys.argv[1], sys.argv[2]
t = open(src, "rb").read().decode("utf-8")
NL = "\r\n" if "\r\n" in t else "\n"

def once(old, new):
    global t
    assert t.count(old) == 1, (old[:60], t.count(old))
    t = t.replace(old, new)

# 1) resolutionAll: nova polozka 1152x648
ind = "\t" * 9
old_y = '"lsc_sect_size_y":\t[81, 81, 81, 81, 81, 81, 81, 81, 81, 81, 81, 81, 81, 81, 81, 81]' + NL + ind + "}],"
xs = ", ".join(["72"] * 16)
ys = ", ".join(["40", "41"] * 8)
new_y = ('"lsc_sect_size_y":\t[81, 81, 81, 81, 81, 81, 81, 81, 81, 81, 81, 81, 81, 81, 81, 81]' + NL + ind + "}, {" + NL
         + ind + '\t"name":\t"1152x648",' + NL
         + ind + '\t"lsc_sect_size_x":\t[' + xs + "]," + NL
         + ind + '\t"lsc_sect_size_y":\t[' + ys + "]" + NL + ind + "}],")
once(old_y, new_y)
once('"resolutionAll_len":\t1' + NL, '"resolutionAll_len":\t2' + NL)

# 2) tableAll: kopie 14 tabulek s nazvem/rozlisenim 1152x648
a = t.index('"tableAll":\t[') + len('"tableAll":\t[')
b = t.index('"tableAll_len":\t', a)
end = t.rindex("]", a, b)          # konec pole tableAll
body = t[a:end]
assert body.count("2304x1296") == 28, body.count("2304x1296")   # 14x name + 14x resolution
n = int(t[b + len('"tableAll_len":\t'):].split(NL, 1)[0])
t = t[:a] + body + ", " + body.replace("2304x1296", "1152x648") + t[end:]
once('"tableAll_len":\t%d' % n + NL, '"tableAll_len":\t%d' % (2 * n) + NL)
open(dst, "wb").write(t.encode("utf-8"))

# kontrola: platny JSON, jinak beze zmeny
o, m = json.load(open(src)), json.load(open(dst))
lo = o["main_scene"][0]["sub_scene"][0]["scene_isp32"]["lsc_v2"]
lm = m["main_scene"][0]["sub_scene"][0]["scene_isp32"]["lsc_v2"]
r = lm["common"]["resolutionAll"][1]
assert sum(r["lsc_sect_size_x"]) == 1152 and sum(r["lsc_sect_size_y"]) == 648
assert lm["tbl"]["tableAll"][:n] == lo["tbl"]["tableAll"]
for x, y in zip(lo["tbl"]["tableAll"], lm["tbl"]["tableAll"][n:]):
    assert y["name"] == x["name"].replace("2304x1296", "1152x648") and y["resolution"] == "1152x648"
    assert all(y[k] == x[k] for k in x if k not in ("name", "resolution"))
lm2 = json.loads(json.dumps(lm)); lm2["common"]["resolutionAll"] = lm2["common"]["resolutionAll"][:1]
lm2["common"]["resolutionAll_len"] = 1; lm2["tbl"]["tableAll"] = lm2["tbl"]["tableAll"][:n]; lm2["tbl"]["tableAll_len"] = n
m["main_scene"][0]["sub_scene"][0]["scene_isp32"]["lsc_v2"] = lm2
assert m == o, "zmena mimo LSC!"
print("OK:", dst, "resolutionAll", [x["name"] for x in lm["common"]["resolutionAll"]], "tabulek", len(lm["tbl"]["tableAll"]))
