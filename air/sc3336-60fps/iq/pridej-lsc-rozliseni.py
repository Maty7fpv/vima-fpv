#!/usr/bin/env python3
# Vima: prida do IQ SC3336 LSC pro dalsi rozliseni se STEJNYM zaberem jako 2304x1296 (binning/skip):
# kopie 14 tabulek 2304x1296_* s novym nazvem; sektory: 16 stejnych (nebo stridani n/n+1).
# pouziti: pridej-lsc-rozliseni.py vstup.json vystup.json 2304x648
import json, sys
src, dst, res = sys.argv[1], sys.argv[2], sys.argv[3]
w, h = map(int, res.split("x"))
t = open(src, "rb").read().decode("utf-8")
NL = "\r\n" if "\r\n" in t else "\n"
def sect(n):
    a = n // 16
    if n % 16 == 0: return [a] * 16
    assert n % 16 == 8, n
    return [a, a + 1] * 8
assert f'"{res}"' not in t, "rozliseni uz v souboru je"
a = t.index('"resolutionAll":\t[') + len('"resolutionAll":\t[')
b = t.index('"resolutionAll_len":\t', a)
end = t.rindex("]", a, b)
first = t[a:t.index("}", a) + 1]          # prvni polozka (2304x1296) jako vzor formatu
assert '"2304x1296"' in first
ind = first[first.rindex(NL) + len(NL):first.rindex("}")]
new = first.replace('"2304x1296"', f'"{res}"')
new = new[:new.index('"lsc_sect_size_x":')] + '"lsc_sect_size_x":\t[' + ", ".join(map(str, sect(w))) + "]," + NL + ind + "\t" + '"lsc_sect_size_y":\t[' + ", ".join(map(str, sect(h))) + "]" + NL + ind + "}"
n_res = int(t[b + len('"resolutionAll_len":\t'):].split(NL, 1)[0])
t = t[:end] + ", " + new + t[end:]
t = t.replace('"resolutionAll_len":\t%d' % n_res + NL, '"resolutionAll_len":\t%d' % (n_res + 1) + NL, 1)
a = t.index('"tableAll":\t[') + len('"tableAll":\t[')
b = t.index('"tableAll_len":\t', a)
end = t.rindex("]", a, b)
body = t[a:end]
o = json.loads(open(src).read())
src_tabs = [x for x in o["main_scene"][0]["sub_scene"][0]["scene_isp32"]["lsc_v2"]["tbl"]["tableAll"] if x["resolution"] == "2304x1296"]
# vyber textove bloky tabulek 2304x1296 (objekty oddelene "}, {")
# tabulky 2304x1296 jsou prvnich 14 v poli; "}, {" se vyskytuje jen mezi tabulkami
assert len(src_tabs) == 14 and body.lstrip().startswith("{")
idx, pos = -1, 0
for _ in range(14):
    idx = body.index("}, {", pos); pos = idx + 1
blk = body[:idx + 1]           # vcetne uzaviraci } 14. tabulky
assert blk.count('"resolution":\t"2304x1296"') == 14 and "1152x648" not in blk
n_tab = int(t[b + len('"tableAll_len":\t'):].split(NL, 1)[0])
t = t[:end] + ", " + blk.replace("2304x1296", res) + t[end:]
t = t.replace('"tableAll_len":\t%d' % n_tab + NL, '"tableAll_len":\t%d' % (n_tab + 14) + NL, 1)
open(dst, "wb").write(t.encode("utf-8"))
m = json.load(open(dst))
l = m["main_scene"][0]["sub_scene"][0]["scene_isp32"]["lsc_v2"]
r = [x for x in l["common"]["resolutionAll"] if x["name"] == res][0]
assert sum(r["lsc_sect_size_x"]) == w and sum(r["lsc_sect_size_y"]) == h
nt = [x for x in l["tbl"]["tableAll"] if x["resolution"] == res]
assert len(nt) == 14 and all(x["lsc_samples_red"] == y["lsc_samples_red"] for x, y in zip(nt, src_tabs))
assert l["common"]["resolutionAll_len"] == len(l["common"]["resolutionAll"]) and l["tbl"]["tableAll_len"] == len(l["tbl"]["tableAll"])
o2 = json.loads(json.dumps(m)); lo = o2["main_scene"][0]["sub_scene"][0]["scene_isp32"]["lsc_v2"]
lo["common"]["resolutionAll"] = [x for x in lo["common"]["resolutionAll"] if x["name"] != res]; lo["common"]["resolutionAll_len"] = len(lo["common"]["resolutionAll"])
lo["tbl"]["tableAll"] = [x for x in lo["tbl"]["tableAll"] if x["resolution"] != res]; lo["tbl"]["tableAll_len"] = len(lo["tbl"]["tableAll"])
assert o2 == o, "zmena mimo LSC!"
print("OK", dst, [x["name"] for x in l["common"]["resolutionAll"]], len(l["tbl"]["tableAll"]), "tabulek")
