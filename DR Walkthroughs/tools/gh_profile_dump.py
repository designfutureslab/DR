"""
Paste this into a Grasshopper *Python 3 Script* component on the canvas you want to profile.
Give it one input called `run` (a Button or Boolean Toggle) and one output called `a`.

1. Load a realistic student drawing and let the definition finish solving
   (press the Data Dam play button so the whole path is computed).
2. Press `run`. It lists how long every component took in the last solution,
   including components inside clusters, slowest first.
3. The same table is saved as gh_profile.csv in your home folder. Send that file
   back so optimisations can be targeted at what is actually slow.
"""
import os
import Grasshopper as gh

rows = []


def walk(doc, path):
    for o in doc.Objects:
        if isinstance(o, gh.Kernel.IGH_ActiveObject):
            ms = o.ProcessorTime.TotalMilliseconds
            count = 0
            try:  # size of the biggest output, to see how much data flows through
                for p in o.Params.Output:
                    count = max(count, p.VolatileDataCount)
            except Exception:
                try:
                    count = o.VolatileDataCount
                except Exception:
                    pass
            rows.append((ms, path, o.NickName, o.Name, count, str(o.InstanceGuid)))
        if isinstance(o, gh.Kernel.Special.GH_Cluster):
            inner = None
            for getter in (lambda c: c.Document(""), lambda c: c.InternalDocument):
                try:
                    inner = getter(o)
                    if inner is not None:
                        break
                except Exception:
                    pass
            if inner is not None:
                walk(inner, path + "/" + o.NickName)


if run:
    walk(ghenv.Component.OnPingDocument(), "main")
    rows.sort(key=lambda r: -r[0])
    lines = ["ms,where,nickname,component,items,guid"]
    lines += ['%.1f,"%s","%s","%s",%d,%s' % r for r in rows]
    path = os.path.join(os.path.expanduser("~"), "gh_profile.csv")
    with open(path, "w") as f:
        f.write("\n".join(lines))
    total = sum(r[0] for r in rows if r[1] == "main")
    a = ["Total (top level): %.0f ms   saved to %s" % (total, path)] + lines[1:41]
