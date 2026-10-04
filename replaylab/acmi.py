"""Tacview text ACMI (2.x) reader -- the format MiG Alley, Battle of Britain and FreeFalcon export.

Handles what the format allows, not only what our writers emit today:
  * `#<seconds>` frame lines, relative to the global ReferenceTime
  * `0,Key=Value` global properties (ReferenceLongitude/Latitude are offsets for every Lon/Lat)
  * `<hexid>,Prop=Value,...` object updates, where the T transform has 3 (Lon|Lat|Alt), 5 (Lon|Lat|Alt|U|V),
    6 (Lon|Lat|Alt|Roll|Pitch|Yaw) or 9 (Lon|Lat|Alt|Roll|Pitch|Yaw|U|V|Heading) fields and an EMPTY field means
    "unchanged" (partial updates)
  * `-<hexid>` object removal, `\\,` escaped commas, trailing-backslash line continuation, `//` comments
  * `.zip.acmi` / zip containers holding one text ACMI
Every other numeric property (IAS, TAS, AOA, AGL, Throttle, ...) becomes a sample-and-hold channel.
"""
import io
import math
import zipfile

T_FIELDS = {3: ("lon", "lat", "alt"),
            5: ("lon", "lat", "alt", "u", "v"),
            6: ("lon", "lat", "alt", "roll", "pitch", "yaw"),
            9: ("lon", "lat", "alt", "roll", "pitch", "yaw", "u", "v", "heading")}
POSE = ("lon", "lat", "alt", "roll", "pitch", "yaw", "u", "v", "heading")


class RawObject:
    """One object's samples as recorded: parallel lists, one entry per update of the object."""

    def __init__(self, oid):
        self.id = oid
        self.props = {}             # latest string properties (Name, Type, Color, Pilot, ...)
        self.t = []
        self.pose = {k: [] for k in POSE}
        self.channels = {}          # numeric property -> list aligned with self.t (None until first seen)
        self.removed_at = None
        self._state = {k: None for k in POSE}
        self._num = {}

    @property
    def name(self):
        return self.props.get("Name") or self.props.get("ShortName") or self.id

    def label(self):
        bits = [self.name]
        if self.props.get("Pilot"):
            bits.append("(%s)" % self.props["Pilot"])
        if self.props.get("Color"):
            bits.append(self.props["Color"])
        return " ".join(bits) + " #" + self.id


class Recording:
    def __init__(self):
        self.globals = {}
        self.objects = {}           # id -> RawObject, in order of first appearance
        self.events = []            # (t, text)
        self.ref_lon = 0.0
        self.ref_lat = 0.0
        self.source = ""

    def aircraft(self):
        """Objects that look like aircraft (Type Air+..., or anything with a transform when Type is absent)."""
        out = []
        for o in self.objects.values():
            ty = o.props.get("Type", "")
            if ("Air" in ty) or (not ty and o.t):
                out.append(o)
        return out

    def find(self, key):
        """An object by hex id, exact name, or 'player' (the Pilot=Player object)."""
        if key in self.objects:
            return self.objects[key]
        k = key.lower()
        for o in self.objects.values():
            if k == "player" and o.props.get("Pilot", "").lower() == "player":
                return o
        for o in self.objects.values():
            if o.name.lower() == k:
                return o
        raise KeyError("no object %r (have: %s)" % (key, ", ".join(o.label() for o in self.objects.values())))


def _split_props(s):
    """Split 'a=1,b=x\\,y' on unescaped commas."""
    out, cur, i = [], [], 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            cur.append(s[i + 1])
            i += 2
            continue
        if ch == ",":
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    out.append("".join(cur))
    # lenient: a fragment with no '=' is an unescaped comma inside the previous value (MA/BoB write
    # "DataSource=MiG Alley (Rowan, 1999)"; the format wants "\\,")
    merged = []
    for frag in out:
        if merged and "=" not in frag:
            merged[-1] += "," + frag
        else:
            merged.append(frag)
    return merged


def _num(s):
    try:
        v = float(s)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def _lines(text):
    """Logical lines: continuation (trailing backslash) joined, comments and blanks dropped."""
    pending = ""
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if line.endswith("\\") and not line.endswith("\\\\"):
            pending += line[:-1] + "\n"
            continue
        line = pending + line
        pending = ""
        s = line.strip()
        if not s or s.startswith("//"):
            continue
        yield s
    if pending.strip():
        yield pending.strip()


def read_text(text, source=""):
    rec = Recording()
    rec.source = source
    t = 0.0
    for line in _lines(text):
        if line.startswith("﻿"):
            line = line[1:]
        if line.startswith("#"):
            v = _num(line[1:])
            if v is not None:
                t = v
            continue
        if line.startswith("FileType=") or line.startswith("FileVersion="):
            k, _, v = line.partition("=")
            rec.globals[k] = v
            continue
        if line.startswith("-"):
            o = rec.objects.get(line[1:].strip().lower())
            if o is not None:
                o.removed_at = t
            continue
        head, sep, rest = line.partition(",")
        if not sep:
            continue
        oid = head.strip().lower()
        parts = _split_props(rest)
        if oid == "0":
            for p in parts:
                k, _, v = p.partition("=")
                if k == "Event":
                    rec.events.append((t, v))
                else:
                    rec.globals[k] = v
            if "ReferenceLongitude" in rec.globals:
                rec.ref_lon = _num(rec.globals["ReferenceLongitude"]) or 0.0
            if "ReferenceLatitude" in rec.globals:
                rec.ref_lat = _num(rec.globals["ReferenceLatitude"]) or 0.0
            continue
        o = rec.objects.get(oid)
        if o is None:
            o = rec.objects[oid] = RawObject(oid)
        moved = False
        for p in parts:
            k, _, v = p.partition("=")
            if k == "T":
                fields = v.split("|")
                names = T_FIELDS.get(len(fields))
                if names is None:
                    continue
                for name, f in zip(names, fields):
                    if f != "":
                        x = _num(f)
                        if x is not None:
                            if name == "lon":
                                x += rec.ref_lon
                            elif name == "lat":
                                x += rec.ref_lat
                            o._state[name] = x
                moved = True
            else:
                x = _num(v)
                if x is not None and k not in ("Color", "Name", "Type", "Pilot", "Group", "Coalition", "Country"):
                    o._num[k] = x
                    moved = True
                else:
                    o.props[k] = v
        if moved and o._state["alt"] is not None:
            if o.t and o.t[-1] == t:          # several lines for one object in one frame: keep the last state
                for k in POSE:
                    o.pose[k][-1] = o._state[k]
                for k, x in o._num.items():
                    o.channels.setdefault(k, [None] * len(o.t))[-1] = x
                continue
            o.t.append(t)
            for k in POSE:
                o.pose[k].append(o._state[k])
            for k in o.channels:
                o.channels[k].append(o._num.get(k))
            for k, x in o._num.items():
                if k not in o.channels:
                    o.channels[k] = [None] * (len(o.t) - 1) + [x]
    return rec


def read(path):
    with open(path, "rb") as f:
        data = f.read()
    if data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            data = z.read(z.namelist()[0])
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return read_text(data.decode(enc), source=path)
        except UnicodeDecodeError:
            continue
