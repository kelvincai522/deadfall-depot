import urllib.request, urllib.parse, xml.etree.ElementTree as ET, json, sys, time
B="https://omniverse-content-production.s3.us-west-2.amazonaws.com"
NS="{http://s3.amazonaws.com/doc/2006-03-01/}"
def page(prefix, token=None, delim="/"):
    q={"list-type":"2","prefix":prefix,"max-keys":"1000"}
    if delim: q["delimiter"]=delim
    if token: q["continuation-token"]=token
    url=B+"/?"+urllib.parse.urlencode(q)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=60) as r: return ET.fromstring(r.read())
        except Exception as e:
            if attempt==3: raise
            time.sleep(2)
def listing(prefix, delim="/"):
    dirs=[]; files=[]; tok=None
    while True:
        root=page(prefix,tok,delim)
        for c in root.findall(NS+"CommonPrefixes"):
            dirs.append(c.find(NS+"Prefix").text)
        for c in root.findall(NS+"Contents"):
            files.append((c.find(NS+"Key").text, int(c.find(NS+"Size").text)))
        t=root.find(NS+"IsTruncated")
        if t is not None and t.text=="true":
            tok=root.find(NS+"NextContinuationToken").text
        else: break
    return dirs, files
def walk(prefix, depth, maxdepth, out):
    dirs, files = listing(prefix)
    out["dirs"].setdefault(prefix, {"subdirs":dirs, "files":[f for f,_ in files if f.lower().endswith(('.usd','.usda','.usdc','.usdz','.mdl','.hdr','.exr','.png','.jpg'))][:400]})
    if depth<maxdepth:
        for d in dirs:
            walk(d, depth+1, maxdepth, out)
out={"dirs":{}}
targets=[("Assets/Vegetation/",3),("Assets/ArchVis/",3),("Assets/Skies/",2),
         ("Assets/simready_content/",3),("Assets/Terrain/",2),("Assets/Particles/",2),
         ("Materials/vMaterials_2/",2),("Assets/Scenes/",2),("Environments/",2),
         ("Assets/DigitalTwin/",3),("Assets/Characters/",2)]
for t,d in targets:
    print("crawling",t,file=sys.stderr)
    try: walk(t,0,d,out)
    except Exception as e: print("FAIL",t,e,file=sys.stderr)
json.dump(out, open(r"c:/Users/kelvi/Documents/ov/level/_catalog/library.json","w"), indent=0)
n=sum(len(v["files"]) for v in out["dirs"].values())
print(f"dirs={len(out['dirs'])} files={n}", file=sys.stderr)
